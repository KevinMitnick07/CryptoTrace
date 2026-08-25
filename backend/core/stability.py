"""
VASP endpoint stability classifier.

After multi-hypothesis attribution reaches one or more VASP candidates,
this module evaluates whether the dominant VASP conclusion is stable
across the accepted allocation models.

Stability dimensions:
  1. Endpoint stability:     Does the same VASP dominate across all models?
  2. Value stability:        Is the attributed-value interval narrow?
  3. Label stability:        Is the VASP attribution label current and reliable?
  4. Cross-chain quality:    If a bridge was used, how strong was the match?

Output: HIGH / MEDIUM / LOW / UNRESOLVED with explicit reasons.
No percentages unless experimentally calibrated.
"""

from __future__ import annotations
import logging
from decimal import Decimal
from typing import Optional

from .models import (
    AllocationModel, EndpointStability,
    ActionabilityState, AttributionConfidence, BridgeMatchStrength,
    ValueInterval, Asset
)

log = logging.getLogger(__name__)

# Staleness threshold in days (must match registry config)
LABEL_STALE_THRESHOLD_DAYS = 180


class StabilityClassifier:
    """
    Evaluates whether a VASP attribution conclusion is stable across
    the accepted allocation models.

    Input: per-model attributed values for each candidate VASP address.
    Output: EndpointStability + reasons.
    """

    def classify(
        self,
        vasp_model_attributions: dict[str, dict[AllocationModel, Decimal]],
        victim_value: Decimal,
        bridge_match_strength: Optional[BridgeMatchStrength],
        label_confidence: AttributionConfidence,
        label_age_days: int,
    ) -> tuple[str, EndpointStability, str]:
        """
        vasp_model_attributions: {vasp_entity_name: {model: attributed_value}}
        Returns: (dominant_vasp, stability, reason)
        """
        if not vasp_model_attributions:
            return (
                "NONE",
                EndpointStability.UNRESOLVED,
                "No VASP candidates reached during traversal.",
            )

        # Find dominant VASP per model
        dominant_by_model: dict[AllocationModel, str] = {}
        for model in AllocationModel:
            best_vasp = max(
                vasp_model_attributions.items(),
                key=lambda kv: kv[1].get(model, Decimal(0)),
            )
            dominant_by_model[model] = best_vasp[0]

        unique_dominants = set(dominant_by_model.values())

        # Check if the same VASP dominates across all models
        if len(unique_dominants) == 1:
            dominant = list(unique_dominants)[0]
            stability = self._refine_stability(
                dominant, vasp_model_attributions[dominant], victim_value,
                bridge_match_strength, label_confidence, label_age_days,
            )
            return (dominant, stability.stability, stability.reason)

        # Multiple VASPs dominate under different models — unstable
        model_disagreement = {
            m.value: v for m, v in dominant_by_model.items()
        }
        reason = (
            f"Dominant endpoint changes across models: {model_disagreement}. "
            "Investigator interpretation required."
        )
        return ("UNSTABLE", EndpointStability.LOW, reason)

    def _refine_stability(
        self,
        vasp: str,
        model_values: dict[AllocationModel, Decimal],
        victim_value: Decimal,
        bridge_match_strength: Optional[BridgeMatchStrength],
        label_confidence: AttributionConfidence,
        label_age_days: int,
    ) -> "_StabilityAssessment":
        """
        Once we have a consistent dominant VASP, assess the quality of that result.
        Each dimension can degrade the overall stability.
        """
        reasons: list[str] = [f"VASP '{vasp}' is dominant under all 4 allocation models."]
        degradations: list[str] = []

        # Value interval width — narrow interval is more stable
        values = list(model_values.values())
        if victim_value > Decimal(0):
            spread_pct = (max(values) - min(values)) / victim_value * 100
        else:
            spread_pct = Decimal(0)
        if spread_pct > 50:
            degradations.append(
                f"Model attribution spread is {float(spread_pct):.0f}% of victim value — wide interval."
            )
        elif spread_pct > 20:
            reasons.append(f"Attribution spread: {float(spread_pct):.0f}% of victim value (moderate).")
        else:
            reasons.append(f"Attribution spread: {float(spread_pct):.0f}% of victim value (narrow).")

        # Bridge match quality
        if bridge_match_strength is not None:
            if bridge_match_strength == BridgeMatchStrength.WEAK:
                degradations.append(
                    "Cross-chain link is WEAK (amount+timing only). "
                    "Bridge association is heuristic, not deterministic."
                )
            elif bridge_match_strength == BridgeMatchStrength.MODERATE:
                reasons.append("Cross-chain link: MODERATE confidence.")
            elif bridge_match_strength == BridgeMatchStrength.STRONG:
                reasons.append("Cross-chain link: STRONG (deterministic protocol match).")

        # Label quality
        if label_confidence == AttributionConfidence.STALE or label_age_days > LABEL_STALE_THRESHOLD_DAYS:
            degradations.append(
                f"VASP attribution label is {label_age_days} days old — STALE. "
                "Verify with current intelligence before taking action."
            )
        elif label_confidence == AttributionConfidence.DISPUTED:
            degradations.append("VASP attribution label is DISPUTED across intelligence sources.")
        elif label_confidence is not None:
            reasons.append(f"Label confidence: {label_confidence.value}.")

        # Compute overall stability
        if not degradations:
            return _StabilityAssessment(EndpointStability.HIGH, " ".join(reasons))
        if len(degradations) == 1 and bridge_match_strength not in (BridgeMatchStrength.WEAK, None):
            combined = " ".join(reasons) + " Degradation: " + degradations[0]
            return _StabilityAssessment(EndpointStability.MEDIUM, combined)
        combined = " ".join(reasons) + " Degradations: " + "; ".join(degradations)
        return _StabilityAssessment(EndpointStability.LOW, combined)


class _StabilityAssessment:
    def __init__(self, stability: EndpointStability, reason: str):
        self.stability = stability
        self.reason = reason


def compute_actionability(
    stability: EndpointStability,
    dominant_vasp: str,
    label_confidence: AttributionConfidence,
    label_age_days: int,
    min_value_interval: ValueInterval,
    victim_value: Decimal,
    has_supported_path: bool,
) -> ActionabilityState:
    """
    Actionability state depends on evidence quality, not just VASP identification.
    An investigator should see this state as a guide, not a decision.
    """
    if dominant_vasp in ("NONE", "UNSTABLE") or not has_supported_path:
        return ActionabilityState.NO_ACTIONABLE_ENDPOINT

    # Minimum value fraction to consider actionable
    min_fraction = min_value_interval.lower_bound / victim_value if victim_value > 0 else Decimal(0)

    if label_confidence == AttributionConfidence.STALE or label_age_days > LABEL_STALE_THRESHOLD_DAYS:
        return ActionabilityState.STALE_EXPOSURE

    if not has_supported_path:
        return ActionabilityState.CANDIDATE_VASP

    if stability == EndpointStability.HIGH and min_fraction > Decimal("0.1"):
        return ActionabilityState.RECENT_SUPPORTED_CUSTODIAL_EXPOSURE

    if stability in (EndpointStability.HIGH, EndpointStability.MEDIUM):
        return ActionabilityState.SUPPORTED_VASP

    return ActionabilityState.CANDIDATE_VASP
