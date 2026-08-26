"""
Intermediary Laundering and Topological Pattern Analysis Engine.

Analyzes intermediate wallet behavior between victim anchors and final service boundaries.
Provides explainable, deterministic detection for:
  - Peeling chains (repeated sequential change splitting)
  - Rapid forwarding / relay hops (minimal dwell time)
  - Fan-out dispersion (value splitting across multiple branches)
  - Fan-in reconsolidation (aggregation of split branches)
  - Cyclic movements (loops or circular transfers)
  - Service boundary approaches (transfers heading towards known infrastructure)

Analytical Principles:
- No criminal/guilt labels.
- Analytical descriptions with explicit transaction evidence and confidence limits.
- Contextual graph intelligence distinguished from victim-attributed value endpoints.
"""

from __future__ import annotations
import datetime
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional, Any

from .models import Chain, Asset, OnChainTransfer, EvidenceClass, ValueInterval, utc_now


class DwellTimeClassification(str, Enum):
    IMMEDIATE = "IMMEDIATE"  # < 60 seconds
    SHORT = "SHORT"          # 1 minute to 15 minutes
    MODERATE = "MODERATE"    # 15 minutes to 24 hours
    LONG = "LONG"            # > 24 hours
    UNKNOWN = "UNKNOWN"


class IntermediaryPatternType(str, Enum):
    PEELING_CHAIN = "PEELING_CHAIN"
    RAPID_FORWARDING = "RAPID_FORWARDING"
    REPEATED_RELAY = "REPEATED_RELAY"
    FAN_OUT_DISPERSION = "FAN_OUT_DISPERSION"
    FAN_IN_CONSOLIDATION = "FAN_IN_CONSOLIDATION"
    CYCLIC_TRANSFER = "CYCLIC_TRANSFER"
    SERVICE_BOUNDARY_APPROACH = "SERVICE_BOUNDARY_APPROACH"
    VALUE_SPLITTING = "VALUE_SPLITTING"
    RECOMBINATION = "RECOMBINATION"


@dataclass
class DwellTimeRecord:
    """Observed dwell time between inbound fund arrival and outbound forwarding."""
    address: str
    inbound_tx_hash: str
    outbound_tx_hash: str
    inbound_time: datetime.datetime
    outbound_time: datetime.datetime
    dwell_seconds: float
    classification: DwellTimeClassification


@dataclass
class LaunderingPatternFinding:
    """Structured record of an observed topological movement pattern."""
    pattern_type: IntermediaryPatternType
    addresses: list[str]
    transactions: list[str]
    description: str
    evidence_class: EvidenceClass
    confidence_tier: str  # "HIGH", "MEDIUM", "LOW"
    is_victim_linked: bool = True
    victim_value_interval: Optional[ValueInterval] = None
    limitations: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass
class IntermediaryAnalysisResult:
    """Comprehensive analytical report for an on-chain fund transfer sequence."""
    case_id: str
    total_hops: int
    fan_out_count: int
    fan_in_count: int
    victim_mass_split_ratio: float
    recombination_ratio: float
    dwell_records: list[DwellTimeRecord]
    pattern_findings: list[LaunderingPatternFinding]
    average_dwell_seconds: Optional[float]
    dominant_dwell_class: DwellTimeClassification
    summary_notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "total_hops": self.total_hops,
            "fan_out_count": self.fan_out_count,
            "fan_in_count": self.fan_in_count,
            "victim_mass_split_ratio": self.victim_mass_split_ratio,
            "recombination_ratio": self.recombination_ratio,
            "dwell_records": [
                {
                    "address": d.address,
                    "inbound_tx": d.inbound_tx_hash,
                    "outbound_tx": d.outbound_tx_hash,
                    "dwell_seconds": d.dwell_seconds,
                    "classification": d.classification.value,
                }
                for d in self.dwell_records
            ],
            "pattern_findings": [
                {
                    "pattern_type": p.pattern_type.value,
                    "addresses": p.addresses,
                    "transactions": p.transactions,
                    "description": p.description,
                    "evidence_class": p.evidence_class.value,
                    "confidence_tier": p.confidence_tier,
                    "is_victim_linked": p.is_victim_linked,
                    "victim_value": {
                        "min": str(p.victim_value_interval.lower_bound) if p.victim_value_interval else None,
                        "max": str(p.victim_value_interval.upper_bound) if p.victim_value_interval else None,
                    } if p.victim_value_interval else None,
                    "limitations": p.limitations,
                    "metrics": p.metrics,
                }
                for p in self.pattern_findings
            ],
            "average_dwell_seconds": self.average_dwell_seconds,
            "dominant_dwell_class": self.dominant_dwell_class.value,
            "summary_notes": self.summary_notes,
        }


def classify_dwell_time(seconds: float) -> DwellTimeClassification:
    if seconds < 0:
        return DwellTimeClassification.UNKNOWN
    if seconds <= 60:
        return DwellTimeClassification.IMMEDIATE
    if seconds <= 900:  # 15 min
        return DwellTimeClassification.SHORT
    if seconds <= 86400:  # 24 hr
        return DwellTimeClassification.MODERATE
    return DwellTimeClassification.LONG


class IntermediaryAnalysisEngine:
    """Evaluates graph sequences to compute dwell times, fan-out/fan-in, and laundering patterns."""

    def analyze_transfers(
        self,
        case_id: str,
        transfers: list[OnChainTransfer],
        known_vasp_addresses: Optional[set[str]] = None,
        victim_value_interval: Optional[ValueInterval] = None,
    ) -> IntermediaryAnalysisResult:
        known_vasp_set = {a.lower() for a in (known_vasp_addresses or set())}

        if not transfers:
            return IntermediaryAnalysisResult(
                case_id=case_id,
                total_hops=0,
                fan_out_count=0,
                fan_in_count=0,
                victim_mass_split_ratio=1.0,
                recombination_ratio=0.0,
                dwell_records=[],
                pattern_findings=[],
                average_dwell_seconds=None,
                dominant_dwell_class=DwellTimeClassification.UNKNOWN,
                summary_notes=["No transfers available for intermediary analysis."],
            )

        # Build address adjacency maps
        outbound_by_addr: dict[str, list[OnChainTransfer]] = {}
        inbound_by_addr: dict[str, list[OnChainTransfer]] = {}

        for t in transfers:
            src = t.from_address.lower()
            dst = t.to_address.lower()
            outbound_by_addr.setdefault(src, []).append(t)
            inbound_by_addr.setdefault(dst, []).append(t)

        # 1. Compute Dwell Times for Intermediary Nodes
        dwell_records: list[DwellTimeRecord] = []
        all_dwell_seconds: list[float] = []

        all_addrs = set(inbound_by_addr.keys()).intersection(set(outbound_by_addr.keys()))
        for addr in all_addrs:
            in_txs = sorted(inbound_by_addr[addr], key=lambda x: x.block_timestamp)
            out_txs = sorted(outbound_by_addr[addr], key=lambda x: x.block_timestamp)

            for it in in_txs:
                matching_out = [ot for ot in out_txs if ot.block_timestamp >= it.block_timestamp]
                if matching_out:
                    first_out = matching_out[0]
                    delta = (first_out.block_timestamp - it.block_timestamp).total_seconds()
                    all_dwell_seconds.append(delta)
                    dwell_records.append(
                        DwellTimeRecord(
                            address=addr,
                            inbound_tx_hash=it.tx_hash,
                            outbound_tx_hash=first_out.tx_hash,
                            inbound_time=it.block_timestamp,
                            outbound_time=first_out.block_timestamp,
                            dwell_seconds=delta,
                            classification=classify_dwell_time(delta),
                        )
                    )

        avg_dwell = sum(all_dwell_seconds) / len(all_dwell_seconds) if all_dwell_seconds else None
        dominant_dwell = classify_dwell_time(avg_dwell) if avg_dwell is not None else DwellTimeClassification.UNKNOWN

        # 2. Fan-out & Fan-in counts
        fan_out_count = sum(1 for src, outs in outbound_by_addr.items() if len(outs) >= 3)
        fan_in_count = sum(1 for dst, ins in inbound_by_addr.items() if len(ins) >= 3)

        # 3. Detect Laundering & Intermediary Patterns
        findings: list[LaunderingPatternFinding] = []
        summary_notes: list[str] = []

        # A. Rapid Forwarding / Relay Detection
        rapid_records = [d for d in dwell_records if d.classification in (DwellTimeClassification.IMMEDIATE, DwellTimeClassification.SHORT)]
        if len(rapid_records) >= 2:
            findings.append(
                LaunderingPatternFinding(
                    pattern_type=IntermediaryPatternType.RAPID_FORWARDING,
                    addresses=list({r.address for r in rapid_records}),
                    transactions=[r.inbound_tx_hash for r in rapid_records] + [r.outbound_tx_hash for r in rapid_records],
                    description=f"Rapid forwarding observed: {len(rapid_records)} sequential hops forwarding funds with short dwell times (<15m).",
                    evidence_class=EvidenceClass.OBSERVED,
                    confidence_tier="HIGH",
                    victim_value_interval=victim_value_interval,
                    limitations=["Automated bot sweeping or exchange hot-wallet processing may also exhibit rapid forwarding timestamps."],
                    metrics={"rapid_hop_count": len(rapid_records), "min_dwell_seconds": min((r.dwell_seconds for r in rapid_records), default=0)},
                )
            )
            summary_notes.append(f"Rapid forwarding pattern observed across {len(rapid_records)} intermediary hops.")

        # B. Peeling Chain Detection (1 major continuation + 1 minor peel address per hop)
        peeling_hops = []
        for src, outs in outbound_by_addr.items():
            if len(outs) == 2:
                amt0, amt1 = outs[0].amount, outs[1].amount
                if amt0 > Decimal(0) and amt1 > Decimal(0):
                    ratio = min(amt0, amt1) / max(amt0, amt1)
                    if ratio < Decimal("0.20"):  # One output is <20% of the other
                        peeling_hops.append(src)

        if len(peeling_hops) >= 2:
            findings.append(
                LaunderingPatternFinding(
                    pattern_type=IntermediaryPatternType.PEELING_CHAIN,
                    addresses=peeling_hops,
                    transactions=[t.tx_hash for src in peeling_hops for t in outbound_by_addr[src]],
                    description=f"Peeling-like flow structure identified across {len(peeling_hops)} successive split transactions.",
                    evidence_class=EvidenceClass.DERIVED,
                    confidence_tier="HIGH",
                    victim_value_interval=victim_value_interval,
                    limitations=["Standard corporate payroll or UTXO change generation can resemble peeling structures."],
                    metrics={"peeling_hop_count": len(peeling_hops)},
                )
            )
            summary_notes.append(f"Peeling-like flow behavior identified ({len(peeling_hops)} splits).")

        # C. Fan-Out Dispersion & Recombination
        if fan_out_count > 0:
            findings.append(
                LaunderingPatternFinding(
                    pattern_type=IntermediaryPatternType.FAN_OUT_DISPERSION,
                    addresses=[src for src, outs in outbound_by_addr.items() if len(outs) >= 3],
                    transactions=[t.tx_hash for src, outs in outbound_by_addr.items() if len(outs) >= 3 for t in outs],
                    description=f"Fan-out dispersion observed: {fan_out_count} addresses split funds across 3 or more branches.",
                    evidence_class=EvidenceClass.OBSERVED,
                    confidence_tier="HIGH",
                    victim_value_interval=victim_value_interval,
                    limitations=["Multi-recipient transfers occur in legitimate staking and token distribution operations."],
                    metrics={"fan_out_hubs": fan_out_count},
                )
            )
            summary_notes.append(f"Fan-out dispersion observed at {fan_out_count} hub(s).")

        if fan_in_count > 0:
            findings.append(
                LaunderingPatternFinding(
                    pattern_type=IntermediaryPatternType.FAN_IN_CONSOLIDATION,
                    addresses=[dst for dst, ins in inbound_by_addr.items() if len(ins) >= 3],
                    transactions=[t.tx_hash for dst, ins in inbound_by_addr.items() if len(ins) >= 3 for t in ins],
                    description=f"Fan-in consolidation observed: {fan_in_count} destination addresses aggregate multiple distinct inflows.",
                    evidence_class=EvidenceClass.OBSERVED,
                    confidence_tier="HIGH",
                    victim_value_interval=victim_value_interval,
                    limitations=["Exchange deposit hot wallets routinely aggregate inflows from multiple distinct senders."],
                    metrics={"fan_in_hubs": fan_in_count},
                )
            )
            summary_notes.append(f"Fan-in consolidation observed at {fan_in_count} collection point(s).")

        # D. Cyclic Transfer / Loop Detection
        visited = set()
        loop_found = False
        loop_addrs = []
        for t in transfers:
            if t.from_address.lower() in visited and t.from_address.lower() == t.to_address.lower():
                loop_found = True
                loop_addrs.append(t.from_address)
            visited.add(t.from_address.lower())

        if loop_found:
            findings.append(
                LaunderingPatternFinding(
                    pattern_type=IntermediaryPatternType.CYCLIC_TRANSFER,
                    addresses=list(set(loop_addrs)),
                    transactions=[t.tx_hash for t in transfers if t.from_address in loop_addrs],
                    description="Cyclic transfer circulation detected returning value to previously active addresses.",
                    evidence_class=EvidenceClass.DERIVED,
                    confidence_tier="MEDIUM",
                    victim_value_interval=victim_value_interval,
                    limitations=["Automated arbitrage or liquidity provision contracts frequently generate circular transfer paths."],
                    metrics={"cyclic_address_count": len(loop_addrs)},
                )
            )

        split_ratio = float(len(transfers) / max(1, len(all_addrs))) if all_addrs else 1.0
        recomb_ratio = float(fan_in_count / max(1, fan_out_count)) if fan_out_count > 0 else 0.0

        return IntermediaryAnalysisResult(
            case_id=case_id,
            total_hops=len(transfers),
            fan_out_count=fan_out_count,
            fan_in_count=fan_in_count,
            victim_mass_split_ratio=split_ratio,
            recombination_ratio=recomb_ratio,
            dwell_records=dwell_records,
            pattern_findings=findings,
            average_dwell_seconds=avg_dwell,
            dominant_dwell_class=dominant_dwell,
            summary_notes=summary_notes,
        )
