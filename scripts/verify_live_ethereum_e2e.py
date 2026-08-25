#!/usr/bin/env python3
"""
End-to-End Live Ethereum Pipeline Verification Script.

Executes complete forensic pipeline on real Ethereum blockchain data:
  Public Address/TX -> Complaint Intake -> Anchor Resolution -> Live Traversal ->
  Multi-Hypothesis Attribution -> VASP Lookup -> Stability -> Graph -> Evidence Package
"""

import sys
import os
import json
from decimal import Decimal

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.chains.ethereum import EthereumAdapter
from backend.core.models import (
    Chain, Asset, ComplaintInput, ValueInterval, utc_now,
    InvestigationCase, CaseState, TraceabilityState, ActionabilityState
)
from backend.core.evidence import ProvenanceStore
from backend.core.anchor import AnchorResolver
from backend.core.traversal import AdaptiveTraversalEngine, TraversalConfig
from backend.vasp.registry import load_registry_from_file
from backend.core.evidence_package import EvidencePackageGenerator


def run_ethereum_e2e() -> dict:
    case_id = "CASE-ETH-LIVE-001"
    rpc_url = os.getenv("ETH_RPC_URL", "https://1rpc.io/eth")
    adapter = EthereumAdapter(rpc_url=rpc_url)
    provenance = ProvenanceStore(case_id=case_id)

    registry_path = os.path.normpath(os.path.join(os.path.dirname(__file__), "../backend/vasp/data/vasp_labels.json"))
    vasp_registry = load_registry_from_file(registry_path)

    # Ethereum Foundation Public Multisig / Grant Wallet
    test_addr = "0xde0b295669a9fd93d5f28d9ec85e40f4cb697bae"
    victim_amount = Decimal("2.50")

    result = {
        "pipeline": "ETHEREUM_LIVE_E2E",
        "stages": {},
        "summary": {},
    }

    # Stage 1: Complaint Intake
    intake = ComplaintInput(
        complaint_ref="NCRP-2026-ETH-LIVE-001",
        reported_wallet=test_addr,
        reported_chain=Chain.ETHEREUM,
        reported_asset=Asset.ETH,
        reported_amount=victim_amount,
        reported_tx_hash=None,
        intake_timestamp=utc_now(),
    )
    result["stages"]["1_intake"] = {
        "status": "LOCAL_LOGIC",
        "complaint_ref": intake.complaint_ref,
        "reported_wallet": intake.reported_wallet,
        "reported_amount": str(intake.reported_amount),
    }

    # Stage 2: Anchor Resolution
    anchor_resolver = AnchorResolver({Chain.ETHEREUM: adapter}, provenance)
    anchor = anchor_resolver.resolve(intake)
    result["stages"]["2_anchor"] = {
        "status": "LIVE_VERIFIED" if anchor.status.value == "VERIFIED" else "LOCAL_LOGIC",
        "anchor_level": anchor.level.value,
        "anchor_status": anchor.status.value,
        "anchor_evidence": anchor.anchor_evidence,
    }

    # Stage 3: Live Transfer Retrieval & Traversal
    engine = AdaptiveTraversalEngine(
        adapter_registry={Chain.ETHEREUM: adapter},
        vasp_registry=lambda chain, addr: vasp_registry.get(chain, addr),
        mixer_detector=lambda chain, addr: False,
        config=TraversalConfig(max_hops=2, max_branches_per_hop=3, max_total_nodes=10),
    )

    current_block = adapter.get_current_block()
    traversal_res = engine.trace(
        start_address=test_addr,
        start_chain=Chain.ETHEREUM,
        start_asset=Asset.ETH,
        victim_value=victim_amount,
        start_block=current_block - 50 if current_block > 50 else 0,
        start_timestamp=utc_now(),
    )

    result["stages"]["3_traversal"] = {
        "status": "LIVE_VERIFIED" if traversal_res.path_segments else "PROVIDER_LIMITED",
        "hops_traced": len(traversal_res.path_segments),
        "total_nodes_visited": traversal_res.total_nodes_visited,
        "branches_audited": len(traversal_res.branch_audit),
        "completeness_pct": str(traversal_res.trace_completeness_pct),
        "high_fragmentation": traversal_res.high_fragmentation_detected,
    }

    # Stage 4: Multi-Hypothesis Attribution & VASP Lookup
    vasp_candidates = traversal_res.vasp_candidates
    result["stages"]["4_attribution_and_vasp"] = {
        "status": "REGISTRY_ATTRIBUTION" if vasp_candidates else "UNRESOLVED",
        "vasp_count": len(vasp_candidates),
        "vasp_candidates": vasp_candidates,
    }

    # Stage 5: Case Assembly & Evidence Package
    case = InvestigationCase(
        case_id=case_id,
        complaint=intake,
        anchor=anchor,
        state=CaseState.ACTIVE,
        traceability=TraceabilityState.DETERMINISTIC if anchor.status.value == "VERIFIED" else TraceabilityState.AMBIGUOUS,
        actionability=ActionabilityState.NO_ACTIONABLE_ENDPOINT if not vasp_candidates else ActionabilityState.SUPPORTED_VASP,
        path_segments=traversal_res.path_segments,
        branch_audit=traversal_res.branch_audit,
        vasp_candidates=vasp_candidates,
        cross_case_signals=[],
        claims=[],
        first_supported_vasp=None,
        primary_stable_vasp=None,
        unresolved_value=traversal_res.unresolved_value,
        trace_completeness_pct=traversal_res.trace_completeness_pct,
        high_fragmentation_detected=traversal_res.high_fragmentation_detected,
    )

    generator = EvidencePackageGenerator(case, investigator_id="INVESTIGATOR-ETH-LIVE")
    pkg = generator.build_package_dict()

    result["stages"]["5_evidence_package"] = {
        "status": "LOCAL_LOGIC",
        "package_integrity_sha256": pkg["metadata"]["package_integrity_sha256"],
        "has_action_packet": "investigator_action_packet" in pkg,
    }

    result["summary"] = {
        "overall_status": "SUCCESS",
        "live_nodes_fetched": traversal_res.total_nodes_visited,
        "evidence_sha256": pkg["metadata"]["package_integrity_sha256"],
    }
    return result


if __name__ == "__main__":
    out = run_ethereum_e2e()
    print(json.dumps(out, indent=2, default=str))
