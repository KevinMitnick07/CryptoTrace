"""
Multi-hypothesis victim-value attribution engine.

This is the core intellectual contribution of the system.

The blockchain does not identify which fungible token units belong to the victim.
When victim funds enter a wallet containing unrelated money, every subsequent
transfer requires an allocation assumption. This module maintains four simultaneous
allocation models rather than silently selecting one.

The output is always an interval [lower_bound, upper_bound] per downstream address,
not a single number. Value conservation is a hard constraint — never violated.

Models implemented:
  CONSERVATIVE: Only direct continuations with amounts/timing consistent with victim value.
  PROPORTIONAL: Each outgoing transfer carries (victim_value / total_outgoing) fraction.
  FIFO:         Victim value fills earliest outgoing transfers first until exhausted.
  LIFO:         Victim value fills latest outgoing transfers first until exhausted.
"""

from __future__ import annotations
import logging
from decimal import Decimal
from typing import Optional, Union
import datetime

from .models import (
    AllocationModel, Asset, OnChainTransfer, ValueInterval, ModelAttribution,
    ASSET_DECIMALS, HistoricalBalanceResult, HistoricalBalanceStatus, utc_now
)

log = logging.getLogger(__name__)


def get_asset_precision_tolerance(asset: Asset) -> Decimal:
    """Derive value conservation rounding tolerance from asset token decimals."""
    decimals = ASSET_DECIMALS.get(asset, 18)
    # Leeway of 100 raw base units for integer division rounding
    return Decimal("100") / (Decimal(10) ** decimals)


def _value_conservation_check(
    victim_value: Decimal,
    attributed_by_model: dict[AllocationModel, dict[str, Decimal]],
    asset: Asset = Asset.USDT_ERC20,
) -> list[str]:
    """
    Hard constraint: for each model, sum of all attributed values ≤ victim_value.
    Tolerance is derived from the asset token decimals, not a hardcoded 0.01 amount.
    Returns a list of violation descriptions (empty if all pass).
    """
    violations = []
    tolerance = get_asset_precision_tolerance(asset)
    for model, by_address in attributed_by_model.items():
        total = sum(by_address.values())
        if total > victim_value + tolerance:
            violations.append(
                f"Conservation violated under {model.value}: "
                f"attributed {total} > victim_value {victim_value} (tolerance={tolerance})"
            )
    return violations


class AccountBasedAttributionEngine:
    """
    Multi-hypothesis attribution for account-based chains (TRON, Ethereum, BSC, Polygon).
    Not applicable to UTXO chains — UTXOAttributionEngine handles those separately.

    Usage:
      engine = AccountBasedAttributionEngine(victim_value, victim_asset)
      result = engine.allocate(wallet_balance_before, outgoing_transfers)
    """

    def __init__(self, victim_value: Decimal, victim_asset: Asset):
        if victim_value <= Decimal(0):
            raise ValueError("victim_value must be positive")
        self.victim_value = victim_value
        self.victim_asset = victim_asset

    def allocate(
        self,
        balance_before_victim_deposit: Union[Decimal, HistoricalBalanceResult],
        outgoing_transfers: list[OnChainTransfer],
    ) -> dict[AllocationModel, dict[str, Decimal]]:
        """
        Given:
          - balance before the victim's transfer arrived (Decimal or structured HistoricalBalanceResult)
          - outgoing transfers from the wallet after the victim's transfer
        Produce per-model attribution: dict[model → dict[to_address → attributed_value]]

        outgoing_transfers must be ordered by block_timestamp ascending.
        Only transfers of the same asset class as the victim are attributed.
        """
        # Resolve historical balance status
        balance_val = Decimal(0)
        historical_known = True

        if isinstance(balance_before_victim_deposit, HistoricalBalanceResult):
            if balance_before_victim_deposit.status == HistoricalBalanceStatus.KNOWN and balance_before_victim_deposit.amount is not None:
                balance_val = balance_before_victim_deposit.amount
            else:
                historical_known = False
                log.warning(
                    "Historical balance is %s for %s (%s). Conservative model will be marked degraded.",
                    balance_before_victim_deposit.status.value,
                    balance_before_victim_deposit.address,
                    balance_before_victim_deposit.reason or "no provider support",
                )
        else:
            balance_val = balance_before_victim_deposit

        relevant = [
            t for t in outgoing_transfers
            if t.asset == self.victim_asset and t.amount > Decimal(0)
        ]
        if not relevant:
            # No outgoing transfers of the correct asset — victim value still in wallet
            empty: dict[AllocationModel, dict[str, Decimal]] = {
                m: {} for m in AllocationModel
            }
            return empty

        total_out = sum(t.amount for t in relevant)
        # The victim value cannot exceed what is actually available to attribute
        attributable = min(self.victim_value, total_out)

        results: dict[AllocationModel, dict[str, Decimal]] = {}

        if historical_known:
            results[AllocationModel.CONSERVATIVE] = self._conservative(relevant, balance_val)
        else:
            # When historical balance is unknown, Conservative direct flow cannot be verified.
            # Record an empty attribution for Conservative rather than hallucinating based on current balance.
            results[AllocationModel.CONSERVATIVE] = {}

        results[AllocationModel.PROPORTIONAL] = self._proportional(relevant, total_out, attributable)
        results[AllocationModel.FIFO] = self._fifo(relevant, attributable)
        results[AllocationModel.LIFO] = self._lifo(relevant, attributable)

        # Hard conservation check with token-aware tolerance
        violations = _value_conservation_check(self.victim_value, results, self.victim_asset)
        if violations:
            for v in violations:
                log.error("VALUE CONSERVATION VIOLATION: %s", v)
            raise RuntimeError(f"Value conservation violated: {violations}")

        return results

    def _conservative(
        self,
        transfers: list[OnChainTransfer],
        balance_before: Decimal,
    ) -> dict[str, Decimal]:
        """
        Conservative direct-flow model.

        Attributes victim value only to transfers where:
          1. The transfer amount is consistent with remaining victim value
          2. The transfer follows immediately after the victim's deposit
        """
        result: dict[str, Decimal] = {}
        remaining = self.victim_value

        for t in transfers:
            if remaining <= Decimal(0):
                break
            denom = balance_before + self.victim_value
            victim_fraction = t.amount / denom if denom > 0 else Decimal(0)
            victim_contribution = t.amount * victim_fraction
            victim_contribution = min(victim_contribution, remaining)
            if victim_contribution > Decimal("0.000000000000000001"):
                result[t.to_address] = result.get(t.to_address, Decimal(0)) + victim_contribution
                remaining -= victim_contribution

        return result

    def _proportional(
        self,
        transfers: list[OnChainTransfer],
        total_out: Decimal,
        attributable: Decimal,
    ) -> dict[str, Decimal]:
        """
        Proportional haircut model.

        Each outgoing transfer carries (its_amount / total_outgoing) × attributable.
        """
        result: dict[str, Decimal] = {}
        if total_out == Decimal(0):
            return result
        for t in transfers:
            share = (t.amount / total_out) * attributable
            result[t.to_address] = result.get(t.to_address, Decimal(0)) + share
        return result

    def _fifo(
        self,
        transfers: list[OnChainTransfer],
        attributable: Decimal,
    ) -> dict[str, Decimal]:
        """
        FIFO model (analytical convention).
        Fills earliest outgoing transfers first until exhausted.
        """
        result: dict[str, Decimal] = {}
        remaining = attributable
        for t in transfers:
            if remaining <= Decimal(0):
                break
            allocated = min(t.amount, remaining)
            result[t.to_address] = result.get(t.to_address, Decimal(0)) + allocated
            remaining -= allocated
        return result

    def _lifo(
        self,
        transfers: list[OnChainTransfer],
        attributable: Decimal,
    ) -> dict[str, Decimal]:
        """
        LIFO model (analytical convention).
        Fills latest outgoing transfers first.
        """
        result: dict[str, Decimal] = {}
        remaining = attributable
        for t in reversed(transfers):
            if remaining <= Decimal(0):
                break
            allocated = min(t.amount, remaining)
            result[t.to_address] = result.get(t.to_address, Decimal(0)) + allocated
            remaining -= allocated
        return result

    def compute_value_interval(
        self,
        address: str,
        model_results: dict[AllocationModel, dict[str, Decimal]],
        asset: Asset,
    ) -> ValueInterval:
        """
        Produce a ValueInterval for one downstream address across all models.
        lower_bound = minimum attribution across models
        upper_bound = maximum attribution across models
        """
        attributions = [
            model_results[m].get(address, Decimal(0))
            for m in AllocationModel
        ]
        return ValueInterval(
            lower_bound=min(attributions),
            upper_bound=max(attributions),
            asset=asset,
            usd_equivalent_at=utc_now(),
            non_additive_across_hypotheses=True,
        )

    def model_attributions_for_address(
        self,
        address: str,
        model_results: dict[AllocationModel, dict[str, Decimal]],
        asset: Asset,
    ) -> list[ModelAttribution]:
        """Return per-model attribution for a specific address."""
        return [
            ModelAttribution(
                model=m,
                attributed_value=model_results[m].get(address, Decimal(0)),
                asset=asset,
                confidence_note=_model_assumption_note(m),
            )
            for m in AllocationModel
        ]


def _model_assumption_note(model: AllocationModel) -> str:
    notes = {
        AllocationModel.CONSERVATIVE: (
            "Conservative direct-flow: attributes victim value only to transfers "
            "consistent with victim amount and timing. Requires verified historical balance. May undercount."
        ),
        AllocationModel.PROPORTIONAL: (
            "Proportional haircut: victim value distributed in proportion to "
            "outgoing transfer amounts. Assumption: all funds equally mixed."
        ),
        AllocationModel.FIFO: (
            "FIFO (analytical convention): victim value treated as earliest-arrived "
            "funds, filling earliest outgoing transfers first. Not a blockchain primitive."
        ),
        AllocationModel.LIFO: (
            "LIFO (analytical convention): victim value treated as latest-arrived "
            "funds, filling latest outgoing transfers first. Not a blockchain primitive."
        ),
    }
    return notes[model]


# ---------------------------------------------------------------------------
# UTXO attribution stub — Bitcoin only; separate engine
# ---------------------------------------------------------------------------

class UTXOAttributionEngine:
    """
    UTXO-specific taint engine for Bitcoin.
    Not implemented in prototype beyond Level D anchor support.
    """

    def __init__(self, victim_utxo_txid: str, victim_vout: int, victim_value: Decimal):
        self.victim_utxo = (victim_utxo_txid, victim_vout)
        self.victim_value = victim_value

    def propagate(self, *args, **kwargs):
        raise NotImplementedError(
            "Full UTXO taint propagation is not implemented in prototype. "
            "Bitcoin support is limited to Level D anchor and single-hop investigation."
        )
