"""
Advisory Pattern Classifier.

Deterministic, rule-based laundering topology classifier.
Classifies topologies and produces explainable advisory suggestions for investigators.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from .features import GraphFeatureVector
from ..core.models import InvestigationCase, TraceabilityState


@dataclass
class PatternClassification:
    pattern_name: str
    confidence: str             # HIGH / MEDIUM / LOW
    evidence_indicators: list[str]
    investigative_advice: str
    is_advisory_only: bool = True


class AdvisoryPatternClassifier:

    @staticmethod
    def classify(case: InvestigationCase, features: GraphFeatureVector) -> list[PatternClassification]:
        """
        Classify investigation into zero or more recognizable laundering typologies.
        Strictly advisory.
        """
        patterns: list[PatternClassification] = []

        # 1. Mixer / Privacy Pool Obfuscation
        if case.traceability == TraceabilityState.OBFUSCATED or any("mixer" in b.reason.lower() for b in case.branch_audit):
            patterns.append(PatternClassification(
                pattern_name="MIXER_OBFUSCATION",
                confidence="HIGH",
                evidence_indicators=[
                    "Funds routed directly to recognized mixer contract / privacy pool",
                    "Traceability state transitioned to OBFUSCATED at mixer boundary",
                ],
                investigative_advice="Direct on-chain tracing terminates at mixer contract. Issue preservation requests for relayer IP logs or coordinate with off-chain intelligence sources.",
            ))

        # 2. High-Fragmentation Fan-Out Dispersal
        if features.fanout_max >= 15 or case.high_fragmentation_detected:
            patterns.append(PatternClassification(
                pattern_name="HIGH_FANOUT_DISPERSAL",
                confidence="HIGH",
                evidence_indicators=[
                    f"Maximum single-wallet fan-out is {features.fanout_max} branches",
                    "Significant portion of victim value split into sub-threshold micro-fractions",
                ],
                investigative_advice="High-fanout dispersal detected. Check deferred branches in audit log for convergence into common deposit wallets downstream.",
            ))

        # 3. Cross-Chain Bridge Transition
        if features.bridge_count >= 1:
            patterns.append(PatternClassification(
                pattern_name="CROSS_CHAIN_BRIDGE_HOP",
                confidence="HIGH",
                evidence_indicators=[
                    f"Observed {features.bridge_count} cross-chain bridge transition events",
                ],
                investigative_advice="Funds moved across blockchain layers. Verify protocol ticket/message ID for deterministic link on destination chain.",
            ))

        # 4. DEX Asset Transformation
        if features.dex_count >= 1:
            patterns.append(PatternClassification(
                pattern_name="DEX_ASSET_TRANSFORMATION",
                confidence="HIGH",
                evidence_indicators=[
                    f"Observed {features.dex_count} automated market maker swap events",
                ],
                investigative_advice="Asset denomination converted via DEX router. Monitor recipient wallet for converted token outflow or custodial deposit.",
            ))

        # 5. Peeling Chain
        if features.peeling_ratio >= 0.7 and features.hop_count >= 3:
            patterns.append(PatternClassification(
                pattern_name="PEELING_CHAIN_LAYERING",
                confidence="MEDIUM",
                evidence_indicators=[
                    f"Sequential chain of {features.hop_count} single-continuation hops (peeling ratio {features.peeling_ratio:.2f})",
                ],
                investigative_advice="Classic peeling chain pattern. Rapid intermediary transfers without significant splitting indicate automated layering to create synthetic hop distance.",
            ))

        # 6. Direct Custodial VASP Deposit
        if case.primary_stable_vasp and features.hop_count <= 2:
            patterns.append(PatternClassification(
                pattern_name="DIRECT_CUSTODIAL_DEPOSIT",
                confidence="HIGH",
                evidence_indicators=[
                    f"Victim value reached {case.primary_stable_vasp.record.entity_name} within {features.hop_count} hops",
                    f"VASP endpoint stability rated {case.primary_stable_vasp.endpoint_stability.value}",
                ],
                investigative_advice=f"Actionable custodial endpoint reached at {case.primary_stable_vasp.record.entity_name}. Expedited LEA preservation request (Section 91 CrPC / Subpoena) is defensible.",
            ))

        return patterns
