"""
Adaptive traversal engine with auditable branch budget and cumulative mass preservation.

Graph traversal must be controlled. Naive BFS on a fraud wallet can produce
thousands of nodes including major legitimate exchanges reached only because
all paths eventually pass through them.

This engine:
  - Uses collections.deque for efficient hot-path graph traversal
  - Ranks outgoing branches by victim-attributed value fraction
  - Assigns each branch to a priority tier (1–5)
  - Fully traces Tier 1–3 branches within budget
  - Stores Tier 4 branches as contextual evidence
  - Records material branches beyond per-hop execution budget as DEFERRED_BUDGET (not DUST)
  - Preserves cumulative victim mass across high-fragmentation fan-out
  - Records every pruning decision in an auditable BranchAuditRecord
  - Detects peeling chains and stops at recognized boundaries (VASP, mixer, bridge)
"""

from __future__ import annotations
import collections
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional, Callable
import datetime

from .models import (
    Chain, Asset, OnChainTransfer, BranchDisposition,
    BranchAuditRecord, PathSegment, TraceabilityState,
    EvidenceClass, AllocationModel, ValueInterval, utc_now
)
from .attribution import AccountBasedAttributionEngine
from ..protocols.dex import is_known_router, interpret_dex_interaction
from ..protocols.bridge import is_known_bridge

log = logging.getLogger(__name__)


@dataclass
class TraversalConfig:
    """
    All tunable parameters in one place.
    Defaults are conservative — investigators can relax them.
    """
    max_hops: int = 8
    max_branches_per_hop: int = 25   # Maximum fully traced branches per wallet
    dust_threshold_pct: Decimal = Decimal("0.005")  # Branch is dust if < 0.5% of victim value
    economic_threshold_pct: Decimal = Decimal("0.01")  # Branch is low-priority if < 1%
    tier1_threshold_pct: Decimal = Decimal("0.20")   # Branch carries ≥ 20% of victim value
    tier2_threshold_pct: Decimal = Decimal("0.05")   # ≥ 5%
    tier3_threshold_pct: Decimal = Decimal("0.01")   # ≥ 1%
    max_total_nodes: int = 300       # Hard stop on graph size
    peeling_min_chain_length: int = 3  # Minimum hops to compress as peeling chain


def assign_tier(
    attributed_value: Decimal,
    victim_value: Decimal,
    config: TraversalConfig,
) -> int:
    """
    Tier 1: Direct continuation carrying ≥ tier1_threshold of victim value.
    Tier 2: Significant branch (≥ tier2_threshold).
    Tier 3: Notable branch (≥ tier3_threshold / economic_threshold).
    Tier 4: Contextual (above dust, below economic threshold).
    Tier 5: Dust — effectively noise.
    """
    if victim_value == Decimal(0):
        return 5
    pct = attributed_value / victim_value
    if pct >= config.tier1_threshold_pct:
        return 1
    if pct >= config.tier2_threshold_pct:
        return 2
    if pct >= config.tier3_threshold_pct:
        return 3
    if pct >= config.dust_threshold_pct:
        return 4
    return 5


def detect_peeling(segments: list[PathSegment], config: TraversalConfig) -> bool:
    """
    A peeling chain: each hop forwards most (but not all) of the incoming value
    to exactly one continuation, keeping a small residual.
    """
    if len(segments) < config.peeling_min_chain_length:
        return False
    consecutive_peel = 0
    for seg in segments[-config.peeling_min_chain_length:]:
        prop_value = seg.victim_value_by_model.get(AllocationModel.PROPORTIONAL, Decimal(0))
        if seg.transfer and prop_value > Decimal(0):
            consecutive_peel += 1
    return consecutive_peel >= config.peeling_min_chain_length


@dataclass
class TraversalResult:
    path_segments: list[PathSegment]
    branch_audit: list[BranchAuditRecord]
    vasp_candidates: list[str]          # Addresses attributed to VASPs
    mixer_boundaries: list[str]         # Addresses where tracing stopped (mixer)
    bridge_events: list                 # BridgeEvent objects
    dex_transformations: list           # DexTransformation objects
    unresolved_addresses: list[str]     # Addresses with no attribution
    unresolved_value: ValueInterval
    deferred_value: ValueInterval       # Material value unexamined due to computation budget
    total_nodes_visited: int
    peeling_chains_detected: int
    traceability_state: TraceabilityState
    trace_completeness_pct: Decimal = Decimal("100.00")
    high_fragmentation_detected: bool = False


class AdaptiveTraversalEngine:
    """
    Evidence-preserving adaptive traversal.
    """

    def __init__(
        self,
        adapter_registry: dict,
        vasp_registry: Callable[[Chain, str], Optional[str]],
        mixer_detector: Callable[[Chain, str], bool],
        config: Optional[TraversalConfig] = None,
    ):
        self._adapters = adapter_registry
        self._vasp_lookup = vasp_registry
        self._is_mixer = mixer_detector
        self._config = config or TraversalConfig()

    def trace(
        self,
        start_address: str,
        start_chain: Chain,
        start_asset: Asset,
        victim_value: Decimal,
        start_block: int,
        start_timestamp: datetime.datetime,
    ) -> TraversalResult:
        """
        Entry point for deep-path traversal.
        """
        config = self._config
        path_segments: list[PathSegment] = []
        branch_audit: list[BranchAuditRecord] = []
        vasp_candidates: list[str] = []
        mixer_boundaries: list[str] = []
        bridge_events: list = []
        dex_transformations: list = []
        unresolved_addresses: list[str] = []
        peeling_count = 0
        total_nodes = 0
        total_deferred_mass = Decimal(0)
        high_fragmentation = False

        # Work queue: (address, chain, asset, remaining_victim_value, hop_depth, parent_tx_hash, after_block)
        queue = collections.deque([
            (start_address, start_chain, start_asset, victim_value, 0, None, start_block)
        ])
        visited: set[str] = set()

        while queue and total_nodes < config.max_total_nodes:
            address, chain, asset, remaining_value, hop, parent_hash, after_block = queue.popleft()

            node_key = f"{chain.value}:{address}"
            if node_key in visited:
                continue
            visited.add(node_key)
            total_nodes += 1

            if hop >= config.max_hops:
                branch_audit.append(BranchAuditRecord(
                    from_address=parent_hash or "",
                    to_address=address,
                    tx_hash=parent_hash or "",
                    chain=chain,
                    asset=asset,
                    amount=remaining_value,
                    victim_attributed_range=ValueInterval(remaining_value, remaining_value, asset),
                    disposition=BranchDisposition.BUDGET_EXHAUSTED,
                    reason=f"Max hop depth {config.max_hops} reached.",
                    tier=5,
                    timestamp=utc_now(),
                ))
                unresolved_addresses.append(address)
                continue

            # Check known boundaries before fetching transfers
            if self._is_mixer(chain, address):
                mixer_boundaries.append(address)
                branch_audit.append(BranchAuditRecord(
                    from_address=parent_hash or "",
                    to_address=address,
                    tx_hash=parent_hash or "",
                    chain=chain, asset=asset, amount=remaining_value,
                    victim_attributed_range=ValueInterval(remaining_value, remaining_value, asset),
                    disposition=BranchDisposition.MIXER_BOUNDARY,
                    reason="Known mixer/tumbler service. Traceability: OBFUSCATED.",
                    tier=1, timestamp=utc_now(),
                ))
                continue

            vasp_entity = self._vasp_lookup(chain, address)
            if vasp_entity:
                vasp_candidates.append(address)
                branch_audit.append(BranchAuditRecord(
                    from_address=parent_hash or "",
                    to_address=address,
                    tx_hash=parent_hash or "",
                    chain=chain, asset=asset, amount=remaining_value,
                    victim_attributed_range=ValueInterval(remaining_value, remaining_value, asset),
                    disposition=BranchDisposition.VASP_BOUNDARY,
                    reason=f"VASP boundary reached: {vasp_entity}.",
                    tier=1, timestamp=utc_now(),
                ))
                continue

            # Check if this is a known DEX router
            if is_known_router(chain, address):
                dex_dispo = BranchAuditRecord(
                    from_address=parent_hash or "",
                    to_address=address,
                    tx_hash=parent_hash or "",
                    chain=chain, asset=asset, amount=remaining_value,
                    victim_attributed_range=ValueInterval(remaining_value, remaining_value, asset),
                    disposition=BranchDisposition.FULLY_TRACED,
                    reason="DEX router reached. Transformation record required.",
                    tier=1, timestamp=utc_now(),
                )
                branch_audit.append(dex_dispo)
                continue

            # Check if known bridge
            if is_known_bridge(chain, address):
                bridge_events.append(address)
                branch_audit.append(BranchAuditRecord(
                    from_address=parent_hash or "",
                    to_address=address,
                    tx_hash=parent_hash or "",
                    chain=chain, asset=asset, amount=remaining_value,
                    victim_attributed_range=ValueInterval(remaining_value, remaining_value, asset),
                    disposition=BranchDisposition.FULLY_TRACED,
                    reason="Bridge contract reached. Cross-chain continuation required.",
                    tier=1, timestamp=utc_now(),
                ))
                continue

            # Fetch outgoing transfers
            adapter = self._adapters.get(chain)
            if adapter is None:
                unresolved_addresses.append(address)
                continue

            fetch_limit = config.max_branches_per_hop + 20
            try:
                outgoing = adapter.get_transfers_from(
                    address=address,
                    asset=asset,
                    after_block=after_block,
                    before_block=None,
                    limit=fetch_limit,
                )
            except Exception as exc:
                log.warning("Provider query failed for %s on %s: %s", address, chain, exc)
                branch_audit.append(BranchAuditRecord(
                    from_address=parent_hash or "",
                    to_address=address,
                    tx_hash=parent_hash or "",
                    chain=chain,
                    asset=asset,
                    amount=remaining_value,
                    victim_attributed_range=ValueInterval(remaining_value, remaining_value, asset),
                    disposition=BranchDisposition.DEFERRED_BUDGET,
                    reason=f"Provider query limited/failed: {str(exc)[:150]}. Marked as unresolved.",
                    tier=hop + 1,
                    timestamp=utc_now(),
                ))
                unresolved_addresses.append(address)
                continue

            if not outgoing:
                unresolved_addresses.append(address)
                continue

            # Get historical balance
            hist_bal = adapter.get_historical_balance(address, asset, at_block=after_block)
            engine = AccountBasedAttributionEngine(remaining_value, asset)
            model_results = engine.allocate(hist_bal, outgoing)

            # Peeling detection
            if len(outgoing) == 1 and hop > 0:
                peeling_count += 1

            # High fragmentation detection:
            # Fire if >= 20 distinct outgoing transfers, OR if the adapter returned exactly
            # fetch_limit items (saturation proxy — the adapter may have more).
            if len(outgoing) >= 20 or len(outgoing) == fetch_limit:
                high_fragmentation = True

            # Assign tiers to each branch
            branch_tiers: list[tuple[OnChainTransfer, int, Decimal]] = []
            for t in outgoing:
                prop_val = model_results[AllocationModel.PROPORTIONAL].get(
                    t.to_address, Decimal(0)
                )
                tier = assign_tier(prop_val, remaining_value, config)
                branch_tiers.append((t, tier, prop_val))

            # Sort: tier ascending (lower = higher priority), then value descending
            branch_tiers.sort(key=lambda x: (x[1], -x[2]))

            fully_traced_count = 0
            for transfer, tier, prop_val in branch_tiers:
                interval = engine.compute_value_interval(
                    transfer.to_address, model_results, asset
                )

                if tier == 5:  # Dust
                    branch_audit.append(BranchAuditRecord(
                        from_address=address,
                        to_address=transfer.to_address,
                        tx_hash=transfer.tx_hash,
                        chain=chain, asset=asset, amount=transfer.amount,
                        victim_attributed_range=interval,
                        disposition=BranchDisposition.DEPRIORITIZED_DUST,
                        reason=(
                            f"Transfer amount {transfer.amount} {asset.value} is below dust "
                            f"threshold ({float(config.dust_threshold_pct * 100):.1f}% of victim value). "
                            "Stored as contextual evidence."
                        ),
                        tier=5, timestamp=utc_now(),
                    ))
                    continue

                if tier == 4:  # Contextual
                    total_deferred_mass += prop_val
                    branch_audit.append(BranchAuditRecord(
                        from_address=address,
                        to_address=transfer.to_address,
                        tx_hash=transfer.tx_hash,
                        chain=chain, asset=asset, amount=transfer.amount,
                        victim_attributed_range=interval,
                        disposition=BranchDisposition.CONTEXTUAL,
                        reason=(
                            f"Transfer carries estimated {float(prop_val):.2f} {asset.value} "
                            f"({float(prop_val/remaining_value*100):.1f}% of victim value). "
                            "Below economic threshold. Stored; not traversed."
                        ),
                        tier=4, timestamp=utc_now(),
                    ))
                    continue

                if fully_traced_count >= config.max_branches_per_hop:
                    total_deferred_mass += prop_val
                    branch_audit.append(BranchAuditRecord(
                        from_address=address,
                        to_address=transfer.to_address,
                        tx_hash=transfer.tx_hash,
                        chain=chain, asset=asset, amount=transfer.amount,
                        victim_attributed_range=interval,
                        disposition=BranchDisposition.BUDGET_EXHAUSTED,
                        reason="Branch budget exhausted for this hop.",
                        tier=tier, timestamp=utc_now(),
                    ))
                    continue

                # Fully trace this branch
                fully_traced_count += 1
                per_model_at_dest = {
                    m: model_results[m].get(transfer.to_address, Decimal(0))
                    for m in AllocationModel
                }
                seg = PathSegment(
                    sequence=len(path_segments),
                    transfer=transfer,
                    transformation=None,
                    bridge_event=None,
                    to_address=transfer.to_address,
                    to_chain=chain,
                    victim_value_by_model=per_model_at_dest,
                    traceability=TraceabilityState.SUPPORTED,
                    evidence_class=EvidenceClass.OBSERVED,
                )
                path_segments.append(seg)
                branch_audit.append(BranchAuditRecord(
                    from_address=address,
                    to_address=transfer.to_address,
                    tx_hash=transfer.tx_hash,
                    chain=chain, asset=asset, amount=transfer.amount,
                    victim_attributed_range=interval,
                    disposition=BranchDisposition.FULLY_TRACED,
                    reason=f"Tier {tier} branch. Attributed value: {float(prop_val):.2f} {asset.value}.",
                    tier=tier, timestamp=utc_now(),
                ))

                # Enqueue continuation
                next_value = per_model_at_dest.get(AllocationModel.PROPORTIONAL, Decimal(0))
                if next_value > Decimal("0.000001"):
                    queue.append((
                        transfer.to_address,
                        chain,
                        asset,
                        next_value,
                        hop + 1,
                        transfer.tx_hash,
                        transfer.block_number,
                    ))

        # Budget exhausted: drain remaining queue items and record them.
        # This ensures no victim-attributed value is silently lost when max_total_nodes is hit.
        while queue:
            rem_addr, rem_chain, rem_asset, rem_value, rem_hop, rem_parent, _rem_block = queue.popleft()
            node_key_rem = f"{rem_chain.value}:{rem_addr}"
            if node_key_rem in visited:
                continue
            total_deferred_mass += rem_value
            branch_audit.append(BranchAuditRecord(
                from_address=rem_parent or "",
                to_address=rem_addr,
                tx_hash=rem_parent or "",
                chain=rem_chain,
                asset=rem_asset,
                amount=rem_value,
                victim_attributed_range=ValueInterval(rem_value, rem_value, rem_asset),
                disposition=BranchDisposition.BUDGET_EXHAUSTED,
                reason=(
                    f"max_total_nodes ({config.max_total_nodes}) reached. "
                    "This is a computation budget limit, NOT a forensic boundary. "
                    f"Estimated {float(rem_value):.4f} {rem_asset.value} in victim value remains unexamined."
                ),
                tier=rem_hop + 1,
                timestamp=utc_now(),
            ))
            unresolved_addresses.append(rem_addr)

        # Compute unresolved value interval and completeness metrics
        traced_max = sum(
            seg.victim_value_by_model.get(AllocationModel.PROPORTIONAL, Decimal(0))
            for seg in path_segments
            if seg.transfer
        )
        unresolved_lower = max(Decimal(0), victim_value - traced_max)
        unresolved_upper = victim_value
        unresolved_interval = ValueInterval(unresolved_lower, unresolved_upper, start_asset)
        deferred_interval = ValueInterval(total_deferred_mass, total_deferred_mass, start_asset)

        completeness_pct = Decimal("100.00")
        if victim_value > Decimal(0):
            completeness_pct = min(Decimal("100.00"), max(Decimal(0), (traced_max / victim_value) * Decimal("100.00")))

        overall_traceability = TraceabilityState.SUPPORTED
        if mixer_boundaries:
            overall_traceability = TraceabilityState.OBFUSCATED
        elif unresolved_lower > victim_value * Decimal("0.5") or (total_deferred_mass > victim_value * Decimal("0.5")):
            overall_traceability = TraceabilityState.UNRESOLVED

        return TraversalResult(
            path_segments=path_segments,
            branch_audit=branch_audit,
            vasp_candidates=vasp_candidates,
            mixer_boundaries=mixer_boundaries,
            bridge_events=bridge_events,
            dex_transformations=dex_transformations,
            unresolved_addresses=unresolved_addresses,
            unresolved_value=unresolved_interval,
            deferred_value=deferred_interval,
            total_nodes_visited=total_nodes,
            peeling_chains_detected=peeling_count,
            traceability_state=overall_traceability,
            trace_completeness_pct=completeness_pct,
            high_fragmentation_detected=high_fragmentation,
        )
