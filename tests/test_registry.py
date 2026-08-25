"""
Automated unit tests for VASP Intelligence Registry & Chain Limitations.
Testing known entities, staleness rules, multi-source conflict preservation, and TRON historical balance limitations.
"""

from __future__ import annotations
import datetime
from decimal import Decimal
import logging
import pytest

from backend.core.models import (
    Chain, Asset, AttributionSource, AttributionConfidence, VaspClaimStatus
)
from backend.vasp.registry import VaspRegistry
from backend.chains.tron import TronAdapter


def test_registry_known_entity(test_registry):
    record = test_registry.get(Chain.ETHEREUM, "0x_okx_hot_01")
    assert record is not None
    assert record.entity_name == "OKX"
    assert record.entity_role == "deposit_infrastructure"
    assert record.confidence == AttributionConfidence.HIGH


def test_registry_unknown_address(test_registry):
    record = test_registry.get(Chain.ETHEREUM, "0x000000000000000000000000000000000000dead")
    assert record is None


def test_registry_stale_record_detection(test_registry):
    # Binance record last_verified in 2025-06-01 (>180 days ago)
    record = test_registry.get(Chain.ETHEREUM, "0x28c6c06298d514db089934071355e5743bf21d60")
    assert record is not None
    assert record.is_stale(threshold_days=180) is True
    assert record.confidence == AttributionConfidence.STALE


def test_registry_active_record(test_registry):
    record = test_registry.get(Chain.ETHEREUM, "0x_okx_hot_01")
    assert record is not None
    assert record.is_stale(threshold_days=180) is False
    assert record.confidence == AttributionConfidence.HIGH


def test_registry_conflicting_record_preservation():
    """
    Validates non-destructive multi-source claim preservation:
    Conflicting source attributions are preserved with CONFLICTED status and DISPUTED confidence.
    """
    records = [
        {
            "chain": "ETHEREUM",
            "address": "0x_disputed_address",
            "entity_name": "Exchange_Alpha",
            "source": "INTERNAL_LEA",
            "first_observed": "2024-01-01T00:00:00",
            "last_verified": "2026-01-01T00:00:00",
            "confidence": "HIGH",
        },
        {
            "chain": "ETHEREUM",
            "address": "0x_disputed_address",
            "entity_name": "Exchange_Beta",
            "source": "COMMERCIAL_INTELLIGENCE",
            "first_observed": "2024-01-01T00:00:00",
            "last_verified": "2026-01-01T00:00:00",
            "confidence": "HIGH",
        }
    ]
    registry = VaspRegistry(records)
    lookup_res = registry.lookup(Chain.ETHEREUM, "0x_disputed_address")

    assert lookup_res.status == VaspClaimStatus.CONFLICTED
    assert len(lookup_res.claims) == 2
    assert lookup_res.primary_claim.confidence == AttributionConfidence.DISPUTED


def test_tron_historical_balance_limitation(caplog):
    """
    Validates that requesting historical balance at specific block height
    returns structured UNAVAILABLE_PROVIDER and logs a warning without crashing.
    """
    adapter = TronAdapter()
    with caplog.at_level(logging.WARNING):
        res = adapter.get_historical_balance("T_SYNTHETIC_ADDR", Asset.TRX, at_block=50000000)
        assert res.status.value == "UNAVAILABLE_PROVIDER"
        warning_found = any("historical balance at block 50000000 not supported on TRONGrid free tier" in record.message for record in caplog.records)
        assert warning_found, "TronAdapter must log a warning when historical at_block balance is requested"


def test_load_registry_from_json_file():
    """
    Validates that load_registry_from_file correctly loads the default vasp_labels.json
    supporting the 'entries' top-level key.
    """
    import os
    from backend.vasp.registry import load_registry_from_file

    path = os.path.normpath(os.path.join(os.path.dirname(__file__), "../backend/vasp/data/vasp_labels.json"))
    registry = load_registry_from_file(path)
    stats = registry.stats()
    assert stats["total_entries"] >= 10
    assert stats["unique_addresses"] >= 10

    # Look up known Ethereum Binance address
    res_eth = registry.lookup(Chain.ETHEREUM, "0x28c6c06298d514db089934071355e5743bf21d60")
    assert res_eth.primary_claim is not None
    assert res_eth.primary_claim.entity_name == "Binance"

    # Look up known TRON Binance address
    res_tron = registry.lookup(Chain.TRON, "TQrY8tryqsYVCZS2XhC26R9FAMt2FkHx7a")
    assert res_tron.primary_claim is not None
    assert res_tron.primary_claim.entity_name == "Binance"


def test_registry_supports_records_and_entries_dicts():
    """
    Validates that VaspRegistry constructor accepts dicts with either 'entries' or 'records'.
    """
    sample_entry = {
        "chain": "ETHEREUM",
        "address": "0x1111111111111111111111111111111111111111",
        "entity_name": "TestExchange",
        "first_observed": "2024-01-01T00:00:00",
        "last_verified": "2026-01-01T00:00:00",
        "confidence": "HIGH",
    }

    # Dict with 'entries'
    reg_entries = VaspRegistry({"entries": [sample_entry]})
    assert reg_entries.stats()["total_entries"] == 1
    assert reg_entries.get(Chain.ETHEREUM, "0x1111111111111111111111111111111111111111").entity_name == "TestExchange"

    # Dict with 'records'
    reg_records = VaspRegistry({"records": [sample_entry]})
    assert reg_records.stats()["total_entries"] == 1
    assert reg_records.get(Chain.ETHEREUM, "0x1111111111111111111111111111111111111111").entity_name == "TestExchange"

