"""
Automated unit tests for Case State Machine and Snapshot Delta Analysis.
"""

from __future__ import annotations
import datetime
from decimal import Decimal
import pytest

from backend.core.models import CaseState
from backend.core.case import CaseStateMachine, compute_delta


def test_case_state_valid_transitions():
    sm = CaseStateMachine("CASE-TEST-01", CaseState.ACTIVE)
    assert sm.current == CaseState.ACTIVE
    
    # ACTIVE -> FAN_OUT (Valid)
    assert sm.transition(CaseState.FAN_OUT, "Split into 5 branches") is True
    assert sm.current == CaseState.FAN_OUT
    
    # FAN_OUT -> VASP_CANDIDATE (Valid)
    assert sm.transition(CaseState.VASP_CANDIDATE, "Reached Binance deposit") is True
    assert sm.current == CaseState.VASP_CANDIDATE
    
    # VASP_CANDIDATE -> SUPPORTED_VASP (Valid)
    assert sm.transition(CaseState.SUPPORTED_VASP, "Attribution corroborated") is True
    assert sm.current == CaseState.SUPPORTED_VASP
    
    # SUPPORTED_VASP -> CLOSED (Valid)
    assert sm.transition(CaseState.CLOSED, "Investigation report delivered") is True
    assert sm.current == CaseState.CLOSED


def test_case_state_invalid_transition_rejected():
    sm = CaseStateMachine("CASE-TEST-02", CaseState.ACTIVE)
    
    # ACTIVE -> CUSTODIAL_BOUNDARY (Invalid direct transition)
    assert sm.transition(CaseState.CUSTODIAL_BOUNDARY, "Illegal direct jump") is False
    assert sm.current == CaseState.ACTIVE, "State must remain unchanged upon rejected transition"
    
    # CLOSED state has 0 outgoing transitions
    sm.current = CaseState.CLOSED
    assert sm.transition(CaseState.ACTIVE, "Cannot reopen closed case directly") is False


def test_case_delta_calculation():
    prev_snapshot = {
        "total_transfers": 10,
        "bridge_events": 1,
        "dex_events": 0,
        "traced_value_max": 5000.00,
        "primary_stable_vasp": "Binance",
        "stale_labels": 0,
        "related_cases": 2,
        "state_transitions": [{"from": "ACTIVE", "to": "FAN_OUT"}]
    }
    
    current_snapshot = {
        "total_transfers": 15,
        "bridge_events": 2,
        "dex_events": 1,
        "traced_value_max": 8000.00,
        "primary_stable_vasp": "OKX",
        "stale_labels": 1,
        "related_cases": 3,
        "state_transitions": [
            {"from": "ACTIVE", "to": "FAN_OUT"},
            {"from": "FAN_OUT", "to": "VASP_CANDIDATE"}
        ]
    }
    
    now = datetime.datetime.now(datetime.timezone.utc)
    delta = compute_delta(prev_snapshot, current_snapshot, now)
    
    assert delta.new_transfers == 5
    assert delta.new_bridge_events == 1
    assert delta.new_dex_events == 1
    assert delta.victim_value_moved == Decimal("3000.00")
    assert delta.primary_vasp_changed is True
    assert "Binance → OKX" in delta.vasp_candidate_changes[0]
    assert delta.related_cases_added == 1
    assert delta.stale_labels_detected == 1
    assert len(delta.state_transitions) == 1
    assert delta.state_transitions[0] == "FAN_OUT → VASP_CANDIDATE"
