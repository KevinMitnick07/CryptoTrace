"""
Automated unit tests for multi-hypothesis fund attribution & value conservation invariants.
Testing Conservative, Proportional, FIFO, and LIFO models under adversarial scenarios.
"""

from __future__ import annotations
import datetime
from decimal import Decimal
import pytest

from backend.core.models import (
    AllocationModel, Asset, OnChainTransfer, TxState, ValueInterval
)
from backend.core.attribution import (
    AccountBasedAttributionEngine, UTXOAttributionEngine, _value_conservation_check
)


def _make_transfer(
    tx_hash: str,
    to_address: str,
    amount: Decimal,
    asset: Asset = Asset.USDT_ERC20,
    timestamp: datetime.datetime = datetime.datetime(2026, 8, 1, 12, 0, 0),
) -> OnChainTransfer:
    return OnChainTransfer(
        tx_hash=tx_hash,
        chain=Asset.USDT_ERC20,
        asset=asset,
        amount=amount,
        from_address="0x_suspect",
        to_address=to_address,
        block_number=1000,
        block_timestamp=timestamp,
        tx_state=TxState.CONFIRMED,
    )


# ===========================================================================
# 1. CORE ATTRIBUTION SCENARIOS
# ===========================================================================

def test_scenario_a_direct_clean_flow():
    """Scenario A: Direct clean flow (10,000 in -> 10,000 out)."""
    victim_val = Decimal("10000.00")
    engine = AccountBasedAttributionEngine(victim_val, Asset.USDT_ERC20)

    outgoing = [
        _make_transfer("0x1", "0x_dest_1", Decimal("10000.00"))
    ]

    result = engine.allocate(Decimal("0.00"), outgoing)

    # All 4 models must allocate exactly 10,000 to 0x_dest_1
    for model in AllocationModel:
        allocated = result[model].get("0x_dest_1", Decimal(0))
        assert allocated == Decimal("10000.00"), f"{model} failed clean allocation"
        # Conservation check
        assert sum(result[model].values()) <= victim_val


def test_scenario_b_pre_existing_balance():
    """Scenario B: Existing balance 50k, victim deposit 10k, two outgoing transfers."""
    victim_val = Decimal("10000.00")
    engine = AccountBasedAttributionEngine(victim_val, Asset.USDT_ERC20)

    outgoing = [
        _make_transfer("0x1", "0x_dest_a", Decimal("20000.00"), timestamp=datetime.datetime(2026, 8, 1, 10, 0)),
        _make_transfer("0x2", "0x_dest_b", Decimal("40000.00"), timestamp=datetime.datetime(2026, 8, 1, 11, 0)),
    ]

    result = engine.allocate(Decimal("50000.00"), outgoing)

    for model in AllocationModel:
        total_attributed = sum(result[model].values())
        assert total_attributed <= victim_val, f"{model} violated value conservation!"

    # Model specific behavior checks:
    # Proportional: 20k/60k -> 3333.33 to A, 40k/60k -> 6666.67 to B
    prop = result[AllocationModel.PROPORTIONAL]
    assert prop["0x_dest_a"] == pytest.approx(Decimal("10000") * Decimal("20000") / Decimal("60000"), rel=1e-4)

    # FIFO: first 10k fills 0x_dest_a (which is 20k)
    fifo = result[AllocationModel.FIFO]
    assert fifo["0x_dest_a"] == Decimal("10000.00")
    assert fifo.get("0x_dest_b", Decimal(0)) == Decimal("0.00")

    # LIFO: fills latest 0x_dest_b (which is 40k)
    lifo = result[AllocationModel.LIFO]
    assert lifo.get("0x_dest_a", Decimal(0)) == Decimal("0.00")
    assert lifo["0x_dest_b"] == Decimal("10000.00")


def test_scenario_c_complete_commingling_90k():
    """Scenario C: 90k pre-existing balance + 10k deposit -> 5k to A, 95k to B."""
    victim_val = Decimal("10000.00")
    engine = AccountBasedAttributionEngine(victim_val, Asset.USDT_ERC20)

    outgoing = [
        _make_transfer("0x1", "0x_dest_a", Decimal("5000.00"), timestamp=datetime.datetime(2026, 8, 1, 10, 0)),
        _make_transfer("0x2", "0x_dest_b", Decimal("95000.00"), timestamp=datetime.datetime(2026, 8, 1, 11, 0)),
    ]

    result = engine.allocate(Decimal("90000.00"), outgoing)

    for model in AllocationModel:
        assert sum(result[model].values()) <= victim_val

    # FIFO must give 5k to A and remaining 5k to B
    assert result[AllocationModel.FIFO]["0x_dest_a"] == Decimal("5000.00")
    assert result[AllocationModel.FIFO]["0x_dest_b"] == Decimal("5000.00")

    # LIFO must give 10k to B and 0 to A
    assert result[AllocationModel.LIFO].get("0x_dest_a", Decimal(0)) == Decimal("0.00")
    assert result[AllocationModel.LIFO]["0x_dest_b"] == Decimal("10000.00")


def test_scenario_d_multiple_outgoing_transfers():
    """Scenario D: 5 sequential outgoing transfers of 2,000 each."""
    victim_val = Decimal("10000.00")
    engine = AccountBasedAttributionEngine(victim_val, Asset.USDT_ERC20)

    outgoing = [
        _make_transfer(f"0x{i}", f"0x_dest_{i}", Decimal("2000.00"), timestamp=datetime.datetime(2026, 8, 1, 10, i))
        for i in range(1, 6)
    ]

    result = engine.allocate(Decimal("0.00"), outgoing)
    for model in AllocationModel:
        assert sum(result[model].values()) <= Decimal("10000.00")

    # Proportional, FIFO, and LIFO allocate all 10,000 across the 5 transfers
    assert sum(result[AllocationModel.PROPORTIONAL].values()) == Decimal("10000.00")
    assert sum(result[AllocationModel.FIFO].values()) == Decimal("10000.00")
    assert sum(result[AllocationModel.LIFO].values()) == Decimal("10000.00")
    # Conservative model undercounts by design on fragmented transfers (attributes 2,000)
    assert sum(result[AllocationModel.CONSERVATIVE].values()) == Decimal("2000.00")


def test_scenario_e_zero_outgoing_value():
    """Scenario E: Suspect wallet receives 10,000 but makes zero outgoing transfers."""
    victim_val = Decimal("10000.00")
    engine = AccountBasedAttributionEngine(victim_val, Asset.USDT_ERC20)

    result = engine.allocate(Decimal("0.00"), [])
    for model in AllocationModel:
        assert len(result[model]) == 0


def test_scenario_f_outgoing_greater_than_victim_value():
    """Scenario F: Suspect wallet sends 500,000 USDT total; victim value is 10,000."""
    victim_val = Decimal("10000.00")
    engine = AccountBasedAttributionEngine(victim_val, Asset.USDT_ERC20)

    outgoing = [
        _make_transfer("0x1", "0x_dest_a", Decimal("250000.00"), timestamp=datetime.datetime(2026, 8, 1, 10, 0)),
        _make_transfer("0x2", "0x_dest_b", Decimal("250000.00"), timestamp=datetime.datetime(2026, 8, 1, 11, 0)),
    ]

    result = engine.allocate(Decimal("490000.00"), outgoing)
    for model in AllocationModel:
        assert sum(result[model].values()) <= victim_val + Decimal("0.01")


def test_scenario_g_very_large_raw_quantities():
    """Scenario G: 100 Billion USDT units (large institution scale)."""
    victim_val = Decimal("100000000000.00")
    engine = AccountBasedAttributionEngine(victim_val, Asset.USDT_ERC20)

    outgoing = [
        _make_transfer("0x1", "0x_dest_a", Decimal("60000000000.00"), timestamp=datetime.datetime(2026, 8, 1, 10, 0)),
        _make_transfer("0x2", "0x_dest_b", Decimal("40000000000.00"), timestamp=datetime.datetime(2026, 8, 1, 11, 0)),
    ]

    result = engine.allocate(Decimal("0.00"), outgoing)
    for model in AllocationModel:
        assert sum(result[model].values()) <= victim_val + Decimal("0.01")


def test_scenario_h_small_decimal_quantities():
    """Scenario H: 0.000001 USDT units (micro-fractions)."""
    victim_val = Decimal("0.000001")
    engine = AccountBasedAttributionEngine(victim_val, Asset.USDT_ERC20)

    outgoing = [
        _make_transfer("0x1", "0x_dest_a", Decimal("0.000001"))
    ]

    result = engine.allocate(Decimal("0.00"), outgoing)
    for model in AllocationModel:
        assert sum(result[model].values()) <= victim_val + Decimal("0.01")


# ===========================================================================
# 2. MODEL SEPARATION & VALUE INTERVAL INVARIANTS
# ===========================================================================

def test_preserve_model_separation():
    """Verify that ValueInterval(min, max) bounds do not sum across mutually incompatible models."""
    victim_val = Decimal("10000.00")
    engine = AccountBasedAttributionEngine(victim_val, Asset.USDT_ERC20)

    outgoing = [
        _make_transfer("0x1", "0x_dest_a", Decimal("10000.00"), timestamp=datetime.datetime(2026, 8, 1, 10, 0)),
        _make_transfer("0x2", "0x_dest_b", Decimal("10000.00"), timestamp=datetime.datetime(2026, 8, 1, 11, 0)),
    ]

    result = engine.allocate(Decimal("10000.00"), outgoing)

    interval_a = engine.compute_value_interval("0x_dest_a", result, Asset.USDT_ERC20)
    interval_b = engine.compute_value_interval("0x_dest_b", result, Asset.USDT_ERC20)

    # FIFO gives 10k to A and 0 to B
    # LIFO gives 0 to A and 10k to B
    # Max of interval_a is 10k, max of interval_b is 10k
    assert interval_a.upper_bound == Decimal("10000.00")
    assert interval_b.upper_bound == Decimal("10000.00")

    # The sum of upper bounds across separate intervals is 20k (which is NOT a valid joint claim)
    # The engine must keep each model's vector separate
    assert sum(result[AllocationModel.FIFO].values()) == Decimal("10000.00")
    assert sum(result[AllocationModel.LIFO].values()) == Decimal("10000.00")


def test_utxo_attribution_raises_not_implemented():
    """Verify UTXO boundary raises NotImplementedError rather than applying account models to Bitcoin."""
    engine = UTXOAttributionEngine("txid_01", 0, Decimal("1.5"))
    with pytest.raises(NotImplementedError):
        engine.propagate()


# ===========================================================================
# DECIMAL PRECISION CONSERVATION TESTS
# ===========================================================================

def test_conservation_6_decimal_usdt_erc20():
    """
    Conservation must hold for 6-decimal USDT_ERC20.
    Smallest representable unit = 0.000001 USDT.
    All 4 models must not allocate more than victim_value.
    """
    victim_val = Decimal("5000.000001")   # deliberate fractional base unit
    engine = AccountBasedAttributionEngine(victim_val, Asset.USDT_ERC20)

    outgoing = [
        _make_transfer("0xtx_6dp_a", "0x_dest_a", Decimal("2500.000001"), asset=Asset.USDT_ERC20),
        _make_transfer("0xtx_6dp_b", "0x_dest_b", Decimal("2500.000000"), asset=Asset.USDT_ERC20),
    ]

    result = engine.allocate(Decimal("0.000000"), outgoing)

    for model in AllocationModel:
        total_allocated = sum(result[model].values())
        assert total_allocated <= victim_val, (
            f"{model}: allocated {total_allocated} > victim_val {victim_val}. "
            "Conservation violated on 6-decimal USDT_ERC20."
        )

    # Explicit conservation check using the precision tool (correct 3-arg signature)
    violations = _value_conservation_check(victim_val, result, Asset.USDT_ERC20)
    assert violations == [], f"Conservation violations: {violations}"


def test_conservation_18_decimal_eth():
    """
    Conservation must hold for 18-decimal ETH.
    Test values include a 1-wei (1e-18 ETH) residual.
    """
    victim_val = Decimal("3.141592653589793238")   # 18-decimal precision ETH
    engine = AccountBasedAttributionEngine(victim_val, Asset.ETH)

    outgoing = [
        _make_transfer("0xtx_18dp_a", "0x_dest_a", Decimal("2.000000000000000000"), asset=Asset.ETH),
        _make_transfer("0xtx_18dp_b", "0x_dest_b", Decimal("1.141592653589793238"), asset=Asset.ETH),
    ]

    result = engine.allocate(Decimal("0.000000000000000000"), outgoing)

    for model in AllocationModel:
        total_allocated = sum(result[model].values())
        assert total_allocated <= victim_val, (
            f"{model}: over-allocation on 18-decimal ETH. "
            f"Allocated {total_allocated}, victim_val {victim_val}."
        )


def test_conservation_minimum_representable_usdt_unit():
    """
    Transfer of 1 base unit (0.000001 USDT_ERC20 = 1e-6) must not cause
    floating-point drift or conservation failure.
    """
    victim_val = Decimal("0.000001")   # 1 satoshi of USDT
    engine = AccountBasedAttributionEngine(victim_val, Asset.USDT_ERC20)

    outgoing = [
        _make_transfer("0xtx_1sat", "0x_dest_min", Decimal("0.000001"), asset=Asset.USDT_ERC20),
    ]

    result = engine.allocate(Decimal("0.000000"), outgoing)

    for model in AllocationModel:
        total = sum(result[model].values())
        assert total <= victim_val, (
            f"{model}: conservation violated for minimum representable USDT unit. "
            f"Allocated {total} > {victim_val}."
        )
        # The allocation must be non-zero (not silently dropped)
        assert total > Decimal("0"), (
            f"{model}: minimum-unit transfer allocation was zero. "
            "Micro-amounts must not be silently discarded."
        )
