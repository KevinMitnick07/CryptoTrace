"""
Tests for persistent SQLite-backed Case Monitor Service.
"""

from decimal import Decimal
import tempfile
import os
import pytest

from backend.core.models import Chain, Asset, OnChainTransfer, TxState, utc_now
from backend.storage.store import InvestigationStore
from backend.services.monitor import CaseMonitorService
from tests.conftest import FakeChainAdapter


def test_monitor_registration_and_polling():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        store = InvestigationStore(db_path)
        fake_adapter = FakeChainAdapter(Chain.ETHEREUM)
        fake_adapter.current_block_num = 100
        adapters = {Chain.ETHEREUM: fake_adapter}

        # Create a mock case
        store.save_case(
            case_id="CASE-MONITOR-01",
            complaint_ref="REF-M1",
            state="ACTIVE",
            traceability="SUPPORTED",
            actionability="NO_ACTIONABLE_ENDPOINT",
            anchor_status="VERIFIED",
            anchor_level="A",
            anchor_chain="ETHEREUM",
            anchor_asset="USDT_ERC20",
            anchor_tx_hash="0x_anchor",
            victim_value="1000.00",
            reported_wallet="0x_suspect_m",
        )

        monitor = CaseMonitorService(store=store, adapter_registry=adapters, poll_interval_seconds=30)
        monitor.register_case("CASE-MONITOR-01", Chain.ETHEREUM, "0x_suspect_m", start_block=100)

        # Initial poll pass (no new blocks, no new transfers)
        summary1 = monitor.poll_once()
        assert summary1["active_watchers_count"] == 1
        assert summary1["watchers_checked"] == 1
        assert summary1["movements_detected"] == 0

        # Now advance chain block height and simulate a new outgoing transfer
        fake_adapter.current_block_num = 200
        now = utc_now()
        fake_adapter.outgoing_transfers["0x_suspect_m"] = [
            OnChainTransfer(
                tx_hash="0x_new_move_tx",
                chain=Chain.ETHEREUM,
                asset=Asset.USDT_ERC20,
                amount=Decimal("500.00"),
                from_address="0x_suspect_m",
                to_address="0x_fresh_dest",
                block_number=150,
                block_timestamp=now,
                tx_state=TxState.CONFIRMED,
            )
        ]

        # Second poll pass
        summary2 = monitor.poll_once()
        assert summary2["movements_detected"] == 1

        # Verify watcher was checkpointed to latest block (200)
        watchers = store.get_active_watchers()
        assert len(watchers) == 1
        assert watchers[0]["last_processed_block"] == 200

    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_monitor_error_persisted_to_last_error_message():
    """
    When a poll pass fails (adapter raises), the error string must be persisted
    to last_error_message in case_watchers and surfaced in get_status().
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        store = InvestigationStore(db_path)

        class BrokenAdapter:
            def get_current_block(self):
                raise RuntimeError("Provider offline — SYNTHETIC_TEST_ERROR")
            def get_transfers_from(self, *a, **kw):
                return []

        adapters = {Chain.ETHEREUM: BrokenAdapter()}

        store.save_case(
            case_id="CASE-ERR-01", complaint_ref="REF-ERR", state="ACTIVE",
            traceability="SUPPORTED", actionability="NO_ACTIONABLE_ENDPOINT",
            anchor_status="VERIFIED", anchor_level="A", anchor_chain="ETHEREUM",
            anchor_asset="USDT_ERC20", anchor_tx_hash="0x_a", victim_value="100.00",
            reported_wallet="0x_err_wallet",
        )

        monitor = CaseMonitorService(store=store, adapter_registry=adapters)
        monitor.register_case("CASE-ERR-01", Chain.ETHEREUM, "0x_err_wallet", start_block=0)

        # Poll — adapter will fail
        monitor.poll_once()

        # Status must include last_error for the watcher
        status = monitor.get_status()
        assert status["active_watchers_count"] == 1
        watcher_info = status["watchers"][0]
        assert watcher_info["last_error"] is not None, (
            "last_error must be set in get_status() after a failing poll. "
            "Investigators must be able to see that polling failed."
        )
        assert "SYNTHETIC_TEST_ERROR" in watcher_info["last_error"]

    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_monitor_successful_checkpoint_clears_error():
    """
    After a successful poll following a failed one, last_error_message must be
    cleared to None (failure is resolved, not stale).
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        store = InvestigationStore(db_path)

        # First: simulate a failure by direct DB call
        store.save_case(
            case_id="CASE-CLR-01", complaint_ref="REF-CLR", state="ACTIVE",
            traceability="SUPPORTED", actionability="NO_ACTIONABLE_ENDPOINT",
            anchor_status="VERIFIED", anchor_level="A", anchor_chain="ETHEREUM",
            anchor_asset="USDT_ERC20", anchor_tx_hash="0x_c", victim_value="100.00",
            reported_wallet="0x_clr_wallet",
        )
        store.register_watcher("CASE-CLR-01", "ETHEREUM", "0x_clr_wallet", start_block=0)
        store.update_watcher_checkpoint("CASE-CLR-01", 0, status="ACTIVE", error="Previous error")

        # Confirm error is recorded
        watchers = store.get_active_watchers()
        assert watchers[0]["last_error_message"] == "Previous error"

        # Now simulate a successful checkpoint
        store.update_watcher_checkpoint("CASE-CLR-01", 100, status="ACTIVE", error=None)

        # Error must be cleared
        watchers2 = store.get_active_watchers()
        assert watchers2[0]["last_error_message"] is None, (
            "last_error_message must be cleared to NULL on successful checkpoint. "
            "Stale error messages mislead investigators."
        )

    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_monitor_duplicate_snapshot_suppression():
    """
    When a poll runs but no new transfers arrive (count unchanged),
    no new snapshot row must be written to case_snapshots.
    Duplicate snapshots inflate audit logs without adding information.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        store = InvestigationStore(db_path)
        fake_adapter = FakeChainAdapter(Chain.ETHEREUM)
        fake_adapter.current_block_num = 200
        adapters = {Chain.ETHEREUM: fake_adapter}

        store.save_case(
            case_id="CASE-DEDUP-01", complaint_ref="REF-DD", state="ACTIVE",
            traceability="SUPPORTED", actionability="NO_ACTIONABLE_ENDPOINT",
            anchor_status="VERIFIED", anchor_level="A", anchor_chain="ETHEREUM",
            anchor_asset="USDT_ERC20", anchor_tx_hash="0x_d", victim_value="500.00",
            reported_wallet="0x_dedup_wallet",
        )

        # Pre-seed one existing transfer (transfer already known)
        now = utc_now()
        fake_adapter.outgoing_transfers["0x_dedup_wallet"] = [
            OnChainTransfer(
                tx_hash="0x_already_seen",
                chain=Chain.ETHEREUM,
                asset=Asset.USDT_ERC20,
                amount=Decimal("100.00"),
                from_address="0x_dedup_wallet",
                to_address="0x_dd_dest",
                block_number=150,
                block_timestamp=now,
                tx_state=TxState.CONFIRMED,
            )
        ]

        monitor = CaseMonitorService(store=store, adapter_registry=adapters)
        monitor.register_case("CASE-DEDUP-01", Chain.ETHEREUM, "0x_dedup_wallet", start_block=100)

        # First poll — discovers 1 new transfer → saves snapshot
        monitor.poll_once()
        snap1 = store.get_latest_snapshot("CASE-DEDUP-01")
        assert snap1 is not None
        count_after_first = snap1["total_transfers"]
        assert count_after_first == 1

        # Advance block height so next poll runs, but return same transfers (no new ones)
        # Simulate same transfers returned again at same block (re-scan scenario)
        # Actually: since we now checkpoint to block 200, next poll will find current_block <= last_processed_block
        # Set to simulate new blocks but zero new transfers
        fake_adapter.current_block_num = 300
        fake_adapter.outgoing_transfers["0x_dedup_wallet"] = []  # No new transfers

        monitor.poll_once()

        snap2 = store.get_latest_snapshot("CASE-DEDUP-01")
        # Snapshot content must be unchanged (total_transfers still 1)
        assert snap2 is not None
        assert snap2["total_transfers"] == 1, (
            "Snapshot must not change when no new transfers are detected. "
            "Duplicate snapshot entries corrupt the audit trail."
        )

    finally:
        if os.path.exists(db_path):
            os.remove(db_path)
