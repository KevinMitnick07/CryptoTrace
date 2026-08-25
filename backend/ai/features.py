"""
Topological Graph Feature Extraction.

Extracts normalized structural and temporal metrics from an investigation graph.
Features are deterministic mathematical properties of the trace.
"""

from __future__ import annotations
import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from ..core.models import InvestigationCase


@dataclass(frozen=True)
class GraphFeatureVector:
    """Standardized 8-dimensional topological feature vector."""
    hop_count: int
    branching_factor: float
    peeling_ratio: float
    bridge_count: int
    dex_count: int
    fanout_max: int
    duration_seconds: float
    entropy: float

    def to_list(self) -> list[float]:
        return [
            float(self.hop_count),
            float(self.branching_factor),
            float(self.peeling_ratio),
            float(self.bridge_count),
            float(self.dex_count),
            float(self.fanout_max),
            float(self.duration_seconds),
            float(self.entropy),
        ]


def extract_features(case: InvestigationCase) -> GraphFeatureVector:
    """Extract topological feature vector from an InvestigationCase."""
    hops = len(case.path_segments)
    branches = len(case.branch_audit)
    branching_factor = (branches / hops) if hops > 0 else 0.0

    peeling_hops = 0
    bridges = 0
    dex_swaps = 0
    from_counts: dict[str, int] = {}
    timestamps = []
    amounts: list[float] = []

    for seg in case.path_segments:
        if seg.bridge_event:
            bridges += 1
        if seg.transformation:
            dex_swaps += 1
        if seg.transfer:
            from_addr = seg.transfer.from_address
            from_counts[from_addr] = from_counts.get(from_addr, 0) + 1
            if seg.transfer.block_timestamp:
                timestamps.append(seg.transfer.block_timestamp.timestamp())
            amounts.append(float(seg.transfer.amount))

    peeling_ratio = (hops / max(1, branches)) if hops > 0 else 0.0
    fanout_max = max(from_counts.values()) if from_counts else 0

    duration_seconds = 0.0
    if len(timestamps) >= 2:
        duration_seconds = max(0.0, max(timestamps) - min(timestamps))

    # Calculate Shannon Entropy of outgoing transfer amounts
    entropy = 0.0
    total_amount = sum(amounts)
    if total_amount > 0 and len(amounts) > 1:
        for a in amounts:
            if a > 0:
                p = a / total_amount
                entropy -= p * math.log2(p)

    return GraphFeatureVector(
        hop_count=hops,
        branching_factor=round(branching_factor, 3),
        peeling_ratio=round(peeling_ratio, 3),
        bridge_count=bridges,
        dex_count=dex_swaps,
        fanout_max=fanout_max,
        duration_seconds=round(duration_seconds, 1),
        entropy=round(entropy, 3),
    )
