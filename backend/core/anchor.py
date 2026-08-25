"""
Trace anchor resolver.

Takes a victim complaint and produces a TraceAnchor — the resolved starting
point for fund tracing. This must happen before any graph traversal.

The anchor level determines the confidence of everything downstream.
A wallet-only complaint (Level D) produces ambiguous results throughout.
The system must never silently convert a Level D complaint into a confirmed trace.
"""

from __future__ import annotations
import logging
from decimal import Decimal
from typing import Optional
import datetime

from .models import (
    Chain, Asset, AnchorLevel, AnchorStatus,
    TraceAnchor, CandidateTransaction, ComplaintInput, utc_now
)
from .evidence import EvidenceRecord, ProvenanceStore, hash_payload, make_record_id, EvidenceClass

log = logging.getLogger(__name__)


class AnchorResolver:
    """
    Resolves a victim complaint to a TraceAnchor using the chain adapters.
    The adapter registry maps Chain → ChainAdapter.
    """

    def __init__(self, adapters: dict, provenance: ProvenanceStore):
        self._adapters = adapters   # dict[Chain, ChainAdapter]
        self._prov = provenance

    def resolve(self, complaint: ComplaintInput) -> TraceAnchor:
        """
        Attempt anchor resolution in descending confidence order.
        Returns the highest-confidence anchor achievable from the complaint fields.
        """
        # Level A: complaint supplies a transaction hash
        if complaint.reported_tx_hash:
            return self._resolve_level_a(complaint)

        # Level B: wallet + asset + exact amount + timestamp
        if (
            complaint.reported_wallet
            and complaint.reported_asset
            and complaint.reported_amount is not None
            and complaint.reported_time_utc is not None
        ):
            return self._resolve_level_b(complaint)

        # Level C: wallet + victim payment evidence but no hash/amount
        if complaint.reported_wallet and complaint.complainant_payment_evidence:
            return self._resolve_level_c(complaint)

        # Level D: wallet only
        return self._resolve_level_d(complaint)

    def _resolve_level_a(self, complaint: ComplaintInput) -> TraceAnchor:
        """
        Fetch the transaction and confirm it matches the complaint fields.
        If the hash resolves but fields differ, return AMBIGUOUS rather than
        silently accepting a mismatched transaction.
        """
        chain = complaint.reported_chain
        tx_hash = complaint.reported_tx_hash
        adapter = self._adapters.get(chain)
        if adapter is None:
            return TraceAnchor(
                status=AnchorStatus.UNRESOLVABLE,
                level=AnchorLevel.A,
                chain=chain,
                asset=complaint.reported_asset,
                tx_hash=tx_hash,
                amount=complaint.reported_amount,
                reported_time=complaint.reported_time_utc,
                confirmed_tx=None,
                anchor_evidence="No chain adapter available for chain.",
            )

        transfer = adapter.get_tx(tx_hash)
        if transfer is None:
            return TraceAnchor(
                status=AnchorStatus.UNRESOLVABLE,
                level=AnchorLevel.A,
                chain=chain,
                asset=complaint.reported_asset,
                tx_hash=tx_hash,
                amount=complaint.reported_amount,
                reported_time=complaint.reported_time_utc,
                confirmed_tx=None,
                anchor_evidence="Transaction hash not found on chain.",
            )

        # Validate that the fetched transaction matches complaint fields
        mismatches = []
        if complaint.reported_asset and transfer.asset != complaint.reported_asset:
            mismatches.append(f"asset mismatch: reported {complaint.reported_asset}, found {transfer.asset}")
        if complaint.reported_amount is not None:
            tolerance = complaint.reported_amount * Decimal("0.01")
            if abs(transfer.amount - complaint.reported_amount) > tolerance:
                mismatches.append(
                    f"amount mismatch: reported {complaint.reported_amount}, found {transfer.amount}"
                )
        if complaint.reported_wallet:
            reported_wallet = complaint.reported_wallet.lower()
            if (reported_wallet not in transfer.to_address.lower()
                    and reported_wallet not in transfer.from_address.lower()):
                mismatches.append("wallet address not in transaction parties")

        record_id = make_record_id("anchor_a", tx_hash, None)
        self._prov.add_record(EvidenceRecord(
            record_id=record_id,
            evidence_class=EvidenceClass.OBSERVED,
            chain=transfer.chain,
            tx_hash=tx_hash,
            block_number=transfer.block_number,
            block_timestamp=transfer.block_timestamp,
            address=transfer.to_address,
            data_source=f"chain_adapter:{chain.value}",
            source_timestamp=utc_now(),
            raw_data_hash=hash_payload({"tx_hash": tx_hash}),
            description=f"Level A anchor resolution for tx {tx_hash}",
            assumptions=[],
        ))

        if mismatches:
            return TraceAnchor(
                status=AnchorStatus.AMBIGUOUS,
                level=AnchorLevel.A,
                chain=chain,
                asset=complaint.reported_asset,
                tx_hash=tx_hash,
                amount=complaint.reported_amount,
                reported_time=complaint.reported_time_utc,
                confirmed_tx=None,
                candidate_txs=[CandidateTransaction(
                    tx_hash=transfer.tx_hash,
                    chain=transfer.chain,
                    asset=transfer.asset,
                    amount=transfer.amount,
                    block_number=transfer.block_number,
                    block_timestamp=transfer.block_timestamp,
                    from_address=transfer.from_address,
                    to_address=transfer.to_address,
                    tx_state=transfer.tx_state,
                    match_fields=["tx_hash"],
                )],
                ambiguity_reason="; ".join(mismatches),
            )

        confirmed = CandidateTransaction(
            tx_hash=transfer.tx_hash,
            chain=transfer.chain,
            asset=transfer.asset,
            amount=transfer.amount,
            block_number=transfer.block_number,
            block_timestamp=transfer.block_timestamp,
            from_address=transfer.from_address,
            to_address=transfer.to_address,
            tx_state=transfer.tx_state,
            match_fields=["tx_hash", "amount", "asset", "wallet"],
        )
        return TraceAnchor(
            status=AnchorStatus.VERIFIED,
            level=AnchorLevel.A,
            chain=transfer.chain,
            asset=transfer.asset,
            tx_hash=tx_hash,
            amount=transfer.amount,
            reported_time=complaint.reported_time_utc,
            confirmed_tx=confirmed,
            anchor_evidence=(
                f"Victim transaction record + confirmed on-chain transfer. "
                f"Block {transfer.block_number}. State: {transfer.tx_state.value}."
            ),
        )

    def _resolve_level_b(self, complaint: ComplaintInput) -> TraceAnchor:
        """
        Search for candidate transactions matching wallet + asset + amount + timestamp window.
        Returns VERIFIED if exactly one candidate, AMBIGUOUS if multiple.
        """
        chain = complaint.reported_chain
        adapter = self._adapters.get(chain)
        if adapter is None:
            return _unresolvable(complaint, AnchorLevel.B, "No adapter for chain.")

        candidates = adapter.resolve_anchor_candidates(
            wallet=complaint.reported_wallet,
            asset=complaint.reported_asset,
            amount=complaint.reported_amount,
            reported_time=complaint.reported_time_utc,
            time_window_minutes=60,
        )

        if not candidates:
            return TraceAnchor(
                status=AnchorStatus.UNRESOLVABLE,
                level=AnchorLevel.B,
                chain=chain,
                asset=complaint.reported_asset,
                tx_hash=None,
                amount=complaint.reported_amount,
                reported_time=complaint.reported_time_utc,
                confirmed_tx=None,
                anchor_evidence="No on-chain transfers match reported wallet, asset, amount, and timestamp.",
            )

        if len(candidates) == 1:
            c = candidates[0]
            return TraceAnchor(
                status=AnchorStatus.VERIFIED,
                level=AnchorLevel.B,
                chain=chain,
                asset=c.asset,
                tx_hash=c.tx_hash,
                amount=c.amount,
                reported_time=complaint.reported_time_utc,
                confirmed_tx=c,
                anchor_evidence=(
                    f"Single candidate transaction matching wallet + asset + amount + "
                    f"60-minute timestamp window. Block {c.block_number}."
                ),
            )

        # Multiple candidates — require investigator to select
        return TraceAnchor(
            status=AnchorStatus.AMBIGUOUS,
            level=AnchorLevel.B,
            chain=chain,
            asset=complaint.reported_asset,
            tx_hash=None,
            amount=complaint.reported_amount,
            reported_time=complaint.reported_time_utc,
            confirmed_tx=None,
            candidate_txs=candidates,
            ambiguity_reason=(
                f"{len(candidates)} candidate transactions match the reported fields. "
                "Investigator review required to select the correct transaction."
            ),
        )

    def _resolve_level_c(self, complaint: ComplaintInput) -> TraceAnchor:
        """
        Wallet with payment evidence but no hash or exact amount.
        Fetch recent incoming transfers and flag for investigator review.
        """
        chain = complaint.reported_chain
        adapter = self._adapters.get(chain)
        if adapter is None:
            return _unresolvable(complaint, AnchorLevel.C, "No adapter for chain.")

        candidates = adapter.resolve_anchor_candidates(
            wallet=complaint.reported_wallet,
            asset=complaint.reported_asset,
            amount=None,
            reported_time=complaint.reported_time_utc,
            time_window_minutes=120,
        )

        return TraceAnchor(
            status=AnchorStatus.AMBIGUOUS,
            level=AnchorLevel.C,
            chain=chain,
            asset=complaint.reported_asset,
            tx_hash=None,
            amount=complaint.reported_amount,
            reported_time=complaint.reported_time_utc,
            confirmed_tx=None,
            candidate_txs=candidates[:10],  # Surface at most 10 candidates
            ambiguity_reason=(
                f"Anchor based on wallet + complainant payment evidence. "
                f"{len(candidates)} candidate transfers found. "
                "Investigator review required."
            ),
        )

    def _resolve_level_d(self, complaint: ComplaintInput) -> TraceAnchor:
        """
        Wallet-only. Lowest confidence. Must be marked throughout the investigation.
        No attempt to identify a specific transaction — investigator must anchor manually.
        """
        return TraceAnchor(
            status=AnchorStatus.AMBIGUOUS,
            level=AnchorLevel.D,
            chain=complaint.reported_chain,
            asset=complaint.reported_asset,
            tx_hash=None,
            amount=complaint.reported_amount,
            reported_time=complaint.reported_time_utc,
            confirmed_tx=None,
            candidate_txs=[],
            ambiguity_reason=(
                "Wallet address is the only complaint field available. "
                "No specific transaction can be identified without additional evidence. "
                "All downstream attribution carries LEVEL-D anchor confidence."
            ),
        )


def _unresolvable(complaint: ComplaintInput, level: AnchorLevel, reason: str) -> TraceAnchor:
    return TraceAnchor(
        status=AnchorStatus.UNRESOLVABLE,
        level=level,
        chain=complaint.reported_chain,
        asset=complaint.reported_asset,
        tx_hash=complaint.reported_tx_hash,
        amount=complaint.reported_amount,
        reported_time=complaint.reported_time_utc,
        confirmed_tx=None,
        anchor_evidence=reason,
    )
