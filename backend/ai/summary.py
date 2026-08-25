"""
Template-First Investigator Narrative Generator.

Builds structured, factual natural language investigative briefings from domain objects.
Guarantees zero hallucination because all text is templated directly from verified facts.
"""

from __future__ import annotations
from typing import Optional

from .features import GraphFeatureVector
from .patterns import PatternClassification
from ..core.models import InvestigationCase


def generate_investigator_narrative(
    case: InvestigationCase,
    features: GraphFeatureVector,
    patterns: list[PatternClassification],
) -> str:
    """Generate structured narrative briefing for law enforcement analysts."""
    lines = []

    # 1. Executive Summary
    wallet = case.complaint.reported_wallet
    chain = case.complaint.reported_chain.value if case.complaint.reported_chain else "UNKNOWN"
    amount = f"{case.complaint.reported_amount} {case.complaint.reported_asset.value if case.complaint.reported_asset else ''}" if case.complaint.reported_amount else "unspecified amount"

    lines.append(f"### Investigative Briefing — Case {case.case_id}")
    lines.append(
        f"Victim complaint `{case.complaint.complaint_ref}` reported a loss of {amount} on {chain} from wallet `{wallet}`. "
        f"Anchor assessment confirmed status **{case.anchor.status.value if case.anchor else 'UNVERIFIED'}** at Evidence Level **{case.anchor.level.value if case.anchor else 'D'}**."
    )

    # 2. Movement & Topological Summary
    lines.append(
        f"Forensic tracing traversed {features.hop_count} hops across {features.branching_factor:.1f} avg branching factor. "
        f"Overall trace completeness is **{case.trace_completeness_pct}%**, with case state **{case.state.value}**."
    )

    # 3. Actionability & VASP Conclusions
    if case.primary_stable_vasp:
        v = case.primary_stable_vasp
        lines.append(
            f"**Actionable Endpoint:** Victim funds reached custodial VASP **{v.record.entity_name}** (`{v.address_in_path}`) at hop {v.hop_from_anchor}. "
            f"Endpoint stability is rated **{v.endpoint_stability.value}** with attributed value interval **[{v.victim_value_interval.lower_bound}, {v.victim_value_interval.upper_bound}]**. "
            f"Status is {v.actionability.value}."
        )
    else:
        lines.append(
            f"**Actionable Endpoint:** No stable custodial VASP has been identified at the current trace depth. "
            f"Traceability state is **{case.traceability.value}**."
        )

    # 4. Advisory Typology Observations
    if patterns:
        lines.append("\n**Observed Typology Patterns (Advisory):**")
        for p in patterns:
            lines.append(f"- **{p.pattern_name}** ({p.confidence} confidence): {p.investigative_advice}")

    return "\n\n".join(lines)
