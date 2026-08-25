"""
Tests for Forensic Evidence Package generation, sanitization, and SHA-256 integrity hashing.
"""

from decimal import Decimal
import json
import hashlib
import pytest

from backend.core.models import (
    InvestigationCase, ComplaintInput, TraceAnchor, AnchorStatus, AnchorLevel,
    CaseState, TraceabilityState, ActionabilityState, ValueInterval,
    Asset, Chain, OnChainTransfer, TxState, PathSegment, EvidenceClass,
    AllocationModel, VaspRecord, VaspAttribution, AttributionSource,
    AttributionConfidence, EndpointStability, utc_now
)
from backend.core.evidence_package import EvidencePackageGenerator


def test_evidence_package_generation_and_hash():
    now = utc_now()
    intake = ComplaintInput(
        complaint_ref="TEST-REF-999",
        reported_wallet="0x_test_victim_reported",
        reported_chain=Chain.ETHEREUM,
        reported_asset=Asset.USDT_ERC20,
        reported_amount=Decimal("15000.00"),
        reported_tx_hash="0x_anchor_tx_hash_123",
        complainant_payment_evidence="Victim bank statement ref #12345",
    )

    anchor = TraceAnchor(
        status=AnchorStatus.VERIFIED,
        level=AnchorLevel.A,
        chain=Chain.ETHEREUM,
        asset=Asset.USDT_ERC20,
        tx_hash="0x_anchor_tx_hash_123",
        amount=Decimal("15000.00"),
        reported_time=now,
        confirmed_tx=None,
        anchor_evidence="Confirmed on-chain transfer hash matches complaint.",
    )

    vasp_rec = VaspRecord(
        address="0x_binance_deposit_01",
        chain=Chain.ETHEREUM,
        entity_name="Binance",
        entity_role="deposit_infrastructure",
        source=AttributionSource.COMMERCIAL_INTELLIGENCE,
        source_reliability="HIGH",
        first_observed=now,
        last_verified=now,
        confidence=AttributionConfidence.HIGH,
        is_active=True,
        independent_corroboration=True,
    )

    primary_vasp = VaspAttribution(
        record=vasp_rec,
        address_in_path="0x_binance_deposit_01",
        hop_from_anchor=1,
        victim_value_interval=ValueInterval(Decimal("15000.00"), Decimal("15000.00"), Asset.USDT_ERC20),
        per_model=[],
        first_hop_reaching_vasp=True,
        is_primary_stable=True,
        endpoint_stability=EndpointStability.HIGH,
        stability_reason="High consensus across all allocation models.",
        actionability=ActionabilityState.SUPPORTED_VASP,
    )

    case = InvestigationCase(
        case_id="CASE-UNIT-TEST-01",
        complaint=intake,
        anchor=anchor,
        state=CaseState.SUPPORTED_VASP,
        traceability=TraceabilityState.DETERMINISTIC,
        actionability=ActionabilityState.SUPPORTED_VASP,
        path_segments=[],
        branch_audit=[],
        vasp_candidates=[primary_vasp],
        cross_case_signals=[],
        claims=[],
        first_supported_vasp=primary_vasp,
        primary_stable_vasp=primary_vasp,
        unresolved_value=ValueInterval(Decimal(0), Decimal(0), Asset.USDT_ERC20),
    )

    generator = EvidencePackageGenerator(case, investigator_id="INVESTIGATOR-TEST")
    pkg = generator.build_package_dict()

    assert "package_integrity_sha256" in pkg["metadata"]
    assert len(pkg["metadata"]["package_integrity_sha256"]) == 64

    # Test Markdown export
    md = generator.export_markdown()
    assert "# FORENSIC BLOCKCHAIN EVIDENCE PACKAGE" in md
    assert "CASE-UNIT-TEST-01" in md
    assert "Binance" in md
    assert pkg["metadata"]["package_integrity_sha256"] in md
