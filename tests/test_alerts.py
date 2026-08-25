"""
Tests for Internal Investigation Alert System and Investigator Action Packet.
"""

from decimal import Decimal
import tempfile
import os
import pytest
from fastapi.testclient import TestClient

from backend.core.models import (
    Chain, Asset, AlertEvent, AlertEventType, AlertSeverity,
    OnChainTransfer, TxState, utc_now
)
from backend.storage.store import InvestigationStore
from backend.services.monitor import CaseMonitorService
from tests.conftest import FakeChainAdapter
from main import app


def test_alert_event_storage_and_lifecycle():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        store = InvestigationStore(db_path)

        # Save a case first
        store.save_case(
            case_id="CASE-ALERT-01",
            complaint_ref="REF-ALERT-01",
            state="ACTIVE",
            traceability="SUPPORTED",
            actionability="NO_ACTIONABLE_ENDPOINT",
            anchor_status="VERIFIED",
            anchor_level="A",
            anchor_chain="ETHEREUM",
            anchor_asset="USDT_ERC20",
            anchor_tx_hash="0x_anchor",
            victim_value="5000.00",
            reported_wallet="0x_suspect_alert",
        )

        # 1. Create and save alert
        alert = AlertEvent(
            alert_id="ALT-TEST-001",
            case_id="CASE-ALERT-01",
            event_type=AlertEventType.NEW_MOVEMENT,
            severity=AlertSeverity.WARNING,
            summary="New on-chain transfer detected (5,000 USDT).",
            evidence_reference="0x_tx_alert_movement_123",
            created_at=utc_now(),
        )
        store.save_alert(alert)

        # 2. Retrieve alerts
        all_alerts = store.get_alerts()
        assert len(all_alerts) == 1
        assert all_alerts[0]["alert_id"] == "ALT-TEST-001"
        assert all_alerts[0]["event_type"] == "NEW_MOVEMENT"
        assert all_alerts[0]["severity"] == "WARNING"
        assert all_alerts[0]["acknowledged"] == 0

        # 3. Filter by case_id
        case_alerts = store.get_alerts(case_id="CASE-ALERT-01")
        assert len(case_alerts) == 1
        empty_alerts = store.get_alerts(case_id="CASE-NONEXISTENT")
        assert len(empty_alerts) == 0

        # 4. Acknowledge alert
        acked = store.acknowledge_alert("ALT-TEST-001")
        assert acked is True

        # 5. Check unack filter
        unack = store.get_alerts(unack_only=True)
        assert len(unack) == 0

        ack_list = store.get_alerts(unack_only=False)
        assert len(ack_list) == 1
        assert ack_list[0]["acknowledged"] == 1

    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_monitor_emits_new_movement_alert():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        store = InvestigationStore(db_path)
        fake_adapter = FakeChainAdapter(Chain.ETHEREUM)
        fake_adapter.current_block_num = 100
        adapters = {Chain.ETHEREUM: fake_adapter}

        store.save_case(
            case_id="CASE-MON-ALERT-01",
            complaint_ref="REF-M-ALERT",
            state="ACTIVE",
            traceability="SUPPORTED",
            actionability="NO_ACTIONABLE_ENDPOINT",
            anchor_status="VERIFIED",
            anchor_level="A",
            anchor_chain="ETHEREUM",
            anchor_asset="USDT_ERC20",
            anchor_tx_hash="0x_anchor",
            victim_value="2500.00",
            reported_wallet="0x_suspect_mon",
        )

        monitor = CaseMonitorService(store=store, adapter_registry=adapters, poll_interval_seconds=30)
        monitor.register_case("CASE-MON-ALERT-01", Chain.ETHEREUM, "0x_suspect_mon", start_block=100)

        # First pass - baseline
        monitor.poll_once()
        assert len(store.get_alerts()) == 0

        # Add new outgoing transfer on fake adapter
        now = utc_now()
        fake_adapter.current_block_num = 105
        fake_adapter.outgoing_transfers["0x_suspect_mon".lower()] = [
            OnChainTransfer(
                tx_hash="0x_tx_new_move_999",
                from_address="0x_suspect_mon",
                to_address="0x_vasp_deposit_999",
                chain=Chain.ETHEREUM,
                asset=Asset.USDT_ERC20,
                amount=Decimal("2500.00"),
                block_number=102,
                block_timestamp=now,
                tx_state=TxState.CONFIRMED,
            )
        ]

        # Second poll pass
        summary2 = monitor.poll_once()
        assert summary2["movements_detected"] == 1

        # Verify alert emission
        alerts = store.get_alerts(case_id="CASE-MON-ALERT-01")
        assert len(alerts) == 1
        assert alerts[0]["event_type"] == "NEW_MOVEMENT"
        assert alerts[0]["severity"] == "WARNING"
        assert "0x_tx_new_move_999" in alerts[0]["evidence_reference"]

    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_api_alert_endpoints():
    with TestClient(app) as client:
        # 1. GET /api/alerts
        res = client.get("/api/alerts")
        assert res.status_code == 200
        data = res.json()
        assert "alerts" in data
        assert "count" in data

        # 2. GET /api/cases/{case_id}/alerts
        res2 = client.get("/api/cases/CASE-TEST-SCENARIO-01/alerts")
        assert res2.status_code in [200, 404]

        # 3. POST /api/alerts/{id}/acknowledge on non-existent alert
        res3 = client.post("/api/alerts/NON-EXISTENT-ALERT-ID/acknowledge")
        assert res3.status_code == 404
