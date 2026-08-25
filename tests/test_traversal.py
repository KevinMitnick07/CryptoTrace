"""
Automated unit tests for Adaptive Traversal Engine & Branch Budgeting.
Testing adversarial fan-out, dust fragmentation, peeling chains, and budget exhaustion.
"""

from __future__ import annotations
import datetime
from decimal import Decimal
import pytest

from backend.core.models import (
    Chain, Asset, OnChainTransfer, TxState, BranchDisposition,
    TraceabilityState, AllocationModel
)
from backend.core.traversal import (
    AdaptiveTraversalEngine, TraversalConfig, assign_tier, detect_peeling
)
from tests.conftest import FakeChainAdapter


def test_adversarial_fanout_250_dust_fragmentation(fake_tron_adapter):
    """
    Scenario: 10,000 USDT split into 250 transfers of 40 USDT (0.4% per branch).
    Dust threshold is 0.5%.
    Every branch is below dust threshold.
    Current engine query limit is max_branches_per_hop + 20 (45 transfers).
    """
    victim_val = Decimal("10000.00")
    config = TraversalConfig(dust_threshold_pct=Decimal("0.005"), economic_threshold_pct=Decimal("0.01"))
    
    # Setup adapter with 250 outgoing transfers of 40 USDT
    outgoing = [
        OnChainTransfer(
            tx_hash=f"0x_tx_{i}",
            chain=Chain.TRON,
            asset=Asset.USDT_TRC20,
            amount=Decimal("40.00"),
            from_address="T_SUSPECT",
            to_address=f"T_DEST_{i}",
            block_number=1000 + i,
            block_timestamp=datetime.datetime(2026, 8, 1, 10, 0) + datetime.timedelta(seconds=i),
            tx_state=TxState.CONFIRMED,
        )
        for i in range(250)
    ]
    fake_tron_adapter.outgoing_transfers["t_suspect"] = outgoing
    fake_tron_adapter.balances[("t_suspect", Asset.USDT_TRC20)] = Decimal("0.00")
    
    engine = AdaptiveTraversalEngine(
        adapter_registry={Chain.TRON: fake_tron_adapter},
        vasp_registry=lambda chain, addr: None,
        mixer_detector=lambda chain, addr: False,
        config=config,
    )
    
    result = engine.trace(
        start_address="T_SUSPECT",
        start_chain=Chain.TRON,
        start_asset=Asset.USDT_TRC20,
        victim_value=victim_val,
        start_block=1000,
        start_timestamp=datetime.datetime(2026, 8, 1, 9, 50),
    )
    
    # Audit assertions:
    # 45 branches fetched by adapter (limit 45), all 45 audited as DEPRIORITIZED_DUST
    assert len(result.branch_audit) == 45
    dust_records = [b for b in result.branch_audit if b.disposition == BranchDisposition.DEPRIORITIZED_DUST]
    assert len(dust_records) == 45, "All fetched branches must be audited as DEPRIORITIZED_DUST"
    
    # Traversal must not enqueue any dust path segments
    assert len(result.path_segments) == 0
    assert result.unresolved_value.lower_bound == victim_val
    assert result.traceability_state == TraceabilityState.UNRESOLVED


def test_10_way_fanout_tier2(fake_eth_adapter):
    """10 outgoing transfers of 1,000 USDT each (10% of 10k -> Tier 2 -> Fully Traced)."""
    victim_val = Decimal("10000.00")
    outgoing = [
        OnChainTransfer(
            tx_hash=f"0x_tx_{i}",
            chain=Chain.ETHEREUM,
            asset=Asset.USDT_ERC20,
            amount=Decimal("1000.00"),
            from_address="0x_suspect",
            to_address=f"0x_dest_{i}",
            block_number=1000 + i,
            block_timestamp=datetime.datetime(2026, 8, 1, 10, i),
            tx_state=TxState.CONFIRMED,
        )
        for i in range(10)
    ]
    fake_eth_adapter.outgoing_transfers["0x_suspect"] = outgoing
    
    engine = AdaptiveTraversalEngine(
        adapter_registry={Chain.ETHEREUM: fake_eth_adapter},
        vasp_registry=lambda chain, addr: None,
        mixer_detector=lambda chain, addr: False,
    )
    
    result = engine.trace(
        start_address="0x_suspect",
        start_chain=Chain.ETHEREUM,
        start_asset=Asset.USDT_ERC20,
        victim_value=victim_val,
        start_block=1000,
        start_timestamp=datetime.datetime(2026, 8, 1, 9, 50),
    )
    
    assert len(result.path_segments) == 10
    fully_traced = [b for b in result.branch_audit if b.disposition == BranchDisposition.FULLY_TRACED]
    assert len(fully_traced) == 10


def test_max_branches_per_hop_exhaustion(fake_eth_adapter):
    """45 outgoing transfers of 600 USDT each (6% each -> Tier 3). Max branches per hop is 25."""
    victim_val = Decimal("10000.00")
    config = TraversalConfig(max_branches_per_hop=25)
    
    outgoing = [
        OnChainTransfer(
            tx_hash=f"0x_tx_{i}",
            chain=Chain.ETHEREUM,
            asset=Asset.USDT_ERC20,
            amount=Decimal("600.00"),
            from_address="0x_suspect",
            to_address=f"0x_dest_{i}",
            block_number=1000 + i,
            block_timestamp=datetime.datetime(2026, 8, 1, 10, 0) + datetime.timedelta(seconds=i),
            tx_state=TxState.CONFIRMED,
        )
        for i in range(45)  # adapter fetches limit + 20
    ]
    fake_eth_adapter.outgoing_transfers["0x_suspect"] = outgoing
    
    engine = AdaptiveTraversalEngine(
        adapter_registry={Chain.ETHEREUM: fake_eth_adapter},
        vasp_registry=lambda chain, addr: None,
        mixer_detector=lambda chain, addr: False,
        config=config,
    )
    
    result = engine.trace(
        start_address="0x_suspect",
        start_chain=Chain.ETHEREUM,
        start_asset=Asset.USDT_ERC20,
        victim_value=victim_val,
        start_block=1000,
        start_timestamp=datetime.datetime(2026, 8, 1, 9, 50),
    )
    
    assert len(result.path_segments) == 25, "Must strictly respect max_branches_per_hop=25"
    budget_exhausted = [b for b in result.branch_audit if b.disposition == BranchDisposition.BUDGET_EXHAUSTED]
    assert len(budget_exhausted) == 20, "Remaining 20 branches must be logged as BUDGET_EXHAUSTED"


def test_max_hops_exhaustion_distinguishable_from_no_vasp(fake_eth_adapter):
    """Linear chain of 10 hops. max_hops=8. Hop 8 must record BUDGET_EXHAUSTED and UNRESOLVED state."""
    victim_val = Decimal("10000.00")
    config = TraversalConfig(max_hops=8)
    
    # Setup linear chain 0 -> 1 -> 2 -> ... -> 9
    for i in range(10):
        fake_eth_adapter.outgoing_transfers[f"0x_hop_{i}"] = [
            OnChainTransfer(
                tx_hash=f"0x_tx_{i}",
                chain=Chain.ETHEREUM,
                asset=Asset.USDT_ERC20,
                amount=Decimal("10000.00"),
                from_address=f"0x_hop_{i}",
                to_address=f"0x_hop_{i+1}",
                block_number=1000 + i,
                block_timestamp=datetime.datetime(2026, 8, 1, 10, i),
                tx_state=TxState.CONFIRMED,
            )
        ]
    
    engine = AdaptiveTraversalEngine(
        adapter_registry={Chain.ETHEREUM: fake_eth_adapter},
        vasp_registry=lambda chain, addr: None,
        mixer_detector=lambda chain, addr: False,
        config=config,
    )
    
    result = engine.trace(
        start_address="0x_hop_0",
        start_chain=Chain.ETHEREUM,
        start_asset=Asset.USDT_ERC20,
        victim_value=victim_val,
        start_block=1000,
        start_timestamp=datetime.datetime(2026, 8, 1, 9, 50),
    )
    
    assert result.total_nodes_visited == 9  # 0 to 8
    exhausted = [b for b in result.branch_audit if b.disposition == BranchDisposition.BUDGET_EXHAUSTED]
    assert len(exhausted) > 0
    assert "0x_hop_8" in result.unresolved_addresses


def test_mixer_boundary_halts_traversal(fake_eth_adapter):
    """Traversal stops at Tornado Cash mixer and marks state OBFUSCATED."""
    victim_val = Decimal("10000.00")
    mixer_addr = "0xd90e2f925da726b50c4ed8d0fb90ad053324f31b"
    
    fake_eth_adapter.outgoing_transfers["0x_suspect"] = [
        OnChainTransfer(
            tx_hash="0x_tx_mixer",
            chain=Chain.ETHEREUM,
            asset=Asset.USDT_ERC20,
            amount=Decimal("10000.00"),
            from_address="0x_suspect",
            to_address=mixer_addr,
            block_number=1000,
            block_timestamp=datetime.datetime(2026, 8, 1, 10, 0),
            tx_state=TxState.CONFIRMED,
        )
    ]
    
    engine = AdaptiveTraversalEngine(
        adapter_registry={Chain.ETHEREUM: fake_eth_adapter},
        vasp_registry=lambda chain, addr: None,
        mixer_detector=lambda chain, addr: addr.lower() == mixer_addr.lower(),
    )
    
    result = engine.trace(
        start_address="0x_suspect",
        start_chain=Chain.ETHEREUM,
        start_asset=Asset.USDT_ERC20,
        victim_value=victim_val,
        start_block=1000,
        start_timestamp=datetime.datetime(2026, 8, 1, 9, 50),
    )
    
    assert mixer_addr in result.mixer_boundaries
    assert result.traceability_state == TraceabilityState.OBFUSCATED


def test_vasp_boundary_stops_traversal(fake_eth_adapter):
    """Traversal stops at VASP deposit address and records VASP candidate."""
    victim_val = Decimal("10000.00")
    binance_addr = "0x28c6c06298d514db089934071355e5743bf21d60"
    
    fake_eth_adapter.outgoing_transfers["0x_suspect"] = [
        OnChainTransfer(
            tx_hash="0x_tx_vasp",
            chain=Chain.ETHEREUM,
            asset=Asset.USDT_ERC20,
            amount=Decimal("10000.00"),
            from_address="0x_suspect",
            to_address=binance_addr,
            block_number=1000,
            block_timestamp=datetime.datetime(2026, 8, 1, 10, 0),
            tx_state=TxState.CONFIRMED,
        )
    ]
    
    engine = AdaptiveTraversalEngine(
        adapter_registry={Chain.ETHEREUM: fake_eth_adapter},
        vasp_registry=lambda chain, addr: "Binance" if addr.lower() == binance_addr.lower() else None,
        mixer_detector=lambda chain, addr: False,
    )
    
    result = engine.trace(
        start_address="0x_suspect",
        start_chain=Chain.ETHEREUM,
        start_asset=Asset.USDT_ERC20,
        victim_value=victim_val,
        start_block=1000,
        start_timestamp=datetime.datetime(2026, 8, 1, 9, 50),
    )
    
    assert binance_addr in result.vasp_candidates
    vasp_audit = [b for b in result.branch_audit if b.disposition == BranchDisposition.VASP_BOUNDARY]
    assert len(vasp_audit) == 1
