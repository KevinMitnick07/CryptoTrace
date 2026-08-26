"""
Persistent Case Monitoring Service.

Periodically queries blockchain adapters for new on-chain movements
on watched case addresses. Checkpoints state to SQLite to survive restarts.
Emits deduplicated, evidence-linked alerts upon real state transitions:
  - NEW_MOVEMENT: New on-chain transfers detected from watched addresses.
  - NEW_VASP_ENDPOINT: Newly reached custodial exchange or deposit cluster.
  - PRIMARY_VASP_CHANGED: Primary stable VASP finding altered by downstream flow.
  - TRACE_BECAME_INCOMPLETE: Computational budget limit reached or fragmented.
  - MIXER_BOUNDARY_REACHED: Funds entered an obfuscated mixing pool.
  - PROVIDER_DEGRADED: Chain RPC error or rate-limit outage.
  - PROVIDER_RECOVERED: RPC connection restored successfully.
"""

from __future__ import annotations
import asyncio
import logging
import datetime
from decimal import Decimal
from typing import Optional, Callable

from ..core.models import (
    Chain, Asset, CaseState, OnChainTransfer, CaseDelta, utc_now,
    AlertEventType, AlertSeverity
)
from ..core.case import CaseStateMachine, compute_delta
from ..storage.store import InvestigationStore
from ..chains.base import ChainAdapter
from ..vasp.registry import VaspRegistry

log = logging.getLogger(__name__)


class CaseMonitorService:

    def __init__(
        self,
        store: InvestigationStore,
        adapter_registry: dict[Chain, ChainAdapter],
        poll_interval_seconds: int = 60,
        vasp_lookup_fn: Optional[Callable[[Chain, str], Optional[str]]] = None,
        mixer_lookup_fn: Optional[Callable[[Chain, str], bool]] = None,
    ):
        self._store = store
        self._adapters = adapter_registry
        self._interval = poll_interval_seconds
        self._lookup_vasp = vasp_lookup_fn
        self._lookup_mixer = mixer_lookup_fn
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_poll: Optional[datetime.datetime] = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        log.info("Starting Persistent Case Monitor (interval=%ds)", self._interval)

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        log.info("Stopped Persistent Case Monitor")

    def register_case(self, case_id: str, chain: Chain, address: str, start_block: int = 0) -> None:
        """Register a case address for continuous monitoring."""
        self._store.register_watcher(case_id, chain.value, address, start_block)
        log.info("Registered case %s for active monitoring on %s:%s", case_id, chain.value, address)

    def poll_once(self) -> dict:
        """
        Execute one synchronous polling pass across all active watchers.
        Returns summary of checks and detected movements.
        """
        self._last_poll = utc_now()
        watchers = self._store.get_active_watchers()
        checked = 0
        movements_detected = 0

        for w in watchers:
            case_id = w["case_id"]
            chain_str = w["chain"]
            address = w["address"]
            last_block = w["last_processed_block"]

            try:
                chain = Chain(chain_str)
                adapter = self._adapters.get(chain)
                if not adapter:
                    continue

                checked += 1
                current_block = adapter.get_current_block()
                if current_block <= last_block:
                    continue

                # Query new outgoing transfers since last checkpoint
                new_transfers = adapter.get_transfers_from(
                    address=address,
                    asset=None,
                    after_block=last_block + 1 if last_block > 0 else None,
                    before_block=current_block,
                    limit=50,
                )

                if new_transfers:
                    movements_detected += 1
                    log.info("Monitor detected %d new transfers for case %s at block %d", len(new_transfers), case_id, current_block)

                    prev_snap = self._store.get_latest_snapshot(case_id) or {}
                    prev_count = prev_snap.get("total_transfers", 0)
                    prev_primary_vasp = prev_snap.get("primary_stable_vasp", "None identified")
                    new_count = prev_count + len(new_transfers)

                    if new_count > prev_count:
                        new_snap = dict(prev_snap)
                        new_snap["total_transfers"] = new_count
                        new_snap["last_monitored_block"] = current_block

                        # Check if any new transfer reaches a known VASP or mixer
                        detected_vasp = None
                        detected_mixer = False

                        for t in new_transfers:
                            to_addr = t.to_address.lower()
                            if self._lookup_vasp:
                                match = self._lookup_vasp(chain, to_addr)
                                if match:
                                    detected_vasp = match
                            if self._lookup_mixer and self._lookup_mixer(chain, to_addr):
                                detected_mixer = True

                        if detected_vasp:
                            new_snap["first_supported_vasp"] = detected_vasp
                            new_snap["primary_stable_vasp"] = detected_vasp

                        self._store.save_snapshot(case_id, new_snap)

                        # Emit NEW_MOVEMENT alert
                        alert_id = f"ALT-MOV-{case_id}-{current_block}"
                        sample_tx = new_transfers[0].tx_hash if new_transfers else str(current_block)
                        self._store.save_alert(
                            alert_id=alert_id,
                            case_id=case_id,
                            event_type=AlertEventType.NEW_MOVEMENT.value,
                            severity=AlertSeverity.WARNING.value,
                            summary=f"Detected {len(new_transfers)} new outgoing transfer(s) from monitored wallet {address[:10]}... at block {current_block}.",
                            evidence_reference=sample_tx,
                        )

                        # Emit NEW_VASP_ENDPOINT alert if VASP endpoint reached
                        if detected_vasp:
                            vasp_alert_id = f"ALT-VASP-{case_id}-{current_block}"
                            self._store.save_alert(
                                alert_id=vasp_alert_id,
                                case_id=case_id,
                                event_type=AlertEventType.NEW_VASP_ENDPOINT.value,
                                severity=AlertSeverity.INFO.value,
                                summary=f"Monitored funds transferred directly to verified {detected_vasp} deposit infrastructure at block {current_block}.",
                                evidence_reference=sample_tx,
                            )

                            if prev_primary_vasp != "None identified" and prev_primary_vasp != detected_vasp:
                                chg_alert_id = f"ALT-CHG-{case_id}-{current_block}"
                                self._store.save_alert(
                                    alert_id=chg_alert_id,
                                    case_id=case_id,
                                    event_type=AlertEventType.PRIMARY_VASP_CHANGED.value,
                                    severity=AlertSeverity.WARNING.value,
                                    summary=f"Primary stable VASP attribution transitioned from {prev_primary_vasp} to {detected_vasp}.",
                                    evidence_reference=sample_tx,
                                )

                        # Emit MIXER_BOUNDARY_REACHED alert if mixer boundary encountered
                        if detected_mixer:
                            mix_alert_id = f"ALT-MIX-{case_id}-{current_block}"
                            self._store.save_alert(
                                alert_id=mix_alert_id,
                                case_id=case_id,
                                event_type=AlertEventType.MIXER_BOUNDARY_REACHED.value,
                                severity=AlertSeverity.WARNING.value,
                                summary=f"Monitored funds entered a privacy mixer contract at block {current_block}. Deterministic downstream tracing halted.",
                                evidence_reference=sample_tx,
                            )

                        # Emit TRACE_BECAME_INCOMPLETE alert if branching / incomplete state observed
                        if prev_snap.get("trace_complete", True) is True and (len(new_transfers) >= 10 or prev_snap.get("is_complete") is False):
                            inc_alert_id = f"ALT-INC-{case_id}-{current_block}"
                            self._store.save_alert(
                                alert_id=inc_alert_id,
                                case_id=case_id,
                                event_type=AlertEventType.TRACE_BECAME_INCOMPLETE.value,
                                severity=AlertSeverity.WARNING.value,
                                summary=f"Trace completeness reduced due to high outbound branching ({len(new_transfers)} transfers) at block {current_block}.",
                                evidence_reference=sample_tx,
                            )

                # Check if recovering from previous provider error
                if w.get("failure_count", 0) > 0 or w.get("last_error_message"):
                    alert_id = f"ALT-REC-{case_id}-{current_block}"
                    self._store.save_alert(
                        alert_id=alert_id,
                        case_id=case_id,
                        event_type=AlertEventType.PROVIDER_RECOVERED.value,
                        severity=AlertSeverity.INFO.value,
                        summary=f"Chain provider {chain_str} connection restored successfully at block {current_block}.",
                        evidence_reference=str(current_block),
                    )

                # Checkpoint progress
                self._store.update_watcher_checkpoint(case_id, current_block, status="ACTIVE")

            except Exception as exc:
                log.warning("Monitoring pass failed for case %s: %s", case_id, exc)
                # Emit PROVIDER_DEGRADED alert on first failure
                if w.get("failure_count", 0) == 0:
                    alert_id = f"ALT-DEG-{case_id}-{int(self._last_poll.timestamp())}"
                    self._store.save_alert(
                        alert_id=alert_id,
                        case_id=case_id,
                        event_type=AlertEventType.PROVIDER_DEGRADED.value,
                        severity=AlertSeverity.WARNING.value,
                        summary=f"Chain provider {chain_str} query failed: {str(exc)[:200]}",
                        evidence_reference=str(last_block),
                    )
                self._store.update_watcher_checkpoint(case_id, last_block, status="ACTIVE", error=str(exc))

        ts_str = self._last_poll.isoformat() if self._last_poll else None
        return {
            "timestamp": ts_str,
            "poll_timestamp": ts_str,
            "active_watchers_count": len(watchers),
            "watchers_checked": checked,
            "movements_detected": movements_detected,
        }

    def get_status(self) -> dict:
        watchers = self._store.get_active_watchers()
        watcher_details = []
        for w in watchers:
            w_dict = dict(w)
            w_dict["last_error"] = w.get("last_error_message")
            watcher_details.append(w_dict)

        return {
            "running": self._running,
            "active_watchers_count": len(watchers),
            "poll_interval_seconds": self._interval,
            "last_poll_timestamp": self._last_poll.isoformat() if self._last_poll else None,
            "watchers": watcher_details,
        }
