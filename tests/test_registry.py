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
