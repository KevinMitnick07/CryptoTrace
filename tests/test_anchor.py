"""
Automated unit tests for Trace Anchor Resolver.
Testing confidence levels A, B, C, D and explicit ambiguity preservation.
"""

from __future__ import annotations
import datetime
from decimal import Decimal
import pytest

from backend.core.models import (
    Chain, Asset, AnchorLevel, AnchorStatus, ComplaintInput,
    OnChainTransfer, TxState, CandidateTransaction
)
from backend.core.anchor import AnchorResolver
from backend.core.evidence import ProvenanceStore
from tests.conftest import FakeChainAdapter


def test_level_a_exact_verified_transaction(fake_eth_adapter):
    """Level A: Transaction hash matches complaint fields exactly."""
    tx_hash = "0x_exact_tx_hash_01"
    transfer = OnChainTransfer(
        tx_hash=tx_hash,
        chain=Chain.ETHEREUM,
        asset=Asset.USDT_ERC20,
        amount=Decimal("5000.00"),
        from_address="0x_victim",
        to_address="0x_suspect",
        block_number=500,
        block_timestamp=datetime.datetime(2026, 8, 1, 10, 0),
        tx_state=TxState.CONFIRMED,
    )
    fake_eth_adapter.transactions[tx_hash] = transfer

    complaint = ComplaintInput(
        complaint_ref="NCRP-001",
        reported_wallet="0x_suspect",
        reported_chain=Chain.ETHEREUM,
        reported_asset=Asset.USDT_ERC20,
        reported_amount=Decimal("5000.00"),
        reported_tx_hash=tx_hash,
        reported_time_utc=None,
        complainant_payment_evidence=None,
    )

    prov = ProvenanceStore("CASE-01")
    resolver = AnchorResolver({Chain.ETHEREUM: fake_eth_adapter}, prov)
    anchor = resolver.resolve(complaint)

    assert anchor.status == AnchorStatus.VERIFIED
    assert anchor.level == AnchorLevel.A
    assert anchor.confirmed_tx is not None
    assert anchor.confirmed_tx.amount == Decimal("5000.00")
    assert len(prov.all_records()) == 1


def test_level_a_mismatch_surfaces_ambiguity(fake_eth_adapter):
    """Level A: Transaction hash exists but amount differs significantly (>1% tolerance)."""
    tx_hash = "0x_mismatched_tx_hash"
    transfer = OnChainTransfer(
        tx_hash=tx_hash,
        chain=Chain.ETHEREUM,
        asset=Asset.USDT_ERC20,
        amount=Decimal("1000.00"),  # Found on chain
        from_address="0x_victim",
        to_address="0x_suspect",
        block_number=500,
        block_timestamp=datetime.datetime(2026, 8, 1, 10, 0),
        tx_state=TxState.CONFIRMED,
    )
    fake_eth_adapter.transactions[tx_hash] = transfer

    complaint = ComplaintInput(
        complaint_ref="NCRP-002",
        reported_wallet="0x_suspect",
        reported_chain=Chain.ETHEREUM,
        reported_asset=Asset.USDT_ERC20,
        reported_amount=Decimal("5000.00"),  # Reported by victim
        reported_tx_hash=tx_hash,
        reported_time_utc=None,
        complainant_payment_evidence=None,
    )

    prov = ProvenanceStore("CASE-02")
    resolver = AnchorResolver({Chain.ETHEREUM: fake_eth_adapter}, prov)
    anchor = resolver.resolve(complaint)

    assert anchor.status == AnchorStatus.AMBIGUOUS
    assert anchor.level == AnchorLevel.A
    assert "amount mismatch" in anchor.ambiguity_reason


def test_level_b_single_candidate_verified(fake_eth_adapter):
    """Level B: Wallet + asset + amount + time matches exactly 1 candidate."""
    candidate = CandidateTransaction(
        tx_hash="0x_cand_01",
        chain=Chain.ETHEREUM,
        asset=Asset.USDT_ERC20,
        amount=Decimal("5000.00"),
        block_number=500,
        block_timestamp=datetime.datetime(2026, 8, 1, 10, 0),
        from_address="0x_victim",
        to_address="0x_suspect",
        tx_state=TxState.CONFIRMED,
        match_fields=["wallet", "asset", "amount", "time"],
    )
    fake_eth_adapter.anchor_candidates = [candidate]

    complaint = ComplaintInput(
        complaint_ref="NCRP-003",
        reported_wallet="0x_suspect",
        reported_chain=Chain.ETHEREUM,
        reported_asset=Asset.USDT_ERC20,
        reported_amount=Decimal("5000.00"),
        reported_tx_hash=None,
        reported_time_utc=datetime.datetime(2026, 8, 1, 10, 0),
        complainant_payment_evidence=None,
    )

    prov = ProvenanceStore("CASE-03")
    resolver = AnchorResolver({Chain.ETHEREUM: fake_eth_adapter}, prov)
    anchor = resolver.resolve(complaint)

    assert anchor.status == AnchorStatus.VERIFIED
    assert anchor.level == AnchorLevel.B
    assert anchor.confirmed_tx == candidate


def test_level_b_multiple_candidates_surface_ambiguity(fake_eth_adapter):
    """Level B: Multiple transactions match the reported criteria within the window."""
    cand1 = CandidateTransaction("0x_cand_01", Chain.ETHEREUM, Asset.USDT_ERC20, Decimal("5000.00"), 500, datetime.datetime(2026, 8, 1, 10, 0), "0x_v1", "0x_suspect", TxState.CONFIRMED, ["match"])
    cand2 = CandidateTransaction("0x_cand_02", Chain.ETHEREUM, Asset.USDT_ERC20, Decimal("5000.00"), 505, datetime.datetime(2026, 8, 1, 10, 15), "0x_v2", "0x_suspect", TxState.CONFIRMED, ["match"])
    fake_eth_adapter.anchor_candidates = [cand1, cand2]

    complaint = ComplaintInput(
        complaint_ref="NCRP-004",
        reported_wallet="0x_suspect",
        reported_chain=Chain.ETHEREUM,
        reported_asset=Asset.USDT_ERC20,
        reported_amount=Decimal("5000.00"),
        reported_tx_hash=None,
        reported_time_utc=datetime.datetime(2026, 8, 1, 10, 0),
        complainant_payment_evidence=None,
    )

    prov = ProvenanceStore("CASE-04")
    resolver = AnchorResolver({Chain.ETHEREUM: fake_eth_adapter}, prov)
    anchor = resolver.resolve(complaint)

    assert anchor.status == AnchorStatus.AMBIGUOUS
    assert anchor.level == AnchorLevel.B
    assert len(anchor.candidate_txs) == 2
    assert "Investigator review required" in anchor.ambiguity_reason


def test_level_c_payment_evidence(fake_eth_adapter):
    """Level C: Wallet with victim receipt reference but no exact amount or hash."""
    fake_eth_adapter.anchor_candidates = [
        CandidateTransaction("0x_c1", Chain.ETHEREUM, Asset.USDT_ERC20, Decimal("2000.00"), 500, datetime.datetime(2026, 8, 1, 10, 0), "0x_v", "0x_suspect", TxState.CONFIRMED, ["wallet"])
    ]

    complaint = ComplaintInput(
        complaint_ref="NCRP-005",
        reported_wallet="0x_suspect",
        reported_chain=Chain.ETHEREUM,
        reported_asset=None,
        reported_amount=None,
        reported_tx_hash=None,
        reported_time_utc=None,
        complainant_payment_evidence="Bank receipt #987654",
    )

    prov = ProvenanceStore("CASE-05")
    resolver = AnchorResolver({Chain.ETHEREUM: fake_eth_adapter}, prov)
    anchor = resolver.resolve(complaint)

    assert anchor.status == AnchorStatus.AMBIGUOUS
    assert anchor.level == AnchorLevel.C


def test_level_d_wallet_only():
    """Level D: Wallet only. Returns AMBIGUOUS with lowest confidence."""
    complaint = ComplaintInput(
        complaint_ref="NCRP-006",
        reported_wallet="0x_unknown_wallet",
        reported_chain=Chain.ETHEREUM,
        reported_asset=None,
        reported_amount=None,
        reported_tx_hash=None,
        reported_time_utc=None,
        complainant_payment_evidence=None,
    )

    prov = ProvenanceStore("CASE-06")
    resolver = AnchorResolver({}, prov)
    anchor = resolver.resolve(complaint)

    assert anchor.status == AnchorStatus.AMBIGUOUS
    assert anchor.level == AnchorLevel.D
    assert "Wallet address is the only complaint field" in anchor.ambiguity_reason
