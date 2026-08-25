"""
Case state machine.

Cases progress through defined states as investigation evidence accumulates.
State transitions are recorded with timestamps and reasons.
The investigator is notified of material transitions via the delta view.
"""

from __future__ import annotations
import logging
import datetime
from typing import Optional

from .models import CaseState, TraceabilityState, ActionabilityState, CaseDelta, utc_now

log = logging.getLogger(__name__)


# Allowed forward transitions
_VALID_TRANSITIONS: dict[CaseState, set[CaseState]] = {
    CaseState.ACTIVE: {
        CaseState.FUNDS_STATIONARY,
        CaseState.NEW_MOVEMENT,
        CaseState.FAN_OUT,
        CaseState.VASP_CANDIDATE,
        CaseState.CLOSED,
    },
    CaseState.FUNDS_STATIONARY: {
        CaseState.NEW_MOVEMENT,
        CaseState.CLOSED,
    },
    CaseState.NEW_MOVEMENT: {
        CaseState.FAN_OUT,
        CaseState.ASSET_TRANSFORMATION,
        CaseState.CROSS_CHAIN_MOVEMENT,
        CaseState.VASP_CANDIDATE,
        CaseState.FUNDS_STATIONARY,
    },
    CaseState.FAN_OUT: {
        CaseState.VASP_CANDIDATE,
        CaseState.ASSET_TRANSFORMATION,
        CaseState.CROSS_CHAIN_MOVEMENT,
        CaseState.FUNDS_STATIONARY,
    },
    CaseState.ASSET_TRANSFORMATION: {
        CaseState.VASP_CANDIDATE,
        CaseState.CROSS_CHAIN_MOVEMENT,
        CaseState.FUNDS_STATIONARY,
    },
    CaseState.CROSS_CHAIN_MOVEMENT: {
        CaseState.VASP_CANDIDATE,
        CaseState.ASSET_TRANSFORMATION,
        CaseState.FUNDS_STATIONARY,
    },
    CaseState.VASP_CANDIDATE: {
        CaseState.SUPPORTED_VASP,
        CaseState.NEW_MOVEMENT,
        CaseState.CLOSED,
    },
    CaseState.SUPPORTED_VASP: {
        CaseState.CUSTODIAL_BOUNDARY,
        CaseState.NEW_MOVEMENT,
        CaseState.CLOSED,
    },
    CaseState.CUSTODIAL_BOUNDARY: {
        CaseState.CLOSED,
    },
    CaseState.CLOSED: set(),
}


class CaseStateMachine:

    def __init__(self, case_id: str, initial_state: CaseState = CaseState.ACTIVE):
        self.case_id = case_id
        self.current = initial_state
        self._history: list[tuple[CaseState, CaseState, str, datetime.datetime]] = []

    def transition(self, new_state: CaseState, reason: str) -> bool:
        """
        Attempt a state transition. Returns True if successful.
        Invalid transitions are rejected and logged — never silently applied.
        """
        allowed = _VALID_TRANSITIONS.get(self.current, set())
        if new_state not in allowed:
            log.warning(
                "Case %s: invalid transition %s → %s. Reason: %s",
                self.case_id, self.current.value, new_state.value, reason,
            )
            return False
        prev = self.current
        self.current = new_state
        self._history.append((prev, new_state, reason, utc_now()))
        log.info(
            "Case %s: %s → %s | %s",
            self.case_id, prev.value, new_state.value, reason,
        )
        return True

    def history(self) -> list[dict]:
        return [
            {
                "from": from_s.value,
                "to": to_s.value,
                "reason": reason,
                "timestamp": ts.isoformat(),
            }
            for from_s, to_s, reason, ts in self._history
        ]


def compute_delta(
    prev_snapshot: dict,
    current_snapshot: dict,
    review_timestamp: datetime.datetime,
) -> CaseDelta:
    """
    Compute what changed between two case snapshots.
    prev_snapshot and current_snapshot are serialized case state dicts.
    """
    new_transfers = (
        current_snapshot.get("total_transfers", 0) -
        prev_snapshot.get("total_transfers", 0)
    )
    new_bridge = (
        current_snapshot.get("bridge_events", 0) -
        prev_snapshot.get("bridge_events", 0)
    )
    new_dex = (
        current_snapshot.get("dex_events", 0) -
        prev_snapshot.get("dex_events", 0)
    )

    prev_value = prev_snapshot.get("traced_value_max", 0)
    curr_value = current_snapshot.get("traced_value_max", 0)
    from decimal import Decimal
    value_moved = Decimal(str(curr_value)) - Decimal(str(prev_value))

    # Detect primary VASP changes
    vasp_changes: list[str] = []
    prev_primary = prev_snapshot.get("primary_stable_vasp")
    curr_primary = current_snapshot.get("primary_stable_vasp")
    primary_changed = prev_primary != curr_primary
    if primary_changed:
        vasp_changes.append(
            f"Primary VASP changed: {prev_primary or 'NONE'} → {curr_primary or 'NONE'}"
        )

    prev_stale = prev_snapshot.get("stale_labels", 0)
    curr_stale = current_snapshot.get("stale_labels", 0)

    prev_related = prev_snapshot.get("related_cases", 0)
    curr_related = current_snapshot.get("related_cases", 0)

    transitions = current_snapshot.get("state_transitions", [])
    prev_transitions = prev_snapshot.get("state_transitions", [])
    new_transitions = transitions[len(prev_transitions):]
    transition_strs = [f"{t['from']} → {t['to']}" for t in new_transitions]

    return CaseDelta(
        review_timestamp=review_timestamp,
        new_transfers=max(0, new_transfers),
        new_bridge_events=max(0, new_bridge),
        new_dex_events=max(0, new_dex),
        victim_value_moved=value_moved,
        vasp_candidate_changes=vasp_changes,
        primary_vasp_changed=primary_changed,
        related_cases_added=max(0, curr_related - prev_related),
        stale_labels_detected=max(0, curr_stale - prev_stale),
        state_transitions=transition_strs,
    )
