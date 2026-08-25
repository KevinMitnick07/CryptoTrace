"""
Cross-case infrastructure convergence with service popularity normalization.

When multiple complaints trace through the same intermediary address, that
convergence is only meaningful if the address is not a high-volume public service.

Without normalization: Binance appears in 50 cases → false syndicate alert.
With normalization:    Binance appears in 50 cases → NEGLIGIBLE signal (baseline).
                       Unknown wallet X appears in 4 cases → HIGH signal.

The normalization approach:
  - Maintain a monthly transaction volume estimate per address/cluster
  - Classify addresses into popularity tiers
  - Adjust convergence signal weight by inverse popularity
  - Require multiple corroborating signals before producing a finding

Output: CrossCaseSignal with normalized_rarity and explicit alternative_explanation.
"""

from __future__ import annotations
import logging
from collections import defaultdict
from decimal import Decimal
from typing import Optional
import datetime

from .models import Chain, CrossCaseSignal

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Service popularity classification
# Estimated monthly transaction counts for known high-volume services.
# Used to normalize convergence signals.
#
# IMPORTANT: These are order-of-magnitude prototype estimates derived from
# publicly available data and SIH synthetic scenarios. They are NOT live
# on-chain measurements. All normalized_rarity values derived from this
# table are labeled "SYNTHETIC_BASELINE" in CrossCaseSignal output.
# Do NOT treat these as authoritative transaction volumes in a forensic
# submission without independent verification.
# ---------------------------------------------------------------------------

SERVICE_MONTHLY_VOLUMES: dict[str, int] = {
    "Binance": 10_000_000,
    "OKX": 3_000_000,
    "Huobi": 2_000_000,
    "Kraken": 500_000,
    "ByBit": 1_000_000,
    "Uniswap v2 Router": 5_000_000,
    "Uniswap v3 Router": 8_000_000,
    "Multichain Bridge": 200_000,
    "Tornado Cash": 50_000,
}

# Inline label applied to all rarity values derived from SERVICE_MONTHLY_VOLUMES
_SYNTHETIC_RARITY_PREFIX = "SYNTHETIC_BASELINE:"


def _popularity_rarity(entity_name: Optional[str], address_monthly_volume: Optional[int]) -> str:
    """
    Classify the rarity of convergence on this service.
    Returns a prefixed label to make clear this is derived from a synthetic baseline:
      SYNTHETIC_BASELINE:NEGLIGIBLE -- major public exchange, convergence expected by chance
      SYNTHETIC_BASELINE:LOW        -- mid-volume service, convergence weakly informative
      SYNTHETIC_BASELINE:MEDIUM     -- lower-volume service, convergence somewhat informative
      SYNTHETIC_BASELINE:HIGH       -- rare/low-volume service, convergence potentially significant
    UNKNOWN                         -- no volume estimate available at all
    """
    if entity_name:
        volume = SERVICE_MONTHLY_VOLUMES.get(entity_name, address_monthly_volume or 0)
    else:
        volume = address_monthly_volume or 0

    if volume == 0:
        return "UNKNOWN"
    if volume > 1_000_000:
        tier = "NEGLIGIBLE"
    elif volume > 100_000:
        tier = "LOW"
    elif volume > 10_000:
        tier = "MEDIUM"
    else:
        tier = "HIGH"
    return f"{_SYNTHETIC_RARITY_PREFIX}{tier}"


# ---------------------------------------------------------------------------
# Convergence analyzer
# ---------------------------------------------------------------------------

class CaseConvergenceAnalyzer:
    """
    Detects potentially shared infrastructure across multiple investigation cases.

    For each intermediary address that appears in multiple cases, produces
    a CrossCaseSignal with normalized rarity and required corroboration checks.
    """

    def __init__(self, vasp_registry):
        self._registry = vasp_registry   # VaspRegistry instance
        # case_id → set of intermediary addresses seen during traversal
        self._case_intermediaries: dict[str, set[str]] = defaultdict(set)
        # case_id → chain of the intermediary
        self._case_chains: dict[str, Chain] = {}
        # case_id → timestamps of traversal events at each address
        self._case_timestamps: dict[str, dict[str, datetime.datetime]] = defaultdict(dict)
        # case_id → amounts at each address (approximate victim-attributed)
        self._case_amounts: dict[str, dict[str, Decimal]] = defaultdict(dict)

    def register_case_address(
        self,
        case_id: str,
        address: str,
        chain: Chain,
        timestamp: Optional[datetime.datetime],
        victim_attributed_amount: Optional[Decimal],
    ) -> None:
        """Record an intermediary address seen during case traversal."""
        self._case_intermediaries[case_id].add(f"{chain.value}:{address.lower()}")
        if timestamp:
            self._case_timestamps[case_id][address.lower()] = timestamp
        if victim_attributed_amount:
            self._case_amounts[case_id][address.lower()] = victim_attributed_amount

    def find_shared_infrastructure(
        self,
        min_cases: int = 2,
    ) -> list[CrossCaseSignal]:
        """
        Find addresses that appear as intermediaries in multiple cases.
        Apply popularity normalization and corroboration checks.
        Returns CrossCaseSignal entries only for statistically non-trivial convergence.
        """
        # Count cases per address
        address_to_cases: dict[str, list[str]] = defaultdict(list)
        for case_id, addresses in self._case_intermediaries.items():
            for addr_key in addresses:
                address_to_cases[addr_key].append(case_id)

        signals: list[CrossCaseSignal] = []

        for addr_key, case_refs in address_to_cases.items():
            if len(case_refs) < min_cases:
                continue

            parts = addr_key.split(":", 1)
            if len(parts) != 2:
                continue
            chain_str, address = parts
            try:
                chain = Chain(chain_str)
            except ValueError:
                continue

            # Look up entity (if known)
            vasp_record = self._registry.get(chain, address)
            entity_name = vasp_record.entity_name if vasp_record else None

            # Normalize rarity
            rarity = _popularity_rarity(entity_name, None)

            # Corroboration checks
            timing_similar = self._check_timing_similarity(address, case_refs)
            amount_related = self._check_amount_relationship(address, case_refs)
            shared_upstream = self._check_shared_upstream(case_refs, addr_key)

            # Alternative explanation
            if entity_name and SERVICE_MONTHLY_VOLUMES.get(entity_name, 0) > 500_000:
                alternative = (
                    f"{entity_name} is a high-volume public service "
                    f"(prototype estimate: {SERVICE_MONTHLY_VOLUMES.get(entity_name, 0):,} "
                    "transactions/month — synthetic baseline, not live measurement). "
                    "Convergence on this address is expected by chance and "
                    "does not independently indicate coordination."
                )
            elif entity_name:
                alternative = (
                    f"{entity_name} is a recognized service. "
                    "Verify transaction volume independently before treating convergence as significant. "
                    "Volume baseline used here is a synthetic prototype estimate."
                )
            else:
                alternative = (
                    "Address is unattributed in the VASP registry. If it is a legitimate high-volume service "
                    "not registered, convergence may be coincidental. "
                    "Manual on-chain volume verification is recommended before drawing conclusions."
                )

            convergence_note = _convergence_note(
                case_count=len(case_refs),
                rarity=rarity,
                timing_similar=timing_similar,
                amount_related=amount_related,
                shared_upstream=shared_upstream,
            )

            signal = CrossCaseSignal(
                shared_address=address,
                chain=chain,
                case_refs=case_refs,
                service_baseline_txcount=SERVICE_MONTHLY_VOLUMES.get(entity_name or "", None),
                normalized_rarity=rarity,
                timing_similarity=timing_similar,
                amount_relationship=amount_related,
                shared_upstream=shared_upstream,
                alternative_explanation=alternative,
                convergence_note=convergence_note,
            )
            signals.append(signal)

        # Sort: highest rarity first, then most cases
        rarity_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "NEGLIGIBLE": 3}
        signals.sort(key=lambda s: (rarity_order.get(s.normalized_rarity, 4), -len(s.case_refs)))

        return signals

    def _check_timing_similarity(self, address: str, case_ids: list[str]) -> bool:
        """
        Cases are timing-similar if transactions at this address occur within
        a 24-hour window across cases. Simple heuristic.
        """
        timestamps = [
            self._case_timestamps[c].get(address)
            for c in case_ids
            if self._case_timestamps[c].get(address)
        ]
        if len(timestamps) < 2:
            return False
        earliest = min(timestamps)
        latest = max(timestamps)
        return (latest - earliest).total_seconds() <= 86400  # 24 hours

    def _check_amount_relationship(self, address: str, case_ids: list[str]) -> bool:
        """
        Cases have an amount relationship if the attributed amounts are similar
        (within 20% of each other). Simplified check.
        """
        amounts = [
            self._case_amounts[c].get(address)
            for c in case_ids
            if self._case_amounts[c].get(address)
        ]
        if len(amounts) < 2:
            return False
        amounts_f = [float(a) for a in amounts]
        avg = sum(amounts_f) / len(amounts_f)
        if avg == 0:
            return False
        max_dev = max(abs(a - avg) / avg for a in amounts_f)
        return max_dev <= 0.20

    def _check_shared_upstream(self, case_ids: list[str], current_addr_key: str) -> bool:
        """
        Check if the converging cases also share an intermediary address
        upstream of the current address. If yes, convergence is more significant.
        """
        shared_count = 0
        for addr_key, addr_cases in self._get_all_shared():
            if addr_key == current_addr_key:
                continue
            overlap = [c for c in addr_cases if c in case_ids]
            if len(overlap) >= len(case_ids):
                shared_count += 1
        return shared_count > 0

    def _get_all_shared(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = defaultdict(list)
        for case_id, addresses in self._case_intermediaries.items():
            for addr_key in addresses:
                result[addr_key].append(case_id)
        return {k: v for k, v in result.items() if len(v) >= 2}


def _convergence_note(
    case_count: int,
    rarity: str,
    timing_similar: bool,
    amount_related: bool,
    shared_upstream: bool,
) -> str:
    corroborations = []
    if timing_similar:
        corroborations.append("timing similarity")
    if amount_related:
        corroborations.append("amount relationship")
    if shared_upstream:
        corroborations.append("shared upstream intermediary")

    corroboration_str = (
        f"Corroborating signals: {', '.join(corroborations)}."
        if corroborations else "No additional corroborating signals found."
    )

    return (
        f"{case_count} cases converge on this address. "
        f"Normalized rarity: {rarity}. {corroboration_str} "
        "This is a potential shared infrastructure signal, not evidence of a common criminal group."
    )
