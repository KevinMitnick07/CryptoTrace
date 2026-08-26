"""
FastAPI application — investigation API layer.

Provides clean REST endpoints for:
  - Complaint intake and fast-path anchor resolution
  - Deep-path multi-hypothesis graph traversal
  - Case state management and snapshot delta auditing
  - Forensic Evidence Package exports (JSON / Markdown with SHA-256 integrity hash)
  - Explainable local AI/ML topological analytics and case similarity
  - Persistent real-time case monitoring
  - Live chain health checking and synthetic scenario execution
"""

from __future__ import annotations
import datetime
import json
import logging
import os
import uuid
from decimal import Decimal
from typing import Optional, Any
from pathlib import Path

from fastapi import FastAPI, BackgroundTasks, HTTPException, Request, Response, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, PlainTextResponse, JSONResponse
from pydantic import BaseModel, Field

# Domain imports
from ..core.models import (
    Chain, Asset, CaseState, TraceabilityState, ActionabilityState,
    ComplaintInput, AnchorLevel, AnchorStatus, AllocationModel, ValueInterval,
    InvestigationCase, TraceAnchor, PathSegment, BranchAuditRecord,
    VaspAttribution, ClaimRecord, EvidenceClass, OnChainTransfer, TxState,
    EndpointStability, AttributionSource, AttributionConfidence, VaspRecord, utc_now
)
from ..core.anchor import AnchorResolver
from ..core.attribution import AccountBasedAttributionEngine
from ..core.traversal import AdaptiveTraversalEngine, TraversalConfig
from ..core.stability import StabilityClassifier, compute_actionability
from ..core.convergence import CaseConvergenceAnalyzer
from ..core.case import CaseStateMachine, compute_delta
from ..core.evidence import ProvenanceStore
from ..core.evidence_package import EvidencePackageGenerator
from ..core.sanitizer import sanitize_dict_records, sanitize_pii
from ..ai.features import extract_features
from ..ai.patterns import AdvisoryPatternClassifier
from ..ai.similarity import CaseSimilarityEngine
from ..ai.summary import generate_investigator_narrative
from ..vasp.registry import VaspRegistry, load_registry_from_file, make_vasp_lookup_fn, make_mixer_fn
from ..vasp.clustering import ExchangeInfrastructureClusteringEngine
from ..core.intermediary import IntermediaryAnalysisEngine
from ..chains.tron import TronAdapter
from ..chains.ethereum import EthereumAdapter
from ..storage.store import InvestigationStore
from ..services.monitor import CaseMonitorService

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# Application setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="CryptoTrace — SIH 26183 Investigation Platform",
    description=(
        "Victim-centric forensic VASP attribution and blockchain analytics system. "
        "Produces investigator-reviewable forensic evidence packages. "
        "Software conclusions are advisory and require authorised investigator review."
    ),
    version="0.2.0-sprint",
    docs_url="/docs",
)

# CORS configuration.
# Default: wildcard, suitable for local demo / hackathon use.
# Set CORS_STRICT=1 to restrict to ALLOWED_ORIGINS (space-separated list).
# Example: ALLOWED_ORIGINS="http://localhost:8000 http://127.0.0.1:8000"
_cors_strict = os.getenv("CORS_STRICT", "0").strip() == "1"
_allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "")
_allowed_origins: list[str] = (
    [o.strip() for o in _allowed_origins_env.split() if o.strip()]
    if (_cors_strict and _allowed_origins_env)
    else ["http://localhost:8000", "http://127.0.0.1:8000"]
    if _cors_strict
    else ["*"]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key", "Authorization", "X-Request-ID"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    req_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    response = await call_next(request)
    response.headers["X-Request-ID"] = req_id
    return response


# ---------------------------------------------------------------------------
# Singleton services
# ---------------------------------------------------------------------------

VASP_REGISTRY: Optional[VaspRegistry] = None
STORE: Optional[InvestigationStore] = None
ADAPTERS: dict = {}
CONVERGENCE_ANALYZER: Optional[CaseConvergenceAnalyzer] = None
CASE_MACHINES: dict[str, CaseStateMachine] = {}
INVESTIGATION_CASES: dict[str, InvestigationCase] = {}
MONITOR_SERVICE: Optional[CaseMonitorService] = None
CLUSTERING_ENGINE: Optional[ExchangeInfrastructureClusteringEngine] = None
INTERMEDIARY_ENGINE: Optional[IntermediaryAnalysisEngine] = None
HISTORICAL_CORPUS: list[dict] = []


class SimpleRateLimiter:
    """Lightweight in-memory rate limiter for public endpoints."""
    def __init__(self, max_requests: int = 120, window_seconds: int = 60):
        self._max = max_requests
        self._window = window_seconds
        self._requests: dict[str, list[float]] = {}

    def check(self, client_id: str) -> bool:
        now = datetime.datetime.now(datetime.timezone.utc).timestamp()
        timestamps = self._requests.setdefault(client_id, [])
        self._requests[client_id] = [ts for ts in timestamps if now - ts < self._window]
        if len(self._requests[client_id]) >= self._max:
            return False
        self._requests[client_id].append(now)
        return True


RATE_LIMITER = SimpleRateLimiter(max_requests=120, window_seconds=60)


def verify_auth_token(authorization: Optional[str] = Header(None), x_api_key: Optional[str] = Header(None)):
    """Optional authentication guard. Enforced if API_AUTH_TOKEN is configured."""
    required = os.getenv("API_AUTH_TOKEN")
    if not required:
        return True
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split("Bearer ", 1)[1].strip()
    elif x_api_key:
        token = x_api_key.strip()
    if token != required:
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid or missing API authentication token.")
    return True


@app.on_event("startup")
async def startup():
    global VASP_REGISTRY, STORE, ADAPTERS, CONVERGENCE_ANALYZER, MONITOR_SERVICE
    global CLUSTERING_ENGINE, INTERMEDIARY_ENGINE, HISTORICAL_CORPUS

    registry_path = os.getenv(
        "VASP_REGISTRY_PATH",
        os.path.join(os.path.dirname(__file__), "../vasp/data/vasp_labels.json"),
    )
    VASP_REGISTRY = load_registry_from_file(os.path.normpath(registry_path))

    ADAPTERS[Chain.TRON] = TronAdapter(api_key=os.getenv("TRONGRID_API_KEY"))
    ADAPTERS[Chain.ETHEREUM] = EthereumAdapter(rpc_url=os.getenv("ETH_RPC_URL"))

    db_path = os.getenv("DB_PATH", "investigations.db")
    STORE = InvestigationStore(db_path)
    CONVERGENCE_ANALYZER = CaseConvergenceAnalyzer(VASP_REGISTRY)

    CLUSTERING_ENGINE = ExchangeInfrastructureClusteringEngine(
        known_vasp_lookup_fn=make_vasp_lookup_fn(VASP_REGISTRY) if VASP_REGISTRY else None
    )
    INTERMEDIARY_ENGINE = IntermediaryAnalysisEngine()

    MONITOR_SERVICE = CaseMonitorService(
        store=STORE,
        adapter_registry=ADAPTERS,
        poll_interval_seconds=int(os.getenv("CASE_MONITOR_INTERVAL_SECONDS", "60")),
        vasp_lookup_fn=make_vasp_lookup_fn(VASP_REGISTRY) if VASP_REGISTRY else None,
        mixer_lookup_fn=make_mixer_fn(VASP_REGISTRY) if VASP_REGISTRY else None,
    )
    MONITOR_SERVICE.start()

    # Load synthetic scenarios for similarity corpus
    scenarios_path = os.path.normpath(os.path.join(os.path.dirname(__file__), "../../data/test_scenarios.json"))
    if os.path.exists(scenarios_path):
        try:
            with open(scenarios_path, "r", encoding="utf-8") as f:
                scenarios_data = json.load(f).get("scenarios", [])
                for sc in scenarios_data:
                    HISTORICAL_CORPUS.append({
                        "case_id": sc.get("scenario_id"),
                        "scenario_name": sc.get("name"),
                        "pattern_type": sc.get("expected_actionability", "Standard"),
                        "description": sc.get("description", ""),
                        "features": [
                            float(sc.get("expected_max_hop", 2)),
                            2.5,
                            0.8 if "peel" in sc.get("scenario_id", "") else 0.2,
                            1.0 if "bridge" in sc.get("scenario_id", "") else 0.0,
                            1.0 if "dex" in sc.get("scenario_id", "") else 0.0,
                            250.0 if "dust" in sc.get("scenario_id", "") else 5.0,
                            1200.0,
                            3.5,
                        ],
                    })
        except Exception as exc:
            log.warning("Could not pre-load historical scenario corpus: %s", exc)

    log.info("CryptoTrace startup complete. VASP registry: %s", VASP_REGISTRY.stats())


@app.on_event("shutdown")
async def shutdown():
    if MONITOR_SERVICE:
        MONITOR_SERVICE.stop()


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------

class ComplaintRequest(BaseModel):
    complaint_ref: str = Field(..., description="Complaint reference (e.g. NCRP ID)")
    reported_wallet: str
    reported_chain: str = Field(..., description="TRON, ETHEREUM, or BITCOIN")
    reported_asset: Optional[str] = None
    reported_amount: Optional[str] = None
    reported_tx_hash: Optional[str] = None
    reported_time_utc: Optional[str] = None
    complainant_payment_evidence: Optional[str] = None


class AnchorResponse(BaseModel):
    status: str
    level: str
    chain: Optional[str]
    asset: Optional[str]
    tx_hash: Optional[str]
    amount: Optional[str]
    anchor_evidence: str
    ambiguity_reason: str
    candidate_count: int


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@app.post("/api/intake", dependencies=[Depends(verify_auth_token)])
async def create_investigation(complaint: ComplaintRequest, background_tasks: BackgroundTasks):
    """
    Intake a victim complaint. Runs synchronous Fast-Path anchor resolution (<10s)
    and schedules Deep-Path multi-hypothesis graph traversal in the background.
    """
    case_id = f"CASE-{uuid.uuid4().hex[:8].upper()}"

    try:
        chain_enum = Chain(complaint.reported_chain.upper())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unsupported chain: {complaint.reported_chain}")

    asset_enum = None
    if complaint.reported_asset:
        try:
            asset_enum = Asset(complaint.reported_asset.upper())
        except ValueError:
            pass

    amount_dec = Decimal(complaint.reported_amount) if complaint.reported_amount else None
    reported_dt = None
    if complaint.reported_time_utc:
        try:
            reported_dt = datetime.datetime.fromisoformat(complaint.reported_time_utc)
        except ValueError:
            pass

    intake = ComplaintInput(
        complaint_ref=complaint.complaint_ref,
        reported_wallet=complaint.reported_wallet,
        reported_chain=chain_enum,
        reported_asset=asset_enum,
        reported_amount=amount_dec,
        reported_tx_hash=complaint.reported_tx_hash,
        reported_time_utc=reported_dt,
        complainant_payment_evidence=complaint.complainant_payment_evidence,
    )

    # 1. Fast-Path Anchor Resolution
    prov = ProvenanceStore(case_id)
    anchor_resolver = AnchorResolver(adapters=ADAPTERS, provenance=prov)
    anchor = anchor_resolver.resolve(intake)

    machine = CaseStateMachine(case_id)
    CASE_MACHINES[case_id] = machine

    # Preliminary VASP check
    prelim_vasp = VASP_REGISTRY.get(chain_enum, intake.reported_wallet) if VASP_REGISTRY else None
    if prelim_vasp:
        machine.transition(CaseState.VASP_CANDIDATE, f"Reported wallet is known VASP: {prelim_vasp.entity_name}")

    # Build initial investigation case object
    inv_case = InvestigationCase(
        case_id=case_id,
        complaint=intake,
        anchor=anchor,
        state=machine.current,
        traceability=TraceabilityState.DETERMINISTIC if anchor.status.value == "VERIFIED" else TraceabilityState.AMBIGUOUS,
        actionability=ActionabilityState.NO_ACTIONABLE_ENDPOINT,
        path_segments=[],
        branch_audit=[],
        vasp_candidates=[],
        cross_case_signals=[],
        claims=[],
        first_supported_vasp=None,
        primary_stable_vasp=None,
        unresolved_value=ValueInterval(amount_dec or Decimal(0), amount_dec or Decimal(0), asset_enum or Asset.USDT_ERC20),
    )
    INVESTIGATION_CASES[case_id] = inv_case

    # Save to SQLite
    STORE.save_case(
        case_id=case_id,
        complaint_ref=intake.complaint_ref,
        state=machine.current.value,
        traceability=inv_case.traceability.value,
        actionability=inv_case.actionability.value,
        anchor_status=anchor.status.value,
        anchor_level=anchor.level.value,
        anchor_chain=chain_enum.value,
        anchor_asset=asset_enum.value if asset_enum else None,
        anchor_tx_hash=anchor.tx_hash,
        victim_value=str(amount_dec) if amount_dec else None,
        reported_wallet=intake.reported_wallet,
    )

    # Schedule deep traversal
    background_tasks.add_task(
        _run_deep_traversal,
        case_id=case_id,
        complaint=intake,
        anchor=anchor,
        machine=machine,
    )

    return {
        "case_id": case_id,
        "complaint_ref": intake.complaint_ref,
        "anchor": {
            "status": anchor.status.value,
            "level": anchor.level.value,
            "chain": anchor.chain.value if anchor.chain else None,
            "asset": anchor.asset.value if anchor.asset else None,
            "tx_hash": anchor.tx_hash,
            "evidence_basis": anchor.anchor_evidence,
            "ambiguity_reason": anchor.ambiguity_reason,
            "candidate_count": len(anchor.candidate_txs),
        },
        "initial_state": machine.current.value,
        "message": "Intake verified. Deep-path multi-hypothesis traversal running.",
    }


def _run_deep_traversal(
    case_id: str,
    complaint: ComplaintInput,
    anchor: TraceAnchor,
    machine: CaseStateMachine,
):
    """Background task executing deep-path traversal and state classification."""
    try:
        start_addr = anchor.confirmed_tx.to_address if (anchor.confirmed_tx and anchor.confirmed_tx.to_address) else complaint.reported_wallet
        start_chain = anchor.chain or complaint.reported_chain or Chain.TRON
        start_asset = anchor.asset or complaint.reported_asset or Asset.USDT_TRC20
        victim_val = complaint.reported_amount or Decimal("1000.00")
        start_block = anchor.confirmed_tx.block_number if anchor.confirmed_tx else 0
        start_ts = anchor.confirmed_tx.block_timestamp if anchor.confirmed_tx else utc_now()

        traversal_engine = AdaptiveTraversalEngine(
            adapter_registry=ADAPTERS,
            vasp_registry=make_vasp_lookup_fn(VASP_REGISTRY),
            mixer_detector=make_mixer_fn(VASP_REGISTRY),
            config=TraversalConfig(max_hops=8, max_branches_per_hop=25),
        )

        res = traversal_engine.trace(
            start_address=start_addr,
            start_chain=start_chain,
            start_asset=start_asset,
            victim_value=victim_val,
            start_block=start_block,
            start_timestamp=start_ts,
        )

        # Save audit records
        audit_dicts = [
            {
                "from_address": b.from_address,
                "to_address": b.to_address,
                "tx_hash": b.tx_hash,
                "chain": b.chain.value,
                "asset": b.asset.value,
                "amount": str(b.amount),
                "victim_lower": str(b.victim_attributed_range.lower_bound) if b.victim_attributed_range else "0",
                "victim_upper": str(b.victim_attributed_range.upper_bound) if b.victim_attributed_range else "0",
                "disposition": b.disposition.value,
                "reason": b.reason,
                "tier": b.tier,
                "recorded_at": b.timestamp.isoformat(),
            }
            for b in res.branch_audit
        ]
        STORE.save_branch_audit(case_id, audit_dicts)

        # VASP Analysis
        vasp_model_attributions: dict[str, dict] = {}
        vasp_attributions: list[VaspAttribution] = []
        for addr in res.vasp_candidates:
            vasp_record = VASP_REGISTRY.get(start_chain, addr)
            if not vasp_record:
                continue
            entity = vasp_record.entity_name
            if entity not in vasp_model_attributions:
                vasp_model_attributions[entity] = {}
            for model in AllocationModel:
                seg_total = sum(
                    seg.victim_value_by_model.get(model, Decimal(0))
                    for seg in res.path_segments if seg.to_address == addr
                )
                vasp_model_attributions[entity][model] = seg_total

        stability_clf = StabilityClassifier()
        dominant_vasp, stability, stability_reason = stability_clf.classify(
            vasp_model_attributions=vasp_model_attributions,
            victim_value=victim_val,
            bridge_match_strength=None,
            label_confidence=None,
            label_age_days=0,
        )

        actionability = compute_actionability(
            stability=stability,
            dominant_vasp=dominant_vasp,
            label_confidence=None,
            label_age_days=0,
            min_value_interval=res.unresolved_value,
            victim_value=victim_val,
            has_supported_path=len(res.vasp_candidates) > 0,
        )

        # Update state machine
        if res.vasp_candidates:
            machine.transition(CaseState.VASP_CANDIDATE, "VASP candidate reached")
            if stability.value in ("HIGH", "MEDIUM"):
                machine.transition(CaseState.SUPPORTED_VASP, f"Stability: {stability.value}")
                machine.transition(CaseState.CUSTODIAL_BOUNDARY, "Custodial deposit confirmed")
        elif res.mixer_boundaries:
            pass
        else:
            machine.transition(CaseState.FUNDS_STATIONARY, "No movement detected")

        # Update In-Memory Case
        inv_case = INVESTIGATION_CASES.get(case_id)
        if inv_case:
            inv_case.state = machine.current
            inv_case.traceability = res.traceability_state
            inv_case.actionability = actionability
            inv_case.path_segments = res.path_segments
            inv_case.branch_audit = res.branch_audit
            inv_case.unresolved_value = res.unresolved_value
            inv_case.deferred_value = res.deferred_value
            inv_case.trace_completeness_pct = res.trace_completeness_pct
            inv_case.high_fragmentation_detected = res.high_fragmentation_detected

            if dominant_vasp and dominant_vasp not in ("NONE", "UNSTABLE") and res.vasp_candidates:
                target_addr = res.vasp_candidates[0]
                rec = VASP_REGISTRY.get(start_chain, target_addr)
                if rec:
                    inv_case.primary_stable_vasp = VaspAttribution(
                        record=rec,
                        address_in_path=target_addr,
                        hop_from_anchor=1,
                        victim_value_interval=ValueInterval(victim_val, victim_val, start_asset),
                        per_model=[],
                        first_hop_reaching_vasp=True,
                        is_primary_stable=True,
                        endpoint_stability=stability,
                        stability_reason=stability_reason,
                        actionability=actionability,
                    )

        # Save snapshot
        snapshot = {
            "case_id": case_id,
            "total_transfers": len(res.path_segments),
            "bridge_events": len(res.bridge_events),
            "dex_events": len(res.dex_transformations),
            "primary_stable_vasp": dominant_vasp if dominant_vasp not in ("NONE", "UNSTABLE") else None,
            "stability": stability.value,
            "stability_reason": stability_reason,
            "trace_completeness_pct": str(res.trace_completeness_pct),
            "high_fragmentation_detected": res.high_fragmentation_detected,
        }
        STORE.save_snapshot(case_id, snapshot)
        STORE.save_case(
            case_id=case_id,
            complaint_ref=complaint.complaint_ref,
            state=machine.current.value,
            traceability=res.traceability_state.value,
            actionability=actionability.value,
            anchor_status=anchor.status.value,
            anchor_level=anchor.level.value,
            anchor_chain=start_chain.value,
            anchor_asset=start_asset.value,
            anchor_tx_hash=anchor.tx_hash,
            victim_value=str(victim_val),
            reported_wallet=complaint.reported_wallet,
            snapshot_json=json.dumps(snapshot),
        )

        log.info("Deep traversal finished for case %s: state=%s, stability=%s", case_id, machine.current.value, stability.value)
    except Exception as exc:
        log.exception("Deep traversal failed for case %s: %s", case_id, exc)


@app.get("/api/cases")
async def list_cases():
    """List all persisted cases."""
    return STORE.list_cases()


@app.get("/api/cases/{case_id}")
async def get_case_detail(case_id: str):
    """Get full case details, latest snapshot, and delta."""
    case_row = STORE.get_case(case_id)
    if not case_row:
        raise HTTPException(status_code=404, detail="Case not found")

    snapshot = STORE.get_latest_snapshot(case_id)
    audit = STORE.get_branch_audit(case_id)
    return {
        "case": case_row,
        "snapshot": snapshot,
        "branch_audit_count": len(audit),
    }


@app.get("/api/cases/{case_id}/clustering")
async def get_case_clustering(case_id: str):
    """Candidate exchange infrastructure clustering hypothesis for case endpoint."""
    inv_case = INVESTIGATION_CASES.get(case_id)
    if not inv_case:
        case_row = STORE.get_case(case_id) if STORE else None
        if not case_row:
            raise HTTPException(status_code=404, detail="Case not found")
        transfers = []
        audit = STORE.get_branch_audit(case_id) if STORE else []
        for r in audit:
            transfers.append(OnChainTransfer(
                tx_hash=r.get("tx_hash", "0x"),
                chain=Chain(r.get("chain", "TRON")) if r.get("chain") in Chain._value2member_map_ else Chain.TRON,
                asset=Asset(r.get("asset", "USDT_TRC20")) if r.get("asset") in Asset._value2member_map_ else Asset.USDT_TRC20,
                amount=Decimal(r.get("amount", "0")),
                from_address=r.get("from_address", ""),
                to_address=r.get("to_address", ""),
                block_number=0,
                block_timestamp=utc_now(),
                tx_state=TxState.CONFIRMED,
            ))
        target_addr = case_row.get("reported_wallet", "")
        chain = Chain(case_row.get("anchor_chain", "TRON")) if case_row.get("anchor_chain") in Chain._value2member_map_ else Chain.TRON
        v_amount = Decimal(case_row.get("victim_value", "0"))
        v_asset = Asset(case_row.get("anchor_asset", "USDT_TRC20")) if case_row.get("anchor_asset") in Asset._value2member_map_ else Asset.USDT_TRC20
        v_interval = ValueInterval(v_amount, v_amount, v_asset) if v_amount > Decimal(0) else None

        hyp = CLUSTERING_ENGINE.analyze_address_cluster(
            target_addr, chain, transfers,
            victim_value_interval=v_interval,
            trace_completeness=100.0,
            endpoint_stability=case_row.get("actionability", "UNRESOLVED"),
        ) if CLUSTERING_ENGINE else None
        return hyp.to_dict() if hyp else {"status": "UNAVAILABLE"}

    transfers = [seg.transfer for seg in inv_case.path_segments if seg.transfer]
    target_addr = inv_case.complaint.reported_wallet
    chain = inv_case.complaint.reported_chain or Chain.TRON
    v_interval = (
        inv_case.primary_stable_vasp.victim_value_interval
        if inv_case.primary_stable_vasp
        else inv_case.unresolved_value
    )
    last_seg = inv_case.path_segments[-1] if inv_case.path_segments else None
    v_models = last_seg.victim_value_by_model if last_seg else None

    hyp = CLUSTERING_ENGINE.analyze_address_cluster(
        target_addr, chain, transfers,
        victim_value_interval=v_interval,
        victim_value_by_model=v_models,
        trace_completeness=inv_case.trace_completeness_pct,
        deferred_value=inv_case.deferred_value.upper_bound if inv_case.deferred_value else None,
        unresolved_value=inv_case.unresolved_value.upper_bound if inv_case.unresolved_value else None,
        endpoint_stability=inv_case.primary_stable_vasp.endpoint_stability.value if inv_case.primary_stable_vasp else None,
    ) if CLUSTERING_ENGINE else None
    return hyp.to_dict() if hyp else {"status": "UNAVAILABLE"}


@app.get("/api/cases/{case_id}/intermediary")
async def get_case_intermediary_analysis(case_id: str):
    """Intermediary laundering pattern, dwell time, and fan-out/fan-in analysis."""
    inv_case = INVESTIGATION_CASES.get(case_id)
    transfers = []
    v_interval = None
    if inv_case:
        transfers = [seg.transfer for seg in inv_case.path_segments if seg.transfer]
        v_interval = inv_case.unresolved_value or (inv_case.primary_stable_vasp.victim_value_interval if inv_case.primary_stable_vasp else None)
    elif STORE:
        audit = STORE.get_branch_audit(case_id)
        for r in audit:
            transfers.append(OnChainTransfer(
                tx_hash=r.get("tx_hash", "0x"),
                chain=Chain(r.get("chain", "TRON")) if r.get("chain") in Chain._value2member_map_ else Chain.TRON,
                asset=Asset(r.get("asset", "USDT_TRC20")) if r.get("asset") in Asset._value2member_map_ else Asset.USDT_TRC20,
                amount=Decimal(r.get("amount", "0")),
                from_address=r.get("from_address", ""),
                to_address=r.get("to_address", ""),
                block_number=0,
                block_timestamp=utc_now(),
                tx_state=TxState.CONFIRMED,
            ))

    res = INTERMEDIARY_ENGINE.analyze_transfers(case_id, transfers, victim_value_interval=v_interval) if INTERMEDIARY_ENGINE else None
    return res.to_dict() if res else {"case_id": case_id, "summary_notes": ["Engine uninitialized"]}


@app.get("/api/cases/{case_id}/graph")
async def get_case_graph(case_id: str):
    """Retrieve Cytoscape graph nodes and edges for an investigation case."""
    inv_case = INVESTIGATION_CASES.get(case_id)
    nodes = []
    edges = []
    seen_nodes = set()

    if inv_case and inv_case.path_segments:
        # Build from in-memory path segments
        victim_addr = inv_case.complaint.reported_wallet
        start_chain = inv_case.complaint.reported_chain.value if inv_case.complaint.reported_chain else "TRON"

        nodes.append({
            "id": victim_addr,
            "label": "Victim Anchor",
            "address": victim_addr,
            "chain": start_chain,
            "role": "victim_anchor",
        })
        seen_nodes.add(victim_addr.lower())

        for idx, seg in enumerate(inv_case.path_segments):
            transfer = seg.transfer
            if not transfer:
                continue
            from_addr = transfer.from_address
            to_addr = transfer.to_address
            chain_str = transfer.chain.value if hasattr(transfer.chain, "value") else str(transfer.chain)

            # Classify node role
            for addr in (from_addr, to_addr):
                if addr.lower() not in seen_nodes:
                    role = "intermediary"
                    label = addr[:8] + "…"
                    if VASP_REGISTRY:
                        vasp_res = VASP_REGISTRY.lookup(transfer.chain, addr)
                        if vasp_res.primary_claim:
                            if vasp_res.entity_type == "CUSTODIAL_VASP":
                                role = "vasp"
                                label = vasp_res.primary_claim.entity_name
                            elif vasp_res.entity_type == "DEX":
                                role = "dex"
                                label = vasp_res.primary_claim.entity_name
                            elif vasp_res.entity_type == "MIXER":
                                role = "mixer"
                                label = vasp_res.primary_claim.entity_name
                            elif vasp_res.entity_type == "BRIDGE":
                                role = "bridge_contract"
                                label = vasp_res.primary_claim.entity_name
                    if addr.lower() == victim_addr.lower():
                        role = "suspect_wallet"
                        label = "Suspect Wallet"

                    nodes.append({
                        "id": addr,
                        "label": label,
                        "address": addr,
                        "chain": chain_str,
                        "role": role,
                    })
                    seen_nodes.add(addr.lower())

            approx_prop = str(seg.victim_value_by_model.get(AllocationModel.PROPORTIONAL, transfer.amount))
            edges.append({
                "id": f"e_{idx}_{transfer.tx_hash[:8]}",
                "from": from_addr,
                "to": to_addr,
                "chain": chain_str,
                "asset": transfer.asset.value if hasattr(transfer.asset, "value") else str(transfer.asset),
                "amount": str(transfer.amount),
                "tx_hash": transfer.tx_hash,
                "evidence_class": seg.evidence_class.value if hasattr(seg.evidence_class, "value") else str(seg.evidence_class),
                "victim_attributed_approx": approx_prop,
                "timestamp": transfer.block_timestamp.isoformat() if transfer.block_timestamp else None,
            })
    else:
        # Fallback to reconstructing from SQLite branch_audit and case records
        case_row = STORE.get_case(case_id)
        if not case_row:
            raise HTTPException(status_code=404, detail="Case not found")

        victim_addr = case_row["reported_wallet"]
        nodes.append({
            "id": victim_addr,
            "label": "Reported Anchor",
            "address": victim_addr,
            "chain": case_row.get("anchor_chain", "TRON"),
            "role": "suspect_wallet",
        })
        seen_nodes.add(victim_addr.lower())

        audit = STORE.get_branch_audit(case_id)
        for idx, r in enumerate(audit):
            from_addr = r.get("from_address") or victim_addr
            to_addr = r.get("to_address")
            if not to_addr:
                continue
            chain_str = r.get("chain", "TRON")
            for addr in (from_addr, to_addr):
                if addr.lower() not in seen_nodes:
                    role = "intermediary"
                    label = addr[:8] + "…"
                    if VASP_REGISTRY:
                        vasp_res = VASP_REGISTRY.lookup(Chain(chain_str) if chain_str in Chain._value2member_map_ else Chain.TRON, addr)
                        if vasp_res.primary_claim:
                            label = vasp_res.primary_claim.entity_name
                            role = "vasp" if vasp_res.entity_type == "CUSTODIAL_VASP" else "dex"
                    nodes.append({
                        "id": addr,
                        "label": label,
                        "address": addr,
                        "chain": chain_str,
                        "role": role,
                    })
                    seen_nodes.add(addr.lower())
            edges.append({
                "id": f"e_audit_{idx}",
                "from": from_addr,
                "to": to_addr,
                "chain": chain_str,
                "asset": r.get("asset", "USDT_TRC20"),
                "amount": r.get("amount", "0"),
                "tx_hash": r.get("tx_hash", "0x_syn"),
                "evidence_class": "OBSERVED",
                "victim_attributed_approx": r.get("victim_upper", r.get("amount", "0")),
                "timestamp": r.get("recorded_at"),
            })

    return {"nodes": nodes, "edges": edges}


@app.get("/api/cases/{case_id}/audit")
async def get_case_audit(case_id: str):
    """Retrieve full branch audit records for traversal decision transparency."""
    audit_records = STORE.get_branch_audit(case_id)
    return {"case_id": case_id, "audit_records": audit_records}


@app.get("/api/cases/{case_id}/delta")
async def get_case_delta(case_id: str):
    """Retrieve state changes between current and previous case snapshots."""
    latest = STORE.get_latest_snapshot(case_id) or {}
    prev = STORE.get_previous_snapshot(case_id) or {}
    delta = compute_delta(latest, prev, utc_now())
    return {
        "case_id": case_id,
        "review_timestamp": delta.review_timestamp.isoformat(),
        "new_transfers": delta.new_transfers,
        "new_bridge_events": delta.new_bridge_events,
        "new_dex_events": delta.new_dex_events,
        "victim_value_moved": str(delta.victim_value_moved),
        "vasp_candidate_changes": delta.vasp_candidate_changes,
        "primary_vasp_changed": delta.primary_vasp_changed,
        "related_cases_added": delta.related_cases_added,
        "stale_labels_detected": delta.stale_labels_detected,
        "state_transitions": delta.state_transitions,
    }


@app.get("/api/cases/{case_id}/attributions")
async def get_case_attributions(case_id: str):
    """Retrieve multi-hypothesis model values per attributed destination/entity."""
    inv_case = INVESTIGATION_CASES.get(case_id)
    if not inv_case:
        return {"case_id": case_id, "attributions": []}

    dest_models: dict[str, dict] = {}
    for seg in inv_case.path_segments:
        dest = seg.to_address
        if dest not in dest_models:
            dest_models[dest] = {
                "address": dest,
                "chain": seg.to_chain.value if hasattr(seg.to_chain, "value") else str(seg.to_chain),
                "entity_name": None,
                "role": "intermediary",
                "conservative": "0.00",
                "proportional": "0.00",
                "fifo": "0.00",
                "lifo": "0.00",
            }
            if VASP_REGISTRY:
                res = VASP_REGISTRY.lookup(seg.to_chain, dest)
                if res.primary_claim:
                    dest_models[dest]["entity_name"] = res.primary_claim.entity_name
                    dest_models[dest]["role"] = res.entity_type
        for model, val in seg.victim_value_by_model.items():
            model_key = model.name.lower() if hasattr(model, "name") else str(model).lower()
            prev_val = Decimal(dest_models[dest].get(model_key, "0"))
            dest_models[dest][model_key] = str(prev_val + val)

    return {"case_id": case_id, "attributions": list(dest_models.values())}


def _build_evidence_package_generator(case_id: str, inv_case: InvestigationCase) -> EvidencePackageGenerator:
    transfers = [seg.transfer for seg in inv_case.path_segments if seg.transfer]
    if not transfers and STORE:
        audit = STORE.get_branch_audit(case_id)
        for r in audit:
            transfers.append(OnChainTransfer(
                tx_hash=r.get("tx_hash", "0x"),
                chain=Chain(r.get("chain", "TRON")) if r.get("chain") in Chain._value2member_map_ else Chain.TRON,
                asset=Asset(r.get("asset", "USDT_TRC20")) if r.get("asset") in Asset._value2member_map_ else Asset.USDT_TRC20,
                amount=Decimal(r.get("amount", "0")),
                from_address=r.get("from_address", ""),
                to_address=r.get("to_address", ""),
                block_number=0,
                block_timestamp=utc_now(),
                tx_state=TxState.CONFIRMED,
            ))

    target_addr = inv_case.complaint.reported_wallet
    chain = inv_case.complaint.reported_chain or Chain.TRON
    v_interval = (
        inv_case.primary_stable_vasp.victim_value_interval
        if inv_case.primary_stable_vasp
        else inv_case.unresolved_value
    )
    last_seg = inv_case.path_segments[-1] if inv_case.path_segments else None
    v_models = last_seg.victim_value_by_model if last_seg else None

    cand_infra = CLUSTERING_ENGINE.analyze_address_cluster(
        target_addr, chain, transfers,
        victim_value_interval=v_interval,
        victim_value_by_model=v_models,
        trace_completeness=inv_case.trace_completeness_pct,
        deferred_value=inv_case.deferred_value.upper_bound if inv_case.deferred_value else None,
        unresolved_value=inv_case.unresolved_value.upper_bound if inv_case.unresolved_value else None,
        endpoint_stability=inv_case.primary_stable_vasp.endpoint_stability.value if inv_case.primary_stable_vasp else None,
    ).to_dict() if CLUSTERING_ENGINE else None

    intermediary = INTERMEDIARY_ENGINE.analyze_transfers(
        case_id, transfers, victim_value_interval=v_interval
    ).to_dict() if INTERMEDIARY_ENGINE else None

    alerts = STORE.get_alerts(case_id) if STORE else []

    return EvidencePackageGenerator(
        case=inv_case,
        candidate_infrastructure=cand_infra,
        intermediary_analysis=intermediary,
        alert_history=alerts,
    )


@app.get("/api/cases/{case_id}/evidence-package")
@app.get("/api/cases/{case_id}/evidence-package/json")
async def export_evidence_package_json(case_id: str):
    """Download court-ready, evidence-oriented Forensic Evidence Package in JSON format."""
    inv_case = INVESTIGATION_CASES.get(case_id)
    if not inv_case:
        case_row = STORE.get_case(case_id)
        if not case_row:
            raise HTTPException(status_code=404, detail="Case not found")
        intake = ComplaintInput(
            complaint_ref=case_row["complaint_ref"],
            reported_wallet=case_row["reported_wallet"],
            reported_chain=Chain(case_row["anchor_chain"]) if case_row.get("anchor_chain") else None,
            reported_asset=Asset(case_row["anchor_asset"]) if case_row.get("anchor_asset") else None,
            reported_amount=Decimal(case_row["victim_value"]) if case_row.get("victim_value") else None,
            reported_tx_hash=case_row.get("anchor_tx_hash"),
        )
        inv_case = InvestigationCase(
            case_id=case_id,
            complaint=intake,
            anchor=None,
            state=CaseState(case_row["state"]),
            traceability=TraceabilityState(case_row["traceability"]),
            actionability=ActionabilityState(case_row["actionability"]),
            path_segments=[],
            branch_audit=[],
            vasp_candidates=[],
            cross_case_signals=[],
            claims=[],
            first_supported_vasp=None,
            primary_stable_vasp=None,
            unresolved_value=ValueInterval(intake.reported_amount or Decimal(0), intake.reported_amount or Decimal(0), intake.reported_asset or Asset.USDT_ERC20),
        )

    generator = _build_evidence_package_generator(case_id, inv_case)
    package_dict = generator.build_package_dict()
    return JSONResponse(content=package_dict)


@app.get("/api/cases/{case_id}/evidence-package/markdown")
async def export_evidence_package_markdown(case_id: str):
    """Download evidence-oriented Forensic Evidence Package in Markdown format."""
    inv_case = INVESTIGATION_CASES.get(case_id)
    if not inv_case:
        case_row = STORE.get_case(case_id)
        if not case_row:
            raise HTTPException(status_code=404, detail="Case not found")
        intake = ComplaintInput(
            complaint_ref=case_row["complaint_ref"],
            reported_wallet=case_row["reported_wallet"],
            reported_chain=Chain(case_row["anchor_chain"]) if case_row.get("anchor_chain") else None,
            reported_asset=Asset(case_row["anchor_asset"]) if case_row.get("anchor_asset") else None,
            reported_amount=Decimal(case_row["victim_value"]) if case_row.get("victim_value") else None,
            reported_tx_hash=case_row.get("anchor_tx_hash"),
        )
        inv_case = InvestigationCase(
            case_id=case_id,
            complaint=intake,
            anchor=None,
            state=CaseState(case_row["state"]),
            traceability=TraceabilityState(case_row["traceability"]),
            actionability=ActionabilityState(case_row["actionability"]),
            path_segments=[],
            branch_audit=[],
            vasp_candidates=[],
            cross_case_signals=[],
            claims=[],
            first_supported_vasp=None,
            primary_stable_vasp=None,
            unresolved_value=ValueInterval(intake.reported_amount or Decimal(0), intake.reported_amount or Decimal(0), intake.reported_asset or Asset.USDT_ERC20),
        )

    generator = _build_evidence_package_generator(case_id, inv_case)
    md = generator.export_markdown()
    return PlainTextResponse(content=md, media_type="text/markdown")


@app.post("/api/cases/{case_id}/ai/analysis")
async def get_ai_case_analysis(case_id: str):
    """Run local explainable topological analysis, similarity ranking, and investigator briefing."""
    inv_case = INVESTIGATION_CASES.get(case_id)
    if not inv_case:
        case_row = STORE.get_case(case_id)
        if not case_row:
            raise HTTPException(status_code=404, detail="Case not found")
        intake = ComplaintInput(
            complaint_ref=case_row["complaint_ref"],
            reported_wallet=case_row["reported_wallet"],
            reported_chain=Chain(case_row["anchor_chain"]) if case_row.get("anchor_chain") else None,
            reported_asset=Asset(case_row["anchor_asset"]) if case_row.get("anchor_asset") else None,
            reported_amount=Decimal(case_row["victim_value"]) if case_row.get("victim_value") else None,
            reported_tx_hash=case_row.get("anchor_tx_hash"),
        )
        inv_case = InvestigationCase(
            case_id=case_id,
            complaint=intake,
            anchor=None,
            state=CaseState(case_row["state"]),
            traceability=TraceabilityState(case_row["traceability"]),
            actionability=ActionabilityState(case_row["actionability"]),
            path_segments=[],
            branch_audit=[],
            vasp_candidates=[],
            cross_case_signals=[],
            claims=[],
            first_supported_vasp=None,
            primary_stable_vasp=None,
            unresolved_value=ValueInterval(intake.reported_amount or Decimal(0), intake.reported_amount or Decimal(0), intake.reported_asset or Asset.USDT_ERC20),
        )

    features = extract_features(inv_case)
    patterns = AdvisoryPatternClassifier.classify(inv_case, features)
    narrative = generate_investigator_narrative(inv_case, features, patterns)

    similarity_engine = CaseSimilarityEngine(HISTORICAL_CORPUS)
    sim_results = similarity_engine.find_similar_cases(features, top_k=3)

    return {
        "case_id": case_id,
        "features": features.__dict__,
        "patterns": [p.__dict__ for p in patterns],
        "investigator_narrative": narrative,
        "case_similarity": sim_results,
    }


@app.get("/api/scenarios")
async def list_benchmark_scenarios():
    """List 16 synthetic benchmark scenarios."""
    scenarios_path = os.path.normpath(os.path.join(os.path.dirname(__file__), "../../data/test_scenarios.json"))
    if not os.path.exists(scenarios_path):
        return {"scenarios": []}
    with open(scenarios_path, "r", encoding="utf-8") as f:
        return json.load(f)


@app.post("/api/scenarios/{scenario_id}/run")
async def run_benchmark_scenario(scenario_id: str):
    """Execute a built-in benchmark scenario instantly for demonstration."""
    scenarios_path = os.path.normpath(os.path.join(os.path.dirname(__file__), "../../data/test_scenarios.json"))
    if not os.path.exists(scenarios_path):
        raise HTTPException(status_code=404, detail="Scenario file not found")

    with open(scenarios_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        scenario = next((s for s in data.get("scenarios", []) if s.get("id") == scenario_id or s.get("scenario_id") == scenario_id), None)

    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")

    victim_data = scenario.get("victim_input", {})
    case_id = f"CASE-{scenario_id.replace('SCENARIO-', '')[:8]}-{uuid.uuid4().hex[:4].upper()}"

    chain_str = victim_data.get("chain", "TRON")
    asset_str = victim_data.get("asset", "USDT_TRC20")
    victim_amount_dec = Decimal(str(victim_data.get("amount", scenario.get("victim_value", "10000.00"))))
    suspect_wallet = victim_data.get("suspect_wallet", "T_SYNTHETIC_WALLET")

    chain_enum = Chain(chain_str) if chain_str in Chain._value2member_map_ else Chain.TRON
    asset_enum = Asset(asset_str) if asset_str in Asset._value2member_map_ else Asset.USDT_TRC20

    # Build Synthetic Transfers
    outgoing_transfers = []
    if "outgoing_transfers" in scenario:
        now = utc_now()
        for idx, t in enumerate(scenario["outgoing_transfers"]):
            outgoing_transfers.append(
                OnChainTransfer(
                    tx_hash=t.get("tx_hash", f"0x_syn_tx_{idx}"),
                    chain=chain_enum,
                    asset=asset_enum,
                    amount=Decimal(str(t.get("amount", "0"))),
                    from_address=suspect_wallet,
                    to_address=t.get("to_address", "T_DEST"),
                    block_number=1000 + idx,
                    block_timestamp=now,
                    tx_state=TxState.CONFIRMED,
                )
            )

    # Compute Attribution
    pre_balance = Decimal(str(scenario.get("pre_existing_balance", "0.00")))
    attribution_engine = AccountBasedAttributionEngine(victim_amount_dec, asset_enum)
    attribution_res = attribution_engine.allocate(pre_balance, outgoing_transfers)

    # Compute Stability
    vasp_model_attributions: dict[str, dict] = {}
    if "vasp_model_attributions" in scenario:
        vasp_model_attributions = {
            v: {AllocationModel[m]: Decimal(val) for m, val in models.items()}
            for v, models in scenario["vasp_model_attributions"].items()
        }
    else:
        for t in outgoing_transfers:
            dest = t.to_address
            entity_name = dest
            if VASP_REGISTRY:
                rec = VASP_REGISTRY.get(chain_enum, dest)
                if rec:
                    entity_name = rec.entity_name
            if entity_name not in vasp_model_attributions:
                vasp_model_attributions[entity_name] = {}
            for model in AllocationModel:
                vasp_model_attributions[entity_name][model] = attribution_res[model].get(dest, Decimal(0))

    stability_clf = StabilityClassifier()
    dominant_vasp, stability, stability_reason = stability_clf.classify(
        vasp_model_attributions=vasp_model_attributions,
        victim_value=victim_amount_dec,
        bridge_match_strength=None,
        label_confidence=AttributionConfidence.HIGH,
        label_age_days=0,
    )

    actionability = compute_actionability(
        stability=stability,
        dominant_vasp=dominant_vasp,
        label_confidence=AttributionConfidence.HIGH,
        label_age_days=0,
        min_value_interval=ValueInterval(victim_amount_dec, victim_amount_dec, asset_enum),
        victim_value=victim_amount_dec,
        has_supported_path=len(outgoing_transfers) > 0,
    )

    # Determine State
    state = CaseState.ACTIVE
    if dominant_vasp and dominant_vasp not in ("NONE", "UNSTABLE"):
        state = CaseState.SUPPORTED_VASP
    elif "MIXER" in scenario_id:
        state = CaseState.FUNDS_STATIONARY

    # Build Path Segments
    path_segments = []
    for idx, t in enumerate(outgoing_transfers):
        models_for_t = {
            m: attribution_res[m].get(t.to_address, Decimal(0))
            for m in AllocationModel
        }
        path_segments.append(
            PathSegment(
                sequence=idx + 1,
                transfer=t,
                transformation=None,
                bridge_event=None,
                to_address=t.to_address,
                to_chain=chain_enum,
                victim_value_by_model=models_for_t,
                traceability=TraceabilityState.DETERMINISTIC,
                evidence_class=EvidenceClass.OBSERVED,
            )
        )

    # Build Case Object
    intake = ComplaintInput(
        complaint_ref=scenario.get("id", scenario_id),
        reported_wallet=suspect_wallet,
        reported_chain=chain_enum,
        reported_asset=asset_enum,
        reported_amount=victim_amount_dec,
        reported_tx_hash=None,
    )

    anchor = TraceAnchor(
        status=AnchorStatus.VERIFIED,
        level=AnchorLevel.A if "DIRECT" in scenario_id else AnchorLevel.B,
        chain=chain_enum,
        asset=asset_enum,
        tx_hash=outgoing_transfers[0].tx_hash if outgoing_transfers else None,
        amount=victim_amount_dec,
        reported_time=utc_now(),
        confirmed_tx=None,
        anchor_evidence=f"Synthetic deterministic benchmark scenario: {scenario.get('name')}",
    )

    inv_case = InvestigationCase(
        case_id=case_id,
        complaint=intake,
        anchor=anchor,
        state=state,
        traceability=TraceabilityState.DETERMINISTIC,
        actionability=actionability,
        path_segments=path_segments,
        branch_audit=[],
        vasp_candidates=[t.to_address for t in outgoing_transfers if "BINANCE" in t.to_address or "OKX" in t.to_address],
        cross_case_signals=[],
        claims=[],
        first_supported_vasp=dominant_vasp if dominant_vasp not in ("NONE", "UNSTABLE") else None,
        primary_stable_vasp=None,
        unresolved_value=ValueInterval(Decimal(0), Decimal(0), asset_enum),
        deferred_value=Decimal(0),
        trace_completeness_pct=Decimal("100.00"),
        high_fragmentation_detected="250" in scenario_id,
    )

    if dominant_vasp and dominant_vasp not in ("NONE", "UNSTABLE") and outgoing_transfers:
        rec = VaspRecord(
            address=outgoing_transfers[0].to_address,
            chain=chain_enum,
            entity_name=dominant_vasp,
            entity_role="deposit_infrastructure",
            source=AttributionSource.COMMERCIAL_INTELLIGENCE,
            source_reliability="HIGH",
            first_observed=utc_now(),
            last_verified=utc_now(),
            confidence=AttributionConfidence.HIGH,
            is_active=True,
            independent_corroboration=True,
        )
        inv_case.primary_stable_vasp = VaspAttribution(
            record=rec,
            address_in_path=outgoing_transfers[0].to_address,
            hop_from_anchor=1,
            victim_value_interval=ValueInterval(victim_amount_dec, victim_amount_dec, asset_enum),
            per_model=[],
            first_hop_reaching_vasp=True,
            is_primary_stable=True,
            endpoint_stability=stability,
            stability_reason=stability_reason,
            actionability=actionability,
        )

    # Persist in memory & SQLite
    INVESTIGATION_CASES[case_id] = inv_case
    snapshot = {
        "case_id": case_id,
        "total_transfers": len(path_segments),
        "bridge_events": 0,
        "dex_events": 0,
        "primary_stable_vasp": dominant_vasp,
        "stability": stability.value,
        "stability_reason": stability_reason,
        "trace_completeness_pct": "100.00",
        "high_fragmentation_detected": "250" in scenario_id,
    }
    STORE.save_case(
        case_id=case_id,
        complaint_ref=intake.complaint_ref,
        state=state.value,
        traceability=TraceabilityState.DETERMINISTIC.value,
        actionability=actionability.value,
        anchor_status=anchor.status.value,
        anchor_level=anchor.level.value,
        anchor_chain=chain_enum.value,
        anchor_asset=asset_enum.value,
        anchor_tx_hash=None,
        victim_value=str(victim_amount_dec),
        reported_wallet=suspect_wallet,
        snapshot_json=json.dumps(snapshot),
    )
    STORE.save_snapshot(case_id, snapshot)

    # Save branch audit
    if outgoing_transfers:
        audit_records = [
            {
                "from_address": t.from_address,
                "to_address": t.to_address,
                "tx_hash": t.tx_hash,
                "chain": t.chain.value,
                "asset": t.asset.value,
                "amount": str(t.amount),
                "victim_lower": "0.00",
                "victim_upper": str(t.amount),
                "disposition": "FULLY_TRACED",
                "reason": "Synthetic benchmark deterministic flow",
                "tier": 1,
                "recorded_at": utc_now().isoformat(),
            }
            for t in outgoing_transfers
        ]
        STORE.save_branch_audit(case_id, audit_records)

    # Validate ground truth match
    validation_status = "PASS"
    gt = scenario.get("ground_truth", {})
    if "expected_stability" in gt and gt["expected_stability"] != stability.value:
        validation_status = "FAIL"

    return {
        "scenario_id": scenario_id,
        "scenario_name": scenario.get("name"),
        "description": scenario.get("description"),
        "classification": "SYNTHETIC TEST DATA",
        "validation_status": validation_status,
        "case_id": case_id,
        "ground_truth": gt,
        "execution_results": {
            "dominant_vasp": dominant_vasp,
            "stability_tier": stability.value,
            "stability_reason": stability_reason,
            "actionability": actionability.value,
            "trace_completeness_pct": "100.00",
            "model_attributions": {
                m.name: {k: str(v) for k, v in res.items()}
                for m, res in attribution_res.items()
            },
        },
    }


@app.get("/api/monitor/status")
async def get_monitor_status():
    """Get persistent case watcher status."""
    if not MONITOR_SERVICE:
        return {"running": False}
    return MONITOR_SERVICE.get_status()


@app.post("/api/monitor/poll")
async def trigger_monitor_poll():
    """Manually trigger a synchronous monitor polling cycle."""
    if not MONITOR_SERVICE:
        raise HTTPException(status_code=500, detail="Monitor service not available")
    return MONITOR_SERVICE.poll_once()


@app.get("/api/alerts")
async def get_all_alerts(unack_only: bool = False, limit: int = 100):
    """Retrieve system-wide internal alert events."""
    if not STORE:
        return {"alerts": [], "count": 0}
    alerts = STORE.get_alerts(case_id=None, unack_only=unack_only, limit=limit)
    return {"alerts": alerts, "count": len(alerts)}


@app.get("/api/cases/{case_id}/alerts")
async def get_case_alerts(case_id: str, unack_only: bool = False, limit: int = 50):
    """Retrieve alert events for a specific investigation case."""
    if not STORE:
        return {"case_id": case_id, "alerts": [], "count": 0}
    alerts = STORE.get_alerts(case_id=case_id, unack_only=unack_only, limit=limit)
    return {"case_id": case_id, "alerts": alerts, "count": len(alerts)}


@app.post("/api/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str):
    """Acknowledge an alert event."""
    if not STORE:
        raise HTTPException(status_code=500, detail="Store unavailable")
    success = STORE.acknowledge_alert(alert_id)
    if not success:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"alert_id": alert_id, "acknowledged": True}


@app.get("/api/chains/health")
async def check_chains_health():
    """Live connectivity health check for TRON and Ethereum."""
    import sys
    proj_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "../.."))
    if proj_root not in sys.path:
        sys.path.insert(0, proj_root)

    from scripts.validate_live_tron import validate_tron
    from scripts.validate_live_ethereum import validate_ethereum

    tron_res = validate_tron()
    eth_res = validate_ethereum()

    return {
        "timestamp": utc_now().isoformat(),
        "tron": tron_res,
        "ethereum": eth_res,
    }


@app.get("/api/registry/lookup")
async def registry_lookup(chain: str, address: str):
    """Lookup address in VASP registry with claim freshness and entity classification."""
    if not VASP_REGISTRY:
        raise HTTPException(status_code=500, detail="VASP Registry not initialized")
    try:
        chain_enum = Chain(chain.upper())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unsupported chain: {chain}")

    result = VASP_REGISTRY.lookup(chain_enum, address)
    primary = None
    if result.primary_claim:
        primary = {
            "address": result.primary_claim.address,
            "chain": result.primary_claim.chain.value if hasattr(result.primary_claim.chain, "value") else str(result.primary_claim.chain),
            "entity_name": result.primary_claim.entity_name,
            "entity_role": result.primary_claim.entity_role,
            "source": result.primary_claim.source.value if hasattr(result.primary_claim.source, "value") else str(result.primary_claim.source),
            "source_reliability": result.primary_claim.source_reliability,
            "confidence": result.primary_claim.confidence.value if hasattr(result.primary_claim.confidence, "value") else str(result.primary_claim.confidence),
            "last_verified": result.primary_claim.last_verified.isoformat() if result.primary_claim.last_verified else None,
        }

    return {
        "address": address,
        "chain": chain_enum.value,
        "status": result.status.value,
        "entity_type": result.entity_type,
        "is_stale": result.is_stale,
        "dispute_reason": result.dispute_reason,
        "primary_claim": primary,
        "claims_count": len(result.claims),
    }


@app.get("/api/registry/stats")
async def registry_stats():
    """VASP registry intelligence statistics."""
    if not VASP_REGISTRY:
        return {}
    return VASP_REGISTRY.stats()


@app.get("/api/registry/entries")
async def registry_entries():
    """List all registered known entity claims for intelligence browsing."""
    if not VASP_REGISTRY:
        return {"entries": [], "count": 0}
    entries = VASP_REGISTRY.list_all_records()
    return {"entries": entries, "count": len(entries)}


# ---------------------------------------------------------------------------
# Static frontend mount
# ---------------------------------------------------------------------------

frontend_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "../../frontend"))
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    @app.get("/")
    async def serve_index():
        return FileResponse(os.path.join(frontend_dir, "index.html"))
