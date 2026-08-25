"""
Case Similarity Engine.

Computes normalized Euclidean distance across topological feature vectors.
Pure Python, transparent, and defensible.
"""

from __future__ import annotations
import math
from typing import Any

from .features import GraphFeatureVector, extract_features
from ..core.models import InvestigationCase


# Normalization bounds for 8 features: (hop, branching, peeling, bridge, dex, fanout, duration, entropy)
_FEATURE_BOUNDS = [
    (0.0, 10.0),    # hops
    (0.0, 50.0),    # branching factor
    (0.0, 1.0),     # peeling ratio
    (0.0, 5.0),     # bridges
    (0.0, 5.0),     # dex swaps
    (0.0, 250.0),   # fanout max
    (0.0, 86400.0), # duration seconds (up to 24h)
    (0.0, 10.0),    # entropy
]


def _normalize_vector(vec: list[float]) -> list[float]:
    norm = []
    for i, val in enumerate(vec):
        min_v, max_v = _FEATURE_BOUNDS[i]
        clamped = max(min_v, min(max_v, val))
        denom = max_v - min_v
        norm.append((clamped - min_v) / denom if denom > 0 else 0.0)
    return norm


def compute_vector_distance(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute normalized Euclidean distance in range [0.0, 1.0]."""
    norm_a = _normalize_vector(vec_a)
    norm_b = _normalize_vector(vec_b)

    sq_sum = sum((a - b) ** 2 for a, b in zip(norm_a, norm_b))
    # Normalized by max possible Euclidean distance sqrt(8)
    return math.sqrt(sq_sum) / math.sqrt(len(norm_a))


class CaseSimilarityEngine:

    def __init__(self, historical_corpus: list[dict]):
        """
        historical_corpus: list of dicts with keys 'case_id', 'description', 'features' (list of 8 floats)
        """
        self._corpus = historical_corpus

    def find_similar_cases(
        self, current_features: GraphFeatureVector, top_k: int = 3
    ) -> dict[str, Any]:
        """
        Find closest historical cases by topological distance.
        If fewer than 3 historical cases exist, returns INSUFFICIENT_DATA status.
        """
        if len(self._corpus) < 3:
            return {
                "status": "INSUFFICIENT_DATA",
                "message": f"Insufficient historical corpus ({len(self._corpus)} cases available; minimum 3 required for defensible similarity ranking).",
                "matches": [],
            }

        target_vec = current_features.to_list()
        scored = []

        for item in self._corpus:
            hist_vec = item.get("features", [])
            if len(hist_vec) != 8:
                continue
            dist = compute_vector_distance(target_vec, hist_vec)
            # Similarity score: 1.0 - distance
            similarity = round(max(0.0, 1.0 - dist), 3)
            scored.append({
                "case_id": item.get("case_id", "HIST-CASE"),
                "scenario_name": item.get("scenario_name", "Historical Trace"),
                "similarity_score": similarity,
                "distance": round(dist, 3),
                "pattern_type": item.get("pattern_type", "Standard"),
                "shared_structural_notes": item.get("description", ""),
            })

        scored.sort(key=lambda x: x["similarity_score"], reverse=True)
        return {
            "status": "COMPUTED",
            "corpus_size": len(self._corpus),
            "matches": scored[:top_k],
        }
