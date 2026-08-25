"""
Chain adapter interface and finality policy specifications.

Each chain has different transaction and finality semantics.
This module defines the contract; chain-specific modules implement it.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
from decimal import Decimal
import datetime

from ..core.models import (
    Chain, Asset, OnChainTransfer, TxState, TraceAnchor,
    AnchorLevel, AnchorStatus, CandidateTransaction, FinalityType,
    HistoricalBalanceResult, HistoricalBalanceStatus
)


ADAPTER_VERSIONS: dict[str, str] = {
    "tron": "0.2.0-sprint",
    "ethereum": "0.2.0-sprint",
    "bitcoin": "0.2.0-sprint",
    "arbitrum": "0.2.0-sprint",
}


@dataclass
class FinalizationPolicy:
    """
    Chain-specific investigative confirmation policy.
    Explicitly distinct from protocol-level deterministic finality / solidification.
    """
    chain: Chain
    investigative_confirmed_blocks: int    # Minimum local confirmations for forensic confidence
    heuristic_finality_blocks: int         # Heuristic block threshold when provider state is absent
    avg_block_time_seconds: float          # Estimated block interval


FINALIZATION_POLICIES: dict[Chain, FinalizationPolicy] = {
    Chain.TRON: FinalizationPolicy(
        chain=Chain.TRON,
        investigative_confirmed_blocks=20,
        heuristic_finality_blocks=27,
        avg_block_time_seconds=3.0,
    ),
    Chain.ETHEREUM: FinalizationPolicy(
        chain=Chain.ETHEREUM,
        investigative_confirmed_blocks=6,
        heuristic_finality_blocks=64,   # 2 epochs post-Merge (approximate heuristic)
        avg_block_time_seconds=12.0,
    ),
    Chain.BITCOIN: FinalizationPolicy(
        chain=Chain.BITCOIN,
        investigative_confirmed_blocks=3,
        heuristic_finality_blocks=6,
        avg_block_time_seconds=600.0,
    ),
}


class ChainAdapter(ABC):
    """
    Abstract interface for chain-specific data access.
    Callers receive domain types; raw chain responses stay inside the adapter.
    """

    @property
    @abstractmethod
    def chain(self) -> Chain:
        ...

    @property
    @abstractmethod
    def version(self) -> str:
        ...

    @abstractmethod
    def get_tx(self, tx_hash: str) -> Optional[OnChainTransfer]:
        """Fetch a single transaction by hash. Returns None if not found."""
        ...

    @abstractmethod
    def get_transfers_from(
        self,
        address: str,
        asset: Optional[Asset],
        after_block: Optional[int],
        before_block: Optional[int],
        limit: int = 50,
    ) -> list[OnChainTransfer]:
        """
        Outgoing token transfers from an address.
        after_block and before_block are inclusive.
        """
        ...

    @abstractmethod
    def get_transfers_to(
        self,
        address: str,
        asset: Optional[Asset],
        after_block: Optional[int],
        before_block: Optional[int],
        limit: int = 50,
    ) -> list[OnChainTransfer]:
        """Incoming token transfers to an address."""
        ...

    @abstractmethod
    def get_historical_balance(
        self, address: str, asset: Asset, at_block: Optional[int] = None
    ) -> HistoricalBalanceResult:
        """
        Account balance at a specific block, returning structured status.
        Never silently replaces historical balance with current balance.
        """
        ...

    def get_balance(self, address: str, asset: Asset, at_block: Optional[int] = None) -> Decimal:
        """Legacy helper returning balance amount or Decimal(0) if unknown."""
        res = self.get_historical_balance(address, asset, at_block)
        return res.amount if (res.status == HistoricalBalanceStatus.KNOWN and res.amount is not None) else Decimal(0)

    @abstractmethod
    def get_current_block(self) -> int:
        """Latest block number."""
        ...

    def classify_tx_state(
        self, tx_block: int, provider_finalized_block: Optional[int] = None
    ) -> tuple[TxState, FinalityType]:
        """
        Derive both TxState and explicit FinalityType.
        If provider_finalized_block is provided and tx_block <= provider_finalized_block:
          Returns (FINALITY_THRESHOLD_REACHED, PROTOCOL_FINALIZED / SOLIDIFIED).
        Otherwise falls back to investigative confirmation count.
        """
        # Protocol-level finality check
        if provider_finalized_block is not None and tx_block <= provider_finalized_block:
            finality_type = FinalityType.SOLIDIFIED if self.chain == Chain.TRON else FinalityType.PROTOCOL_FINALIZED
            return TxState.FINALITY_THRESHOLD_REACHED, finality_type

        policy = FINALIZATION_POLICIES.get(self.chain)
        if not policy:
            return TxState.SEEN, FinalityType.OBSERVED

        current = self.get_current_block()
        confirmations = current - tx_block
        if confirmations < 0:
            return TxState.SEEN, FinalityType.OBSERVED
        if confirmations < policy.investigative_confirmed_blocks:
            return TxState.SEEN, FinalityType.OBSERVED
        if confirmations < policy.heuristic_finality_blocks:
            return TxState.CONFIRMED, FinalityType.INVESTIGATIVE_CONFIRMATION_POLICY
        return TxState.FINALITY_THRESHOLD_REACHED, FinalityType.INVESTIGATIVE_CONFIRMATION_POLICY

    def resolve_anchor_candidates(
        self,
        wallet: str,
        asset: Optional[Asset],
        amount: Optional[Decimal],
        reported_time: Optional[datetime.datetime],
        time_window_minutes: int = 60,
    ) -> list[CandidateTransaction]:
        """
        Find on-chain transactions matching complaint criteria.
        """
        return []
