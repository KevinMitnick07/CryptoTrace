"""
VASP attribution registry and multi-source claim repository.

Stores entity labels for blockchain addresses with full provenance.
Preserves multi-source intelligence without destructive overwrite.
"""

from __future__ import annotations
import json
import logging
import os
from typing import Optional, Callable, Union
import datetime

from ..core.models import (
    Chain, Asset, VaspRecord, AttributionSource, AttributionConfidence,
    VaspLookupResult, VaspClaimStatus, utc_now
)

log = logging.getLogger(__name__)

STALE_THRESHOLD_DAYS = int(os.getenv("VASP_STALE_DAYS", "180"))

# Known mixer addresses
KNOWN_MIXERS: dict[Chain, set[str]] = {
    Chain.ETHEREUM: {
        "0xd90e2f925da726b50c4ed8d0fb90ad053324f31b",  # Tornado Cash v1
        "0x722122df12d4e14e13ac3b6895a86e84145b6967",  # Tornado Cash v2
        "0xdd4c48c0b24039969fc16d1cdf626eab821d3384",  # Tornado Cash v3
    },
    Chain.BITCOIN: set(),
    Chain.TRON: set(),
    Chain.ARBITRUM: set(),
    Chain.OPTIMISM: set(),
    Chain.BSC: set(),
    Chain.POLYGON: set(),
    Chain.UNKNOWN: set(),
}


class VaspRegistry:
    """
    Provides entity attribution for blockchain addresses with multi-claim preservation.
    """

    def __init__(self, label_data: Union[list[dict], dict]):
        # Index: (chain_value, address_lower) → list[VaspRecord]
        self._index: dict[tuple[str, str], list[VaspRecord]] = {}
        if isinstance(label_data, dict):
            records = label_data.get("records", [])
        else:
            records = label_data
        self._load(records)

    def _load(self, records: list[dict]) -> None:
        loaded = 0
        for r in records:
            try:
                chain = Chain(r["chain"])
                address = r["address"].lower()
                first_observed = datetime.datetime.fromisoformat(r["first_observed"])
                last_verified = datetime.datetime.fromisoformat(r["last_verified"])
                effective_until = (
                    datetime.datetime.fromisoformat(r["effective_until"])
                    if r.get("effective_until") else None
                )
                record = VaspRecord(
                    address=address,
                    chain=chain,
                    entity_name=r["entity_name"],
                    entity_role=r.get("entity_role", "deposit_infrastructure"),
                    source=AttributionSource(r.get("source", "PROTOTYPE_REGISTRY")),
                    source_reliability=r.get("source_reliability", "LOW"),
                    first_observed=first_observed,
                    last_verified=last_verified,
                    confidence=AttributionConfidence(r.get("confidence", "LOW")),
                    is_active=r.get("is_active", True),
                    independent_corroboration=r.get("independent_corroboration", False),
                    notes=r.get("notes", ""),
                    effective_until=effective_until,
                )
                key = (chain.value, address)
                if key not in self._index:
                    self._index[key] = []
                self._index[key].append(record)
                loaded += 1
            except (KeyError, ValueError) as exc:
                log.warning("Skipping malformed VASP registry entry: %s — %s", r.get("address"), exc)
        log.info("VASP registry loaded: %d claims across %d addresses", loaded, len(self._index))

    def lookup(self, chain: Chain, address: str) -> VaspLookupResult:
        """
        Evaluate all claims for an address and determine resolution status.
        Preserves conflicting sources rather than silently choosing one.
        """
        addr_lower = address.lower()
        claims = self._index.get((chain.value, addr_lower), [])

        if not claims:
            # Check if recognized mixer
            if self.is_mixer(chain, addr_lower):
                return VaspLookupResult(
                    status=VaspClaimStatus.RESOLVED,
                    primary_claim=None,
                    claims=[],
                    entity_type="MIXER",
                    is_stale=False,
                )
            return VaspLookupResult(
                status=VaspClaimStatus.INSUFFICIENT_EVIDENCE,
                primary_claim=None,
                claims=[],
                entity_type="UNKNOWN",
                is_stale=False,
            )

        # Classify entity type
        first_role = claims[0].entity_role.lower()
        if "mixer" in first_role or self.is_mixer(chain, addr_lower):
            entity_type = "MIXER"
        elif "dex" in first_role or "router" in first_role or "pool" in first_role:
            entity_type = "DEX"
        elif "bridge" in first_role:
            entity_type = "BRIDGE"
        elif "foundation" in first_role or "treasury" in first_role:
            entity_type = "FOUNDATION"
        else:
            entity_type = "CUSTODIAL_VASP"

        # Check for multi-source conflict
        entity_names = {c.entity_name for c in claims}
        is_conflicted = len(entity_names) > 1

        # Check staleness of most recent claim
        sorted_claims = sorted(claims, key=lambda c: c.last_verified, reverse=True)
        primary = sorted_claims[0]
        stale = primary.is_stale(STALE_THRESHOLD_DAYS)

        if is_conflicted:
            dispute_msg = f"Conflicting entity assertions detected across {len(claims)} sources: {', '.join(sorted(entity_names))}"
            disputed_claim = VaspRecord(
                address=primary.address,
                chain=primary.chain,
                entity_name=primary.entity_name,
                entity_role=primary.entity_role,
                source=primary.source,
                source_reliability="DISPUTED",
                first_observed=primary.first_observed,
                last_verified=primary.last_verified,
                confidence=AttributionConfidence.DISPUTED,
                is_active=primary.is_active,
                independent_corroboration=False,
                notes=f"[DISPUTED: {dispute_msg}] {primary.notes}",
            )
            return VaspLookupResult(
                status=VaspClaimStatus.CONFLICTED,
                primary_claim=disputed_claim,
                claims=claims,
                entity_type=entity_type,
                is_stale=stale,
                dispute_reason=dispute_msg,
            )

        if stale:
            stale_claim = VaspRecord(
                address=primary.address,
                chain=primary.chain,
                entity_name=primary.entity_name,
                entity_role=primary.entity_role,
                source=primary.source,
                source_reliability=primary.source_reliability,
                first_observed=primary.first_observed,
                last_verified=primary.last_verified,
                confidence=AttributionConfidence.STALE,
                is_active=primary.is_active,
                independent_corroboration=primary.independent_corroboration,
                notes=f"[STALE: Verified > {STALE_THRESHOLD_DAYS} days ago] {primary.notes}",
            )
            return VaspLookupResult(
                status=VaspClaimStatus.STALE,
                primary_claim=stale_claim,
                claims=claims,
                entity_type=entity_type,
                is_stale=True,
            )

        return VaspLookupResult(
            status=VaspClaimStatus.RESOLVED,
            primary_claim=primary,
            claims=claims,
            entity_type=entity_type,
            is_stale=False,
        )

    def get(self, chain: Chain, address: str) -> Optional[VaspRecord]:
        """
        Legacy get method returning the primary resolved or disputed claim.
        """
        res = self.lookup(chain, address)
        return res.primary_claim

    def is_mixer(self, chain: Chain, address: str) -> bool:
        mixers = KNOWN_MIXERS.get(chain, set())
        return address.lower() in mixers

    def is_stale_record(self, record: VaspRecord) -> bool:
        return record.is_stale(STALE_THRESHOLD_DAYS)

    def stats(self) -> dict:
        total_claims = sum(len(c) for c in self._index.values())
        stale_count = 0
        for claims in self._index.values():
            if claims and claims[0].is_stale(STALE_THRESHOLD_DAYS):
                stale_count += 1
        return {
            "total_entries": total_claims,
            "unique_addresses": len(self._index),
            "stale_entries": stale_count,
            "stale_threshold_days": STALE_THRESHOLD_DAYS,
        }


def load_registry_from_file(filepath: str) -> VaspRegistry:
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "records" in data:
        data = data["records"]
    return VaspRegistry(data)


def make_vasp_lookup_fn(registry: VaspRegistry) -> Callable[[Chain, str], Optional[str]]:
    def lookup(chain: Chain, address: str) -> Optional[str]:
        res = registry.lookup(chain, address)
        # Only return entity name if it's a custodial VASP or resolved entity
        if res.primary_claim and res.entity_type == "CUSTODIAL_VASP":
            return res.primary_claim.entity_name
        return None
    return lookup


def make_mixer_fn(registry: VaspRegistry) -> Callable[[Chain, str], bool]:
    def is_mixer(chain: Chain, address: str) -> bool:
        return registry.is_mixer(chain, address)
    return is_mixer
