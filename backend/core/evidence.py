"""
Evidence provenance system.

Every material claim in the investigation must be traceable to its source,
its evidence class, and its assumptions. This module enforces that discipline.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import datetime
import hashlib
import json

from .models import (
    EvidenceClass, AllocationModel, Chain, Asset, AnchorLevel,
    BridgeMatchStrength, AttributionSource, AttributionConfidence, utc_now
)


SOFTWARE_VERSION = "0.2.0-sprint"


# ---------------------------------------------------------------------------
# Evidence record — the atomic unit of forensic evidence
# ---------------------------------------------------------------------------

@dataclass
class EvidenceRecord:
    """
    One unit of evidence supporting an investigation claim.
    Stored with everything needed for later reproduction.
    """
    record_id: str
    evidence_class: EvidenceClass
    chain: Optional[Chain]
    tx_hash: Optional[str]
    block_number: Optional[int]
    block_timestamp: Optional[datetime.datetime]
    address: Optional[str]
    data_source: str              # API endpoint, dataset name, or 'complaint'
    source_timestamp: datetime.datetime
    raw_data_hash: Optional[str]  # SHA-256 of the raw fetched payload
    description: str
    assumptions: list[str] = field(default_factory=list)
    analyst_note: Optional[str] = None

    def to_reproducibility_dict(self) -> dict:
        """Subset of fields required to reproduce this evidence record."""
        return {
            "record_id": self.record_id,
            "evidence_class": self.evidence_class.value,
            "chain": self.chain.value if self.chain else None,
            "tx_hash": self.tx_hash,
            "block_number": self.block_number,
            "data_source": self.data_source,
            "source_timestamp": self.source_timestamp.isoformat(),
            "raw_data_hash": self.raw_data_hash,
            "software_version": SOFTWARE_VERSION,
        }


def hash_payload(payload: dict | str | bytes) -> str:
    """SHA-256 of raw fetched API payload for evidence reproducibility."""
    if isinstance(payload, dict):
        raw = json.dumps(payload, sort_keys=True).encode()
    elif isinstance(payload, str):
        raw = payload.encode()
    else:
        raw = payload
    return hashlib.sha256(raw).hexdigest()


def make_record_id(prefix: str, tx_hash: Optional[str], address: Optional[str]) -> str:
    """Deterministic record ID so duplicate evidence records can be detected."""
    components = [prefix, tx_hash or "", address or ""]
    raw = "|".join(components).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Claim builder — structured wrapper for claim records
# ---------------------------------------------------------------------------

class ClaimBuilder:
    """
    Builds a ClaimRecord with all required fields.
    Callers must supply all mandatory fields; no silent defaults.
    """

    def __init__(
        self,
        claim_text: str,
        evidence_class: EvidenceClass,
        algorithm_or_model: str,
    ):
        self.claim_text = claim_text
        self.evidence_class = evidence_class
        self.algorithm_or_model = algorithm_or_model
        self.supporting_observations: list[str] = []
        self.data_source: str = ""
        self.source_timestamp: Optional[datetime.datetime] = None
        self.assumptions: list[str] = []
        self.confidence: str = "UNRESOLVED"
        self.alternative_explanation: Optional[str] = None
        self.conflicting_evidence: Optional[str] = None
        self.analyst_override: Optional[str] = None

    def observe(self, observation: str) -> "ClaimBuilder":
        self.supporting_observations.append(observation)
        return self

    def from_source(self, source: str, timestamp: Optional[datetime.datetime] = None) -> "ClaimBuilder":
        self.data_source = source
        self.source_timestamp = timestamp
        return self

    def assuming(self, assumption: str) -> "ClaimBuilder":
        self.assumptions.append(assumption)
        return self

    def with_confidence(self, confidence: str) -> "ClaimBuilder":
        assert confidence in ("HIGH", "MEDIUM", "LOW", "UNRESOLVED"), \
            f"Use qualitative tier, not numeric: {confidence}"
        self.confidence = confidence
        return self

    def alternative(self, explanation: str) -> "ClaimBuilder":
        self.alternative_explanation = explanation
        return self

    def conflicting(self, evidence: str) -> "ClaimBuilder":
        self.conflicting_evidence = evidence
        return self

    def build(self) -> "ClaimRecord":
        from .models import ClaimRecord  # avoid circular at module level
        if not self.data_source:
            raise ValueError("ClaimRecord requires a data_source")
        return ClaimRecord(
            claim_text=self.claim_text,
            evidence_class=self.evidence_class,
            supporting_observations=self.supporting_observations,
            data_source=self.data_source,
            source_timestamp=self.source_timestamp,
            effective_date=utc_now(),
            algorithm_or_model=self.algorithm_or_model,
            assumptions=self.assumptions,
            confidence=self.confidence,
            alternative_explanation=self.alternative_explanation,
            conflicting_evidence=self.conflicting_evidence,
            analyst_override=self.analyst_override,
            software_version=SOFTWARE_VERSION,
        )


# ---------------------------------------------------------------------------
# Provenance store — per-case evidence accumulation
# ---------------------------------------------------------------------------

class ProvenanceStore:
    """
    Accumulates all evidence records and claims for a single case.
    Produces a reproducibility manifest on demand.
    """

    def __init__(self, case_id: str):
        self.case_id = case_id
        self._records: list[EvidenceRecord] = []
        self._claims: list = []  # ClaimRecord instances, typed loosely to avoid circular
        self._block_heights: dict[str, int] = {}   # chain → highest block seen
        self._adapter_versions: dict[str, str] = {}  # chain → adapter version

    def add_record(self, record: EvidenceRecord) -> None:
        self._records.append(record)

    def add_claim(self, claim) -> None:
        self._claims.append(claim)

    def record_block_height(self, chain: Chain, height: int) -> None:
        key = chain.value
        existing = self._block_heights.get(key, 0)
        if height > existing:
            self._block_heights[key] = height

    def record_adapter_version(self, chain: Chain, version: str) -> None:
        self._adapter_versions[chain.value] = version

    def reproducibility_manifest(self) -> dict:
        """
        Everything needed for a later analyst to understand
        what state the system was in when it produced this investigation.
        """
        return {
            "case_id": self.case_id,
            "manifest_generated_at": utc_now().isoformat(),
            "software_version": SOFTWARE_VERSION,
            "block_heights_at_analysis": self._block_heights,
            "chain_adapter_versions": self._adapter_versions,
            "evidence_record_count": len(self._records),
            "claim_count": len(self._claims),
            "evidence_hashes": [
                r.raw_data_hash for r in self._records if r.raw_data_hash
            ],
            "evidence_records": [r.to_reproducibility_dict() for r in self._records],
        }

    def all_claims(self) -> list:
        return list(self._claims)

    def all_records(self) -> list[EvidenceRecord]:
        return list(self._records)
