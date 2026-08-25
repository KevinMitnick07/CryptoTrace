"""
Automated unit tests for VASP Stability Classifier and Actionability State.
Testing consensus, model disagreement, degradation axes, and actionability mappings.
"""

from __future__ import annotations
from decimal import Decimal
import pytest

from backend.core.models import (
    AllocationModel, EndpointStability, ActionabilityState,
    AttributionConfidence, BridgeMatchStrength, ValueInterval, Asset
)
from backend.core.stability import StabilityClassifier, compute_actionability


@pytest.fixture
def classifier() -> StabilityClassifier:
    return StabilityClassifier()


def test_stability_all_models_agree_high(classifier):
    """All 4 models agree on OKX as dominant endpoint with narrow value spread."""
    attributions = {
        "OKX": {
          AllocationModel.CONSERVATIVE: Decimal("9000.00"),
          AllocationModel.PROPORTIONAL: Decimal("9500.00"),
          AllocationModel.FIFO: Decimal("10000.00"),
          AllocationModel.LIFO: Decimal("9000.00"),
        },
        "Kraken": {
          AllocationModel.CONSERVATIVE: Decimal("1000.00"),
          AllocationModel.PROPORTIONAL: Decimal("500.00"),
          AllocationModel.FIFO: Decimal("0.00"),
          AllocationModel.LIFO: Decimal("1000.00"),
        }
    }
    dominant, stability, reason = classifier.classify(
        vasp_model_attributions=attributions,
        victim_value=Decimal("10000.00"),
        bridge_match_strength=None,
        label_confidence=AttributionConfidence.HIGH,
        label_age_days=30,
    )
    assert dominant == "OKX"
    assert stability == EndpointStability.HIGH
    assert "dominant under all 4 allocation models" in reason


def test_stability_models_disagree_unstable(classifier):
    """FIFO points to Binance (first outgoing), LIFO points to Kraken (last outgoing)."""
    attributions = {
        "Binance": {
          AllocationModel.CONSERVATIVE: Decimal("4000.00"),
          AllocationModel.PROPORTIONAL: Decimal("4500.00"),
          AllocationModel.FIFO: Decimal("8000.00"),
          AllocationModel.LIFO: Decimal("1000.00"),
        },
        "Kraken": {
          AllocationModel.CONSERVATIVE: Decimal("4000.00"),
          AllocationModel.PROPORTIONAL: Decimal("4500.00"),
          AllocationModel.FIFO: Decimal("1000.00"),
          AllocationModel.LIFO: Decimal("8000.00"),
        }
    }
    dominant, stability, reason = classifier.classify(
        vasp_model_attributions=attributions,
        victim_value=Decimal("10000.00"),
        bridge_match_strength=None,
        label_confidence=AttributionConfidence.HIGH,
        label_age_days=30,
    )
    assert dominant == "UNSTABLE"
    assert stability == EndpointStability.LOW
    assert "Dominant endpoint changes across models" in reason


def test_stability_wide_spread_degradation(classifier):
    """All models agree on Binance, but model values range from 1k to 9k (80% spread)."""
    attributions = {
        "Binance": {
          AllocationModel.CONSERVATIVE: Decimal("1000.00"),
          AllocationModel.PROPORTIONAL: Decimal("5000.00"),
          AllocationModel.FIFO: Decimal("9000.00"),
          AllocationModel.LIFO: Decimal("9000.00"),
        }
    }
    dominant, stability, reason = classifier.classify(
        vasp_model_attributions=attributions,
        victim_value=Decimal("10000.00"),
        bridge_match_strength=None,
        label_confidence=AttributionConfidence.HIGH,
        label_age_days=30,
    )
    assert dominant == "Binance"
    assert stability == EndpointStability.LOW
    assert "wide interval" in reason


def test_stability_stale_label_degradation(classifier):
    """All models agree on Binance, but label is 300 days old (>180d)."""
    attributions = {
        "Binance": {
          AllocationModel.CONSERVATIVE: Decimal("9000.00"),
          AllocationModel.PROPORTIONAL: Decimal("9000.00"),
          AllocationModel.FIFO: Decimal("9000.00"),
          AllocationModel.LIFO: Decimal("9000.00"),
        }
    }
    dominant, stability, reason = classifier.classify(
        vasp_model_attributions=attributions,
        victim_value=Decimal("10000.00"),
        bridge_match_strength=None,
        label_confidence=AttributionConfidence.HIGH,
        label_age_days=300,
    )
    assert dominant == "Binance"
    assert stability == EndpointStability.LOW
    assert "STALE" in reason


def test_stability_weak_bridge_degradation(classifier):
    """Dominant VASP found after a WEAK bridge match."""
    attributions = {
        "Binance": {
          AllocationModel.CONSERVATIVE: Decimal("9000.00"),
          AllocationModel.PROPORTIONAL: Decimal("9000.00"),
          AllocationModel.FIFO: Decimal("9000.00"),
          AllocationModel.LIFO: Decimal("9000.00"),
        }
    }
    dominant, stability, reason = classifier.classify(
        vasp_model_attributions=attributions,
        victim_value=Decimal("10000.00"),
        bridge_match_strength=BridgeMatchStrength.WEAK,
        label_confidence=AttributionConfidence.HIGH,
        label_age_days=30,
    )
    assert dominant == "Binance"
    assert stability == EndpointStability.LOW
    assert "Cross-chain link is WEAK" in reason


def test_no_vasp_candidate(classifier):
    """Zero VASP candidates reached during traversal."""
    dominant, stability, reason = classifier.classify(
        vasp_model_attributions={},
        victim_value=Decimal("10000.00"),
        bridge_match_strength=None,
        label_confidence=AttributionConfidence.HIGH,
        label_age_days=30,
    )
    assert dominant == "NONE"
    assert stability == EndpointStability.UNRESOLVED


# ===========================================================================
# ACTIONABILITY STATE TESTS
# ===========================================================================

def test_actionability_recent_supported_custodial():
    state = compute_actionability(
        stability=EndpointStability.HIGH,
        dominant_vasp="Binance",
        label_confidence=AttributionConfidence.HIGH,
        label_age_days=30,
        min_value_interval=ValueInterval(Decimal("5000.00"), Decimal("9000.00"), Asset.USDT_ERC20),
        victim_value=Decimal("10000.00"),
        has_supported_path=True,
    )
    assert state == ActionabilityState.RECENT_SUPPORTED_CUSTODIAL_EXPOSURE


def test_actionability_stale_label():
    state = compute_actionability(
        stability=EndpointStability.HIGH,
        dominant_vasp="Binance",
        label_confidence=AttributionConfidence.STALE,
        label_age_days=250,
        min_value_interval=ValueInterval(Decimal("5000.00"), Decimal("9000.00"), Asset.USDT_ERC20),
        victim_value=Decimal("10000.00"),
        has_supported_path=True,
    )
    assert state == ActionabilityState.STALE_EXPOSURE


def test_actionability_unstable_endpoint():
    state = compute_actionability(
        stability=EndpointStability.LOW,
        dominant_vasp="UNSTABLE",
        label_confidence=AttributionConfidence.HIGH,
        label_age_days=30,
        min_value_interval=ValueInterval(Decimal("0.00"), Decimal("8000.00"), Asset.USDT_ERC20),
        victim_value=Decimal("10000.00"),
        has_supported_path=True,
    )
    assert state == ActionabilityState.NO_ACTIONABLE_ENDPOINT
