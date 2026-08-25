"""
Tests for token-aware value conservation and precision tolerances.
"""

from decimal import Decimal
import pytest

from backend.core.models import Asset, OnChainTransfer, TxState, Chain, ValueInterval, utc_now
from backend.core.attribution import AccountBasedAttributionEngine, get_asset_precision_tolerance, _value_conservation_check


def test_asset_precision_tolerances():
    # 6 decimals (USDT/USDC): 100 / 10^6 = 0.0001
    tol_6 = get_asset_precision_tolerance(Asset.USDT_ERC20)
    assert tol_6 == Decimal("0.0001")

    # 18 decimals (ETH/DAI): 100 / 10^18 = 10^-16
    tol_18 = get_asset_precision_tolerance(Asset.ETH)
    assert tol_18 == Decimal("0.0000000000000001")


def test_conservation_with_high_precision_fractions():
    # Victim value: 1.000000000000000001 ETH
    victim_val = Decimal("1.000000000000000001")
    engine = AccountBasedAttributionEngine(victim_val, Asset.ETH)

    now = utc_now()
    transfers = [
        OnChainTransfer(
            tx_hash="0x_tx1",
            chain=Chain.ETHEREUM,
            asset=Asset.ETH,
            amount=Decimal("0.333333333333333333"),
            from_address="0x_suspect",
            to_address="0x_dest1",
            block_number=100,
            block_timestamp=now,
            tx_state=TxState.CONFIRMED,
        ),
        OnChainTransfer(
            tx_hash="0x_tx2",
            chain=Chain.ETHEREUM,
            asset=Asset.ETH,
            amount=Decimal("0.666666666666666667"),
            from_address="0x_suspect",
            to_address="0x_dest2",
            block_number=101,
            block_timestamp=now,
            tx_state=TxState.CONFIRMED,
        ),
    ]

    res = engine.allocate(Decimal(0), transfers)
    violations = _value_conservation_check(victim_val, res, Asset.ETH)
    assert len(violations) == 0


def test_zero_or_negative_victim_deposit_rejection():
    with pytest.raises(ValueError, match="victim_value must be positive"):
        AccountBasedAttributionEngine(Decimal(0), Asset.USDT_TRC20)
    with pytest.raises(ValueError, match="victim_value must be positive"):
        AccountBasedAttributionEngine(Decimal("-10.00"), Asset.USDT_TRC20)


def test_value_interval_invariants():
    interval = ValueInterval(Decimal("100.00"), Decimal("500.00"), Asset.USDT_ERC20)
    assert interval.midpoint() == Decimal("300.00")
    assert interval.is_zero() is False
    assert interval.non_additive_across_hypotheses is True

    # Negative lower bound rejected
    with pytest.raises(ValueError, match="lower_bound cannot be negative"):
        ValueInterval(Decimal("-1.00"), Decimal("10.00"), Asset.USDT_ERC20)

    # Upper bound < lower bound rejected
    with pytest.raises(ValueError, match="upper_bound cannot be less than lower_bound"):
        ValueInterval(Decimal("20.00"), Decimal("10.00"), Asset.USDT_ERC20)
