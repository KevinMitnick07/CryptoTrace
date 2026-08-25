"""
Integration tests for FastAPI application endpoints.
"""

import json
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient

from backend.api.routes import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_api_root_and_docs(client):
    res_root = client.get("/")
    assert res_root.status_code == 200

    res_docs = client.get("/docs")
    assert res_docs.status_code == 200

    res_openapi = client.get("/openapi.json")
    assert res_openapi.status_code == 200


def test_api_scenarios_listing_and_run(client):
    res_list = client.get("/api/scenarios")
    assert res_list.status_code == 200
    data = res_list.json()
    assert "scenarios" in data
    assert len(data["scenarios"]) == 16

    # Run scenario 1
    res_run = client.post("/api/scenarios/SCENARIO-01-DIRECT-VASP/run")
    assert res_run.status_code == 200
    run_data = res_run.json()
    assert run_data["scenario_id"] == "SCENARIO-01-DIRECT-VASP"
    assert "case_id" in run_data
    assert run_data["validation_status"] == "PASS"
    assert run_data["classification"] == "SYNTHETIC TEST DATA"


def test_api_intake_and_case_lifecycle(client):
    complaint_payload = {
        "complaint_ref": "TEST-INTAKE-001",
        "reported_wallet": "0x_test_intake_wallet_001",
        "reported_chain": "ETHEREUM",
        "reported_asset": "USDT_ERC20",
        "reported_amount": "5000.00",
        "reported_tx_hash": "0x_test_anchor_tx",
    }

    res_intake = client.post("/api/intake", json=complaint_payload)
    assert res_intake.status_code == 200
    data = res_intake.json()
    case_id = data["case_id"]
    assert "anchor" in data

    # Fetch case detail
    res_case = client.get(f"/api/cases/{case_id}")
    assert res_case.status_code == 200
    case_detail = res_case.json()
    assert case_detail["case"]["complaint_ref"] == "TEST-INTAKE-001"

    # Fetch graph
    res_graph = client.get(f"/api/cases/{case_id}/graph")
    assert res_graph.status_code == 200
    graph_data = res_graph.json()
    assert "nodes" in graph_data
    assert "edges" in graph_data

    # Fetch audit
    res_audit = client.get(f"/api/cases/{case_id}/audit")
    assert res_audit.status_code == 200
    audit_data = res_audit.json()
    assert "audit_records" in audit_data

    # Fetch delta
    res_delta = client.get(f"/api/cases/{case_id}/delta")
    assert res_delta.status_code == 200
    delta_data = res_delta.json()
    assert "new_transfers" in delta_data

    # Fetch attributions
    res_attr = client.get(f"/api/cases/{case_id}/attributions")
    assert res_attr.status_code == 200
    attr_data = res_attr.json()
    assert "attributions" in attr_data

    # Export JSON Evidence Package
    res_json_pkg = client.get(f"/api/cases/{case_id}/evidence-package/json")
    assert res_json_pkg.status_code == 200
    pkg_data = res_json_pkg.json()
    assert "package_integrity_sha256" in pkg_data["metadata"]

    # Export Markdown Evidence Package
    res_md = client.get(f"/api/cases/{case_id}/evidence-package/markdown")
    assert res_md.status_code == 200
    assert "FORENSIC BLOCKCHAIN EVIDENCE PACKAGE" in res_md.text

    # Pattern Analysis
    res_ai = client.post(f"/api/cases/{case_id}/ai/analysis")
    assert res_ai.status_code == 200
    ai_data = res_ai.json()
    assert "features" in ai_data
    assert "patterns" in ai_data
    assert "investigator_narrative" in ai_data


def test_api_monitor_endpoints(client):
    res_status = client.get("/api/monitor/status")
    assert res_status.status_code == 200
    data = res_status.json()
    assert "running" in data

    res_poll = client.post("/api/monitor/poll")
    assert res_poll.status_code == 200
    poll_data = res_poll.json()
    assert "poll_timestamp" in poll_data


def test_api_registry_stats_and_chains_health(client):
    res_reg = client.get("/api/registry/stats")
    assert res_reg.status_code == 200
    stats = res_reg.json()
    assert "total_entries" in stats

    res_health = client.get("/api/chains/health")
    assert res_health.status_code == 200
    health = res_health.json()
    assert "tron" in health
    assert "ethereum" in health
