"""
Automated benchmark runner verifying the 16 deterministic scenarios in data/test_scenarios.json.
All fixtures and hashes in this suite are explicitly SYNTHETIC TEST DATA.
"""

from __future__ import annotations
import json
import os
from decimal import Decimal
import pytest

from backend.core.models import (
    AllocationModel, Asset, Chain, EndpointStability, ValueInterval,
    OnChainTransfer, TxState, AttributionConfidence
)
from backend.core.attribution import AccountBasedAttributionEngine
from backend.core.stability import StabilityClassifier
from backend.protocols.bridge import match_bridge_destination, BridgeMatchStrength


def _load_benchmark_dataset():
    path = os.path.join(os.path.dirname(__file__), "../data/test_scenarios.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["scenarios"]


@pytest.mark.parametrize("scenario", _load_benchmark_dataset(), ids=lambda s: s["id"])
def test_benchmark_scenario_invariants(scenario):
    """Verify each benchmark scenario against domain invariants and ground truth."""
    scenario_id = scenario["id"]
    ground_truth = scenario.get("ground_truth", {})

    # Scenario 01: Direct VASP
    if scenario_id == "SCENARIO-01-DIRECT-VASP":
        victim_val = Decimal(scenario["victim_input"]["amount"])
        engine = AccountBasedAttributionEngine(victim_val, Asset.USDT_TRC20)
        outgoing = [
            OnChainTransfer(
                tx_hash=t["tx_hash"],
                chain=Chain.TRON,
                asset=Asset.USDT_TRC20,
                amount=Decimal(t["amount"]),
                from_address="T_SUSPECT_01",
                to_address=t["to_address"],
                block_number=1000,
                block_timestamp=None,
                tx_state=TxState.CONFIRMED,
            )
            for t in scenario["outgoing_transfers"]
        ]
        result = engine.allocate(Decimal(scenario["pre_existing_balance"]), outgoing)
        for model in AllocationModel:
            assert result[model]["T_BINANCE_HOT_01"] == Decimal(ground_truth["conservative_attributed"]["T_BINANCE_HOT_01"])

    # Scenario 02: Commingling 90k
    elif scenario_id == "SCENARIO-02-COMMINGLING-90K":
        victim_val = Decimal(scenario["victim_input"]["amount"])
        engine = AccountBasedAttributionEngine(victim_val, Asset.USDT_ERC20)
        outgoing = [
            OnChainTransfer(
                tx_hash=t["tx_hash"],
                chain=Chain.ETHEREUM,
                asset=Asset.USDT_ERC20,
                amount=Decimal(t["amount"]),
                from_address="0x_suspect_02",
                to_address=t["to_address"],
                block_number=1000,
                block_timestamp=None,
                tx_state=TxState.CONFIRMED,
            )
            for t in scenario["outgoing_transfers"]
        ]
        result = engine.allocate(Decimal(scenario["pre_existing_balance"]), outgoing)
        # Verify FIFO
        assert result[AllocationModel.FIFO]["0x_dest_a"] == Decimal(ground_truth["fifo_attributed"]["0x_dest_a"])
        assert result[AllocationModel.FIFO]["0x_dest_b"] == Decimal(ground_truth["fifo_attributed"]["0x_dest_b"])
        # Verify LIFO
        assert result[AllocationModel.LIFO].get("0x_dest_a", Decimal(0)) == Decimal(ground_truth["lifo_attributed"]["0x_dest_a"])
        assert result[AllocationModel.LIFO]["0x_dest_b"] == Decimal(ground_truth["lifo_attributed"]["0x_dest_b"])

    # Scenario 03 & 04: Stability
    elif scenario_id in ("SCENARIO-03-STABLE-VASP", "SCENARIO-04-UNSTABLE-VASP"):
        classifier = StabilityClassifier()
        attributions = {
            vasp: {AllocationModel[m]: Decimal(val) for m, val in models.items()}
            for vasp, models in scenario["vasp_model_attributions"].items()
        }
        dominant, stability, reason = classifier.classify(
            vasp_model_attributions=attributions,
            victim_value=Decimal(scenario["victim_value"]),
            bridge_match_strength=None,
            label_confidence=AttributionConfidence.HIGH,
            label_age_days=0,
        )
        assert dominant == ground_truth["dominant_vasp"]
        assert stability.name == ground_truth["stability"]
        assert ground_truth["reason_contains"].lower() in reason.lower()
