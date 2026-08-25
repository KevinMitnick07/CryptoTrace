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
