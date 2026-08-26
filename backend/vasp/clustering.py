"""
Exchange Infrastructure Clustering & Address Disambiguation Engine.

Differentiates:
  1. KNOWN_ADDRESS: Directly registered in verified VASP intelligence database.
  2. STRONG_INFRASTRUCTURE_INFERENCE: Repeated sweeps to known exchange hot-wallet + deposit funnel fan-in.
  3. MODERATE_INFRASTRUCTURE_INFERENCE: Repeated sweeps to known exchange hot-wallet without full fan-in.
  4. WEAK_CANDIDATE: Behavioral fan-in and rapid forwarding without verified destination entity.
  5. UNRESOLVED: Insufficient observations (<2 transfers), one-off transfers, or hard contradictions.

Analytical Principles:
- A heuristic clustering result must NEVER automatically become a verified VASP claim.
- Preserves explicit contradiction checks (mixer boundary, conflicting VASP destinations, long personal holding duration).
- Preserves victim-value interval, model agreement (Conservative, Proportional, FIFO, LIFO), trace completeness, and deferred/unresolved mass without independent value invention.
- Distinguishes generic contextual graph topology from victim-linked case endpoints.
"""

from __future__ import annotations
import datetime
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional, Any

from ..core.models import (
    Chain, Asset, AttributionSource, AttributionConfidence, EvidenceClass,
    OnChainTransfer, ValueInterval, AllocationModel, EndpointStability, utc_now
)


class InferenceStrength(str, Enum):
    KNOWN_ADDRESS = "KNOWN_ADDRESS"
    STRONG_INFRASTRUCTURE_INFERENCE = "STRONG_INFRASTRUCTURE_INFERENCE"
    MODERATE_INFRASTRUCTURE_INFERENCE = "MODERATE_INFRASTRUCTURE_INFERENCE"
    WEAK_CANDIDATE = "WEAK_CANDIDATE"
    UNRESOLVED = "UNRESOLVED"


class CandidateRole(str, Enum):
    DEPOSIT_SWEEPER = "DEPOSIT_SWEEPER"
    HOT_WALLET = "HOT_WALLET"
    COLD_STORAGE = "COLD_STORAGE"
    CONSOLIDATION_INTERMEDIARY = "CONSOLIDATION_INTERMEDIARY"
    UNRESOLVED = "UNRESOLVED"


@dataclass
class ClusterFeatureEvidence:
    """10 deterministic feature models evaluated during clustering."""
    deposit_funnel_detected: bool = False
    repeated_sweep_destination: bool = False
    sweep_destination_address: Optional[str] = None
    sweep_count: int = 0
    short_dwell_time_seconds: Optional[float] = None
    value_consolidation_ratio: Optional[float] = None
    counterparty_overlap_count: int = 0
    known_vasp_proximity_hops: Optional[int] = None
    known_vasp_entity: Optional[str] = None
    repeated_behavioral_consistency: bool = False
    sweep_to_hot_wallet: bool = False
    deposit_address_fan_in: bool = False
    shared_infrastructure_notes: list[str] = field(default_factory=list)


@dataclass
class ContradictoryEvidence:
    """Explicit checks for why an address should NOT be clustered."""
    is_one_off_transfer_only: bool = False
    unrelated_counterparties: bool = False
    long_term_personal_wallet_usage: bool = False
    conflicting_vasp_destinations: list[str] = field(default_factory=list)
    no_repeated_sweep_behavior: bool = False
    bridge_uncertainty_present: bool = False
    mixer_boundary_present: bool = False
    insufficient_observations: bool = False
    notes: list[str] = field(default_factory=list)

    def has_hard_contradiction(self) -> bool:
        return (
            self.mixer_boundary_present or
            len(self.conflicting_vasp_destinations) > 1 or
            self.is_one_off_transfer_only
        )


@dataclass
class ClusterHypothesis:
    """
    Structured hypothesis object representing candidate exchange infrastructure.
    Tied directly to victim-attributed value and model agreement.
    No black-box scores — purely explainable, evidence-backed attribution.
    """
    cluster_id: str
    candidate_entity: Optional[str]
    member_addresses: list[str]
    seed_addresses: list[str]
    candidate_role: CandidateRole
    inference_strength: InferenceStrength
    confidence: AttributionConfidence
    feature_evidence: ClusterFeatureEvidence
    contradictions: ContradictoryEvidence
    supporting_tx_hashes: list[str]
    evidence_refs: list[str]
    first_observed: datetime.datetime
    last_observed: datetime.datetime
    explanation: str

    # Victim-value linkage & model agreement
    is_victim_linked: bool = False
    victim_value_interval: Optional[ValueInterval] = None
    supporting_models: dict[str, str] = field(default_factory=dict)
    trace_completeness: Optional[float] = None
    deferred_value: Optional[Decimal] = None
    unresolved_value: Optional[Decimal] = None
    endpoint_stability: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "candidate_entity": self.candidate_entity,
            "member_addresses": self.member_addresses,
            "seed_addresses": self.seed_addresses,
            "candidate_role": self.candidate_role.value,
            "inference_strength": self.inference_strength.value,
            "confidence": self.confidence.value,
            "is_victim_linked": self.is_victim_linked,
            "victim_value": {
                "min": str(self.victim_value_interval.lower_bound) if self.victim_value_interval else "0.00",
                "max": str(self.victim_value_interval.upper_bound) if self.victim_value_interval else "0.00",
                "asset": self.victim_value_interval.asset.value if self.victim_value_interval and hasattr(self.victim_value_interval.asset, "value") else "USDT",
                "non_additive_across_hypotheses": True,
            } if self.victim_value_interval else None,
            "models": self.supporting_models,
            "trace_completeness": self.trace_completeness,
            "deferred_value": str(self.deferred_value) if self.deferred_value is not None else None,
            "unresolved_value": str(self.unresolved_value) if self.unresolved_value is not None else None,
            "endpoint_stability": self.endpoint_stability,
            "feature_evidence": {
                "deposit_funnel_detected": self.feature_evidence.deposit_funnel_detected,
                "repeated_sweep_destination": self.feature_evidence.repeated_sweep_destination,
                "sweep_destination_address": self.feature_evidence.sweep_destination_address,
                "sweep_count": self.feature_evidence.sweep_count,
                "short_dwell_time_seconds": self.feature_evidence.short_dwell_time_seconds,
                "value_consolidation_ratio": self.feature_evidence.value_consolidation_ratio,
                "counterparty_overlap_count": self.feature_evidence.counterparty_overlap_count,
                "known_vasp_proximity_hops": self.feature_evidence.known_vasp_proximity_hops,
                "known_vasp_entity": self.feature_evidence.known_vasp_entity,
                "repeated_behavioral_consistency": self.feature_evidence.repeated_behavioral_consistency,
                "sweep_to_hot_wallet": self.feature_evidence.sweep_to_hot_wallet,
                "deposit_address_fan_in": self.feature_evidence.deposit_address_fan_in,
                "shared_infrastructure_notes": self.feature_evidence.shared_infrastructure_notes,
            },
            "contradictions": {
                "is_one_off_transfer_only": self.contradictions.is_one_off_transfer_only,
                "unrelated_counterparties": self.contradictions.unrelated_counterparties,
                "long_term_personal_wallet_usage": self.contradictions.long_term_personal_wallet_usage,
                "conflicting_vasp_destinations": self.contradictions.conflicting_vasp_destinations,
                "no_repeated_sweep_behavior": self.contradictions.no_repeated_sweep_behavior,
                "bridge_uncertainty_present": self.contradictions.bridge_uncertainty_present,
                "mixer_boundary_present": self.contradictions.mixer_boundary_present,
                "insufficient_observations": self.contradictions.insufficient_observations,
                "notes": self.contradictions.notes,
            },
            "supporting_tx_hashes": self.supporting_tx_hashes,
            "evidence_refs": self.evidence_refs,
            "first_observed": self.first_observed.isoformat(),
            "last_observed": self.last_observed.isoformat(),
            "explanation": self.explanation,
        }


def compute_model_support(victim_value_by_model: Optional[dict[AllocationModel, Decimal]]) -> dict[str, str]:
    """Derives model support breakdown across CONSERVATIVE, PROPORTIONAL, FIFO, LIFO."""
    models_status: dict[str, str] = {}
    standard_models = [
        AllocationModel.CONSERVATIVE,
        AllocationModel.PROPORTIONAL,
        AllocationModel.FIFO,
        AllocationModel.LIFO,
    ]
    for m in standard_models:
        key = m.value
        if victim_value_by_model is not None and m in victim_value_by_model:
            val = victim_value_by_model[m]
            models_status[key] = "SUPPORTED" if val > Decimal(0) else "DISAGREES"
        else:
            models_status[key] = "UNAVAILABLE"
    return models_status


class ExchangeInfrastructureClusteringEngine:
    """
    Evaluates on-chain transaction sequences to identify deposit sweeper patterns,
    consolidation fan-in, and hot-wallet sweep relationships with victim-value linkage.
    """

    def __init__(self, known_vasp_lookup_fn=None):
        self._lookup_vasp = known_vasp_lookup_fn

    def analyze_address_cluster(
        self,
        target_address: str,
        chain: Chain,
        transfers: list[OnChainTransfer],
        known_vasp_name: Optional[str] = None,
        victim_value_interval: Optional[ValueInterval] = None,
        victim_value_by_model: Optional[dict[AllocationModel, Decimal]] = None,
        trace_completeness: Optional[float] = None,
        deferred_value: Optional[Decimal] = None,
        unresolved_value: Optional[Decimal] = None,
        endpoint_stability: Optional[str] = None,
    ) -> ClusterHypothesis:
        """
        Analyzes inbound and outbound transfers for a target address to evaluate
        whether it behaves as an exchange deposit funnel, sweeper, or personal wallet.
        Integrates victim-value interval and model agreement when available.
        """
        addr_lower = target_address.lower()
        inbound = [t for t in transfers if t.to_address.lower() == addr_lower]
        outbound = [t for t in transfers if t.from_address.lower() == addr_lower]

        now = utc_now()
        first_obs = min((t.block_timestamp for t in transfers), default=now)
        last_obs = max((t.block_timestamp for t in transfers), default=now)
        tx_hashes = list(dict.fromkeys(t.tx_hash for t in transfers))

        # Check victim-value reachability
        is_victim_linked = False
        if victim_value_interval is not None and victim_value_interval.upper_bound > Decimal(0):
            is_victim_linked = True
        elif victim_value_by_model and any(v > Decimal(0) for v in victim_value_by_model.values()):
            is_victim_linked = True

        supporting_models = compute_model_support(victim_value_by_model)

        # Check if address is ALREADY a known deterministic VASP address
        if self._lookup_vasp:
            known_match = self._lookup_vasp(chain, target_address)
            if known_match:
                return ClusterHypothesis(
                    cluster_id=f"CLUSTER-KNOWN-{target_address[:10]}",
                    candidate_entity=known_match,
                    member_addresses=[target_address],
                    seed_addresses=[target_address],
                    candidate_role=CandidateRole.DEPOSIT_SWEEPER,
                    inference_strength=InferenceStrength.KNOWN_ADDRESS,
                    confidence=AttributionConfidence.HIGH,
                    is_victim_linked=is_victim_linked,
                    victim_value_interval=victim_value_interval,
                    supporting_models=supporting_models,
                    trace_completeness=trace_completeness,
                    deferred_value=deferred_value,
                    unresolved_value=unresolved_value,
                    endpoint_stability=endpoint_stability or EndpointStability.HIGH.value,
                    feature_evidence=ClusterFeatureEvidence(
                        known_vasp_entity=known_match,
                        known_vasp_proximity_hops=0,
                        shared_infrastructure_notes=[f"Address is directly in the verified {known_match} registry."]
                    ),
                    contradictions=ContradictoryEvidence(),
                    supporting_tx_hashes=tx_hashes,
                    evidence_refs=[f"REGISTRY-MATCH-{known_match}"],
                    first_observed=first_obs,
                    last_observed=last_obs,
                    explanation=f"Address {target_address} is a verified, deterministic {known_match} endpoint.",
                )

        features = ClusterFeatureEvidence()
        contradictions = ContradictoryEvidence()

        # Insufficient observations check
        if len(transfers) < 2:
            contradictions.insufficient_observations = True
            contradictions.is_one_off_transfer_only = (len(transfers) == 1)
            contradictions.notes.append("Fewer than 2 transfers observed for target address.")

            return ClusterHypothesis(
                cluster_id=f"CLUSTER-UNRESOLVED-{target_address[:10]}",
                candidate_entity=None,
                member_addresses=[target_address],
                seed_addresses=[target_address],
                candidate_role=CandidateRole.UNRESOLVED,
                inference_strength=InferenceStrength.UNRESOLVED,
                confidence=AttributionConfidence.LOW,
                is_victim_linked=is_victim_linked,
                victim_value_interval=victim_value_interval,
                supporting_models=supporting_models,
                trace_completeness=trace_completeness,
                deferred_value=deferred_value,
                unresolved_value=unresolved_value,
                endpoint_stability=endpoint_stability,
                feature_evidence=features,
                contradictions=contradictions,
                supporting_tx_hashes=tx_hashes,
                evidence_refs=[],
                first_observed=first_obs,
                last_observed=last_obs,
                explanation="Insufficient on-chain transfer history to evaluate infrastructure clustering." + (" Note: Contextual graph intelligence; not a victim-linked case endpoint." if not is_victim_linked else ""),
            )

        # 1. Evaluate Deposit Funnel & Repeated Sweeps
        outbound_destinations: dict[str, list[OnChainTransfer]] = {}
        for ot in outbound:
            dest = ot.to_address.lower()
            outbound_destinations.setdefault(dest, []).append(ot)

        dominant_dest = None
        dominant_count = 0
        for dest, dest_txs in outbound_destinations.items():
            if len(dest_txs) > dominant_count:
                dominant_dest = dest
                dominant_count = len(dest_txs)

        if dominant_dest and dominant_count >= 2:
            features.repeated_sweep_destination = True
            features.sweep_destination_address = dominant_dest
            features.sweep_count = dominant_count
            features.sweep_to_hot_wallet = True
        elif len(outbound) > 0 and len(outbound_destinations) > 3:
            contradictions.unrelated_counterparties = True
            contradictions.notes.append(f"Outbound transfers disperse to {len(outbound_destinations)} unrelated addresses.")

        # 2. Evaluate Fan-In / Consolidation Ratio
        if len(inbound) >= 3 and len(outbound) <= 2:
            features.deposit_address_fan_in = True
            features.deposit_funnel_detected = True
            features.value_consolidation_ratio = float(len(inbound) / max(1, len(outbound)))

        # 3. Evaluate Dwell Time (Inbound -> Outbound duration)
        dwell_times = []
        for it in inbound:
            for ot in outbound:
                if ot.block_timestamp >= it.block_timestamp:
                    delta = (ot.block_timestamp - it.block_timestamp).total_seconds()
                    dwell_times.append(delta)

        if dwell_times:
            avg_dwell = sum(dwell_times) / len(dwell_times)
            features.short_dwell_time_seconds = avg_dwell
            if avg_dwell < 600:
                features.repeated_behavioral_consistency = True
                features.shared_infrastructure_notes.append(f"Rapid forwarding detected (avg dwell: {avg_dwell:.0f}s).")
            elif avg_dwell > 86400 * 7:
                contradictions.long_term_personal_wallet_usage = True
                contradictions.notes.append("Long holding duration consistent with self-custody personal wallet.")

        # 4. Evaluate Proximity to Known VASP
        target_entity = known_vasp_name
        if not target_entity and dominant_dest and self._lookup_vasp:
            vasp_match = self._lookup_vasp(chain, dominant_dest)
            if vasp_match:
                features.known_vasp_proximity_hops = 1
                features.known_vasp_entity = vasp_match
                target_entity = vasp_match

        # 5. Determine Inference Strength & Role
        inference_strength = InferenceStrength.UNRESOLVED
        confidence = AttributionConfidence.LOW
        candidate_role = CandidateRole.UNRESOLVED

        if contradictions.has_hard_contradiction():
            inference_strength = InferenceStrength.UNRESOLVED
            confidence = AttributionConfidence.LOW
            candidate_role = CandidateRole.UNRESOLVED
            explanation = "Contradictory evidence (mixer boundary, conflicting VASP destinations, or one-off transfer) precludes clustering."
        elif features.known_vasp_proximity_hops == 1 and features.repeated_sweep_destination and features.deposit_funnel_detected:
            inference_strength = InferenceStrength.STRONG_INFRASTRUCTURE_INFERENCE
            confidence = AttributionConfidence.HIGH
            candidate_role = CandidateRole.DEPOSIT_SWEEPER
            explanation = f"Strong inference: Address displays repeated deposit fan-in with systematic sweeps to verified {target_entity} infrastructure."
        elif features.known_vasp_proximity_hops == 1 and features.repeated_sweep_destination:
            inference_strength = InferenceStrength.MODERATE_INFRASTRUCTURE_INFERENCE
            confidence = AttributionConfidence.MEDIUM
            candidate_role = CandidateRole.DEPOSIT_SWEEPER
            explanation = f"Moderate inference: Address repeatedly sweeps funds to known {target_entity} infrastructure ({dominant_count} sweeps observed)."
        elif features.deposit_address_fan_in and features.repeated_behavioral_consistency:
            inference_strength = InferenceStrength.WEAK_CANDIDATE
            confidence = AttributionConfidence.LOW
            candidate_role = CandidateRole.CONSOLIDATION_INTERMEDIARY
            explanation = "Weak candidate: Behavioral fan-in and rapid forwarding match sweeper patterns, but destination VASP entity is unverified."
        else:
            inference_strength = InferenceStrength.UNRESOLVED
            confidence = AttributionConfidence.LOW
            candidate_role = CandidateRole.UNRESOLVED
            explanation = "Transfers do not exhibit verified exchange infrastructure characteristics."

        if not is_victim_linked:
            contradictions.notes.append("Contextual graph observation only: No victim-attributed value reaches this candidate address.")
            explanation += " Note: Contextual graph intelligence; not a victim-linked case endpoint."

        return ClusterHypothesis(
            cluster_id=f"CLUSTER-INFRA-{target_address[:10]}",
            candidate_entity=target_entity,
            member_addresses=[target_address] + ([dominant_dest] if dominant_dest and inference_strength in (InferenceStrength.STRONG_INFRASTRUCTURE_INFERENCE, InferenceStrength.MODERATE_INFRASTRUCTURE_INFERENCE) else []),
            seed_addresses=[target_address],
            candidate_role=candidate_role,
            inference_strength=inference_strength,
            confidence=confidence,
            is_victim_linked=is_victim_linked,
            victim_value_interval=victim_value_interval,
            supporting_models=supporting_models,
            trace_completeness=trace_completeness,
            deferred_value=deferred_value,
            unresolved_value=unresolved_value,
            endpoint_stability=endpoint_stability,
            feature_evidence=features,
            contradictions=contradictions,
            supporting_tx_hashes=tx_hashes,
            evidence_refs=([f"REGISTRY-MATCH-{target_entity}"] if target_entity else []) + [f"FLOW-SWEEP-{h[:8]}" for h in tx_hashes[:3]],
            first_observed=first_obs,
            last_observed=last_obs,
            explanation=explanation,
        )
