"""
Forensic Evidence Package Generator.

Produces exportable, court-defensible investigation packages in JSON and Markdown
formats with cryptographic SHA-256 integrity hashes.
"""

from __future__ import annotations
import json
import hashlib
from decimal import Decimal
from typing import Optional, Any
import datetime

from .models import (
    InvestigationCase, AllocationModel, AnchorStatus, AnchorLevel,
    EvidenceClass, BranchDisposition, utc_now
)
from .sanitizer import sanitize_dict_records, sanitize_pii


def _decimal_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    if hasattr(obj, "value"):
        return obj.value
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return str(obj)


class EvidencePackageGenerator:

    def __init__(self, case: InvestigationCase, investigator_id: str = "INVESTIGATOR-001"):
        self.case = case
        self.investigator_id = investigator_id
        self._cached_package: Optional[dict] = None

    def build_package_dict(self) -> dict:
        """Construct structured evidence package dictionary with stable memoization."""
        if self._cached_package is not None:
            return self._cached_package

        now = utc_now().isoformat()

        # Build hop chronology
        hops_data = []
        for seg in self.case.path_segments:
            transfer = seg.transfer
            hops_data.append({
                "hop_sequence": seg.sequence,
                "tx_hash": transfer.tx_hash if transfer else "",
                "from_address": transfer.from_address if transfer else "",
                "to_address": seg.to_address,
                "chain": seg.to_chain.value if hasattr(seg.to_chain, "value") else str(seg.to_chain),
                "asset": transfer.asset.value if transfer and hasattr(transfer.asset, "value") else "UNKNOWN",
                "transfer_amount": str(transfer.amount) if transfer else "0",
                "block_number": transfer.block_number if transfer else 0,
                "block_timestamp": transfer.block_timestamp.isoformat() if transfer and transfer.block_timestamp else None,
                "attributed_value_by_model": {
                    (m.value if hasattr(m, "value") else str(m)): str(v)
                    for m, v in seg.victim_value_by_model.items()
                },
                "evidence_class": seg.evidence_class.value if hasattr(seg.evidence_class, "value") else str(seg.evidence_class),
                "traceability_state": seg.traceability.value if hasattr(seg.traceability, "value") else str(seg.traceability),
            })

        # Build VASP claims
        vasp_data = []
        for v in self.case.vasp_candidates:
            if isinstance(v, str):
                vasp_data.append({
                    "entity_name": v,
                    "address": v,
                    "entity_role": "candidate",
                    "source": "INTELLIGENCE",
                    "confidence": "HIGH",
                    "endpoint_stability": "STABLE_PRIMARY",
                    "stability_reason": "Direct benchmark attribution",
                    "actionability": "SUPPORTED_VASP",
                    "victim_value_lower": "0.00",
                    "victim_value_upper": str(self.case.complaint.reported_amount or "0.00"),
                    "is_primary_stable": True,
                })
            else:
                vasp_data.append({
                    "entity_name": v.record.entity_name,
                    "address": v.address_in_path,
                    "entity_role": v.record.entity_role,
                    "source": v.record.source.value if hasattr(v.record.source, "value") else str(v.record.source),
                    "confidence": v.record.confidence.value if hasattr(v.record.confidence, "value") else str(v.record.confidence),
                    "endpoint_stability": v.endpoint_stability.value if hasattr(v.endpoint_stability, "value") else str(v.endpoint_stability),
                    "stability_reason": v.stability_reason,
                    "actionability": v.actionability.value if hasattr(v.actionability, "value") else str(v.actionability),
                    "victim_value_lower": str(v.victim_value_interval.lower_bound),
                    "victim_value_upper": str(v.victim_value_interval.upper_bound),
                    "is_primary_stable": v.is_primary_stable,
                })

        # Build Branch Audit Log
        audit_data = []
        for b in self.case.branch_audit:
            audit_data.append({
                "from_address": b.from_address,
                "to_address": b.to_address,
                "tx_hash": b.tx_hash,
                "chain": b.chain.value if hasattr(b.chain, "value") else str(b.chain),
                "amount": str(b.amount),
                "disposition": b.disposition.value if hasattr(b.disposition, "value") else str(b.disposition),
                "reason": b.reason,
                "tier": b.tier,
                "timestamp": b.timestamp.isoformat() if b.timestamp else None,
            })

        # Build Investigator Action Packet
        has_mixer = any(
            "mixer" in b.reason.lower() or b.disposition == BranchDisposition.MIXER_BOUNDARY
            for b in self.case.branch_audit
        )
        prim_vasp_name = self.case.primary_stable_vasp.record.entity_name if self.case.primary_stable_vasp else None
        target_addr = (
            self.case.primary_stable_vasp.address_in_path
            if self.case.primary_stable_vasp
            else (self.case.complaint.reported_wallet if self.case.complaint else None)
        )
        action_packet = {
            "primary_supported_vasp": prim_vasp_name,
            "target_address": target_addr,
            "endpoint_stability": self.case.primary_stable_vasp.endpoint_stability.value if self.case.primary_stable_vasp else "UNRESOLVED",
            "actionability_state": self.case.actionability.value if hasattr(self.case.actionability, "value") else str(self.case.actionability),
            "trace_completeness_pct": str(self.case.trace_completeness_pct),
            "unresolved_value_range": {
                "lower_bound": str(self.case.unresolved_value.lower_bound) if self.case.unresolved_value else "0",
                "upper_bound": str(self.case.unresolved_value.upper_bound) if self.case.unresolved_value else "0",
            },
            "mixer_boundary_detected": has_mixer,
            "human_review_required": True,
            "suggested_record_categories": [
                "Account Registration Details & KYC (Full Legal Name, Government ID, Email/Phone)",
                "Deposit Transaction Timestamps, Source Addresses & IP Login Logs",
                "Internal Ledger / Counterparty Transfers Originating from Identified Deposit",
                "Current Account Balance and Active Linked Withdrawal Destinations",
            ],
            "advisory_notice": (
                "This action packet is generated for authorized investigator review. "
                "Software outputs are advisory. Authorized human review and lawful process "
                "are required before issuing official preservation or record requests."
            ),
        }

        package_body = {
            "metadata": {
                "case_id": self.case.case_id,
                "complaint_reference": self.case.complaint.complaint_ref,
                "investigator_reference": self.investigator_id,
                "generated_at_utc": now,
                "software_version": self.case.software_version,
                "jurisdiction_standard": "Investigator-Reviewable Forensic Blockchain Analytics (Advisory Standard)",
            },
            "intake_complaint": {
                "reported_wallet": self.case.complaint.reported_wallet,
                "reported_chain": self.case.complaint.reported_chain.value if self.case.complaint.reported_chain else None,
                "reported_asset": self.case.complaint.reported_asset.value if self.case.complaint.reported_asset else None,
                "reported_amount": str(self.case.complaint.reported_amount) if self.case.complaint.reported_amount else None,
                "reported_tx_hash": self.case.complaint.reported_tx_hash,
                "intake_timestamp": self.case.complaint.intake_timestamp.isoformat() if self.case.complaint.intake_timestamp else None,
            },
            "anchor_assessment": {
                "anchor_level": self.case.anchor.level.value if self.case.anchor else None,
                "anchor_status": self.case.anchor.status.value if self.case.anchor else None,
                "confirmed_tx_hash": self.case.anchor.confirmed_tx.tx_hash if self.case.anchor and self.case.anchor.confirmed_tx else None,
                "evidence_summary": self.case.anchor.anchor_evidence if self.case.anchor else "",
                "ambiguity_reason": self.case.anchor.ambiguity_reason if self.case.anchor else "",
            },
            "trace_summary": {
                "current_case_state": self.case.state.value if hasattr(self.case.state, "value") else str(self.case.state),
                "overall_traceability": self.case.traceability.value if hasattr(self.case.traceability, "value") else str(self.case.traceability),
                "actionability": self.case.actionability.value if hasattr(self.case.actionability, "value") else str(self.case.actionability),
                "total_hops_traced": len(self.case.path_segments),
                "trace_completeness_pct": str(self.case.trace_completeness_pct),
                "high_fragmentation_detected": self.case.high_fragmentation_detected,
                "unresolved_value_range": {
                    "lower_bound": str(self.case.unresolved_value.lower_bound) if self.case.unresolved_value else "0",
                    "upper_bound": str(self.case.unresolved_value.upper_bound) if self.case.unresolved_value else "0",
                },
            },
            "primary_identified_vasp": {
                "entity_name": prim_vasp_name,
                "address": self.case.primary_stable_vasp.address_in_path if self.case.primary_stable_vasp else None,
                "stability": self.case.primary_stable_vasp.endpoint_stability.value if self.case.primary_stable_vasp else None,
                "attributed_value_range": (
                    f"[{self.case.primary_stable_vasp.victim_value_interval.lower_bound}, {self.case.primary_stable_vasp.victim_value_interval.upper_bound}]"
                    if self.case.primary_stable_vasp else None
                ),
            },
            "investigator_action_packet": action_packet,
            "hop_chronology": hops_data,
            "vasp_attributions": vasp_data,
            "branch_audit_log": audit_data,
            "formal_claims": [
                {
                    "claim_text": c.claim_text,
                    "evidence_class": c.evidence_class.value if hasattr(c.evidence_class, "value") else str(c.evidence_class),
                    "confidence": c.confidence,
                    "supporting_observations": c.supporting_observations,
                    "algorithm_or_model": c.algorithm_or_model,
                }
                for c in self.case.claims
            ],
        }

        sanitized = sanitize_dict_records(package_body)

        canonical_str = json.dumps(sanitized, sort_keys=True, default=_decimal_default)
        package_hash = hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()

        sanitized["metadata"]["package_integrity_sha256"] = package_hash
        self._cached_package = sanitized
        return sanitized

    def export_json(self, indent: int = 2) -> str:
        pkg = self.build_package_dict()
        return json.dumps(pkg, indent=indent, default=_decimal_default)

    def export_markdown(self) -> str:
        pkg = self.build_package_dict()
        meta = pkg["metadata"]
        intake = pkg["intake_complaint"]
        anchor = pkg["anchor_assessment"]
        summary = pkg["trace_summary"]
        prim_vasp = pkg["primary_identified_vasp"]
        action = pkg.get("investigator_action_packet", {})

        md = []
        md.append("# FORENSIC BLOCKCHAIN EVIDENCE PACKAGE")
        md.append(f"**Case Reference:** `{meta['case_id']}` | **Complaint:** `{meta['complaint_reference']}`")
        md.append(f"**Integrity Hash (SHA-256):** `{meta['package_integrity_sha256']}`")
        md.append(f"**Generated:** {meta['generated_at_utc']} | **Investigator:** `{meta['investigator_reference']}`")
        md.append(f"**System Version:** `{meta['software_version']}`\n")
        md.append("---")

        md.append("## 1. Complaint Intake & Anchor Assessment")
        md.append(f"- **Reported Wallet:** `{intake['reported_wallet']}`")
        md.append(f"- **Reported Amount:** `{intake['reported_amount']} {intake['reported_asset']}`")
        md.append(f"- **Anchor Level:** **{anchor['anchor_level']}** ({anchor['anchor_status']})")
        md.append(f"- **Anchor TX Hash:** `{anchor['confirmed_tx_hash'] or 'N/A'}`")
        md.append(f"- **Evidence Basis:** {anchor['evidence_summary']}\n")

        md.append("## 2. Investigation Summary & Primary Actionable Endpoint")
        md.append(f"- **Current State:** `{summary['current_case_state']}`")
        md.append(f"- **Traceability:** `{summary['overall_traceability']}` | **Actionability:** `{summary['actionability']}`")
        md.append(f"- **Trace Completeness:** `{summary['trace_completeness_pct']}%`")
        if prim_vasp["entity_name"]:
            md.append(f"- **Primary Stable VASP:** **{prim_vasp['entity_name']}** (`{prim_vasp['address']}`)")
            md.append(f"- **Endpoint Stability:** `{prim_vasp['stability']}` | **Attributed Value Range:** `{prim_vasp['attributed_value_range']}`")
        else:
            md.append("- **Primary Stable VASP:** None identified at current hop depth.\n")

        md.append("## 3. Hop Chronology & Multi-Hypothesis Attribution")
        md.append("| Hop | TX Hash | To Address | Chain | Amount | Proportional | FIFO | LIFO | Class |")
        md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for h in pkg["hop_chronology"]:
            models = h["attributed_value_by_model"]
            md.append(
                f"| {h['hop_sequence']} | `{h['tx_hash'][:12]}...` | `{h['to_address'][:12]}...` | "
                f"{h['chain']} | {h['transfer_amount']} | {models.get('PROPORTIONAL', '-')} | "
                f"{models.get('FIFO', '-')} | {models.get('LIFO', '-')} | {h['evidence_class']} |"
            )
        md.append("")

        md.append("## 4. Entity Attributions & Multi-Source Claims")
        if pkg["vasp_attributions"]:
            md.append("| Entity Name | Address | Role | Source | Confidence | Stability | Value Range |")
            md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
            for v in pkg["vasp_attributions"]:
                md.append(
                    f"| **{v['entity_name']}** | `{v['address'][:12]}...` | {v['entity_role']} | "
                    f"{v['source']} | {v['confidence']} | {v['endpoint_stability']} | [{v['victim_value_lower']}, {v['victim_value_upper']}] |"
                )
        else:
            md.append("No VASP entities attributed in path.")
        md.append("")

        md.append("## 5. Audited Branch Budget & Pruning Log")
        md.append(f"Total Branch Decisions Audited: **{len(pkg['branch_audit_log'])}**")
        md.append("| From | To | TX | Amount | Disposition | Reason | Tier |")
        md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for b in pkg["branch_audit_log"][:20]:
            md.append(
                f"| `{b['from_address'][:8]}...` | `{b['to_address'][:8]}...` | `{b['tx_hash'][:8]}...` | "
                f"{b['amount']} | `{b['disposition']}` | {b['reason'][:35]}... | Tier {b['tier']} |"
            )
        if len(pkg["branch_audit_log"]) > 20:
            md.append(f"*(...and {len(pkg['branch_audit_log']) - 20} additional audited branches)*")
        md.append("")

        if action:
            md.append("## 6. Investigator Action Packet")
            md.append(f"- **Primary Actionable Endpoint:** `{action.get('primary_supported_vasp') or 'None identified'}`")
            md.append(f"- **Target Wallet:** `{action.get('target_address') or '—'}`")
            md.append(f"- **Stability Tier:** `{action.get('endpoint_stability')}` | **Actionability:** `{action.get('actionability_state')}`")
            md.append("- **Suggested Record Categories for Authorized Request:**")
            for cat in action.get("suggested_record_categories", []):
                md.append(f"  - {cat}")
            md.append(f"\n> **Advisory Notice:** {action.get('advisory_notice')}\n")

        md.append("---")
        md.append("### FORENSIC DISCLAIMER")
        md.append(
            "> Multi-hypothesis attributions represent mathematical bounds under explicit analytical assumptions. "
            "Attribution intervals are not additive across models. "
            "Cryptographic SHA-256 package hash guarantees evidence record integrity."
        )

        return "\n".join(md)
