"""
Tests for local AI/ML topological graph feature extraction, similarity ranking, and patterns.
"""

from decimal import Decimal
import pytest

from backend.core.models import (
    InvestigationCase, ComplaintInput, CaseState, TraceabilityState,
    ActionabilityState, ValueInterval, Asset, Chain, OnChainTransfer,
    TxState, PathSegment, EvidenceClass, AllocationModel, utc_now
)
from backend.ai.features import extract_features
from backend.ai.patterns import AdvisoryPatternClassifier
from backend.ai.similarity import CaseSimilarityEngine, compute_vector_distance
from backend.ai.summary import generate_investigator_narrative


def test_topological_feature_extraction_and_patterns():
    now = utc_now()
    intake = ComplaintInput(
        complaint_ref="TEST-AI-01",
        reported_wallet="0x_suspect_ai",
        reported_chain=Chain.ETHEREUM,
        reported_asset=Asset.USDT_ERC20,
        reported_amount=Decimal("50000.00"),
    )

    # 3-hop peeling chain
    segments = [
        PathSegment(
            sequence=0,
            transfer=OnChainTransfer("0x_t1", Chain.ETHEREUM, Asset.USDT_ERC20, Decimal("49000.00"), "0x_suspect_ai", "0x_hop1", 1, now, TxState.CONFIRMED),
            transformation=None,
            bridge_event=None,
            to_address="0x_hop1",
            to_chain=Chain.ETHEREUM,
            victim_value_by_model={AllocationModel.PROPORTIONAL: Decimal("49000.00")},
            traceability=TraceabilityState.SUPPORTED,
            evidence_class=EvidenceClass.OBSERVED,
        ),
        PathSegment(
            sequence=1,
            transfer=OnChainTransfer("0x_t2", Chain.ETHEREUM, Asset.USDT_ERC20, Decimal("48000.00"), "0x_hop1", "0x_hop2", 2, now, TxState.CONFIRMED),
            transformation=None,
            bridge_event=None,
            to_address="0x_hop2",
            to_chain=Chain.ETHEREUM,
            victim_value_by_model={AllocationModel.PROPORTIONAL: Decimal("48000.00")},
            traceability=TraceabilityState.SUPPORTED,
            evidence_class=EvidenceClass.OBSERVED,
        ),
        PathSegment(
            sequence=2,
            transfer=OnChainTransfer("0x_t3", Chain.ETHEREUM, Asset.USDT_ERC20, Decimal("47000.00"), "0x_hop2", "0x_hop3", 3, now, TxState.CONFIRMED),
            transformation=None,
            bridge_event=None,
            to_address="0x_hop3",
            to_chain=Chain.ETHEREUM,
            victim_value_by_model={AllocationModel.PROPORTIONAL: Decimal("47000.00")},
            traceability=TraceabilityState.SUPPORTED,
            evidence_class=EvidenceClass.OBSERVED,
        ),
    ]

    case = InvestigationCase(
        case_id="CASE-AI-TEST",
        complaint=intake,
        anchor=None,
        state=CaseState.ACTIVE,
        traceability=TraceabilityState.SUPPORTED,
        actionability=ActionabilityState.NO_ACTIONABLE_ENDPOINT,
        path_segments=segments,
        branch_audit=[],
        vasp_candidates=[],
        cross_case_signals=[],
        claims=[],
        first_supported_vasp=None,
        primary_stable_vasp=None,
        unresolved_value=ValueInterval(Decimal(0), Decimal(0), Asset.USDT_ERC20),
    )

    features = extract_features(case)
    assert features.hop_count == 3
    assert features.peeling_ratio >= 0.7

    patterns = AdvisoryPatternClassifier.classify(case, features)
    peeling_pat = next((p for p in patterns if p.pattern_name == "PEELING_CHAIN_LAYERING"), None)
    assert peeling_pat is not None
    assert peeling_pat.confidence == "MEDIUM"

    narrative = generate_investigator_narrative(case, features, patterns)
    assert "Investigative Briefing" in narrative
    assert "PEELING_CHAIN_LAYERING" in narrative


def test_similarity_insufficient_data_guard():
    features = [3.0, 1.0, 0.8, 0.0, 0.0, 1.0, 100.0, 0.0]
    # Corpus with only 2 cases
    small_corpus = [
        {"case_id": "CASE-1", "features": features},
        {"case_id": "CASE-2", "features": features},
    ]

    from backend.ai.features import GraphFeatureVector
    fv = GraphFeatureVector(3, 1.0, 0.8, 0, 0, 1, 100.0, 0.0)

    engine = CaseSimilarityEngine(small_corpus)
    res = engine.find_similar_cases(fv)

    assert res["status"] == "INSUFFICIENT_DATA"
    assert "minimum 3 required" in res["message"]


def test_similarity_computation_with_sufficient_corpus():
    features = [3.0, 1.0, 0.8, 0.0, 0.0, 1.0, 100.0, 0.0]
    corpus = [
        {"case_id": "CASE-1", "scenario_name": "Similar Peel", "features": [3.0, 1.0, 0.8, 0.0, 0.0, 1.0, 100.0, 0.0]},
        {"case_id": "CASE-2", "scenario_name": "Fanout Dispersal", "features": [1.0, 20.0, 0.0, 0.0, 0.0, 50.0, 500.0, 4.0]},
        {"case_id": "CASE-3", "scenario_name": "Bridge Move", "features": [2.0, 2.0, 0.5, 1.0, 0.0, 2.0, 800.0, 1.0]},
    ]

    from backend.ai.features import GraphFeatureVector
    fv = GraphFeatureVector(3, 1.0, 0.8, 0, 0, 1, 100.0, 0.0)

    engine = CaseSimilarityEngine(corpus)
    res = engine.find_similar_cases(fv, top_k=2)

    assert res["status"] == "COMPUTED"
    assert len(res["matches"]) == 2
    assert res["matches"][0]["case_id"] == "CASE-1"
    assert res["matches"][0]["similarity_score"] == 1.0
