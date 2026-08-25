"""
Tests for DEX decimal scaling and token metadata resolution.
"""

from decimal import Decimal
import datetime
import pytest

from backend.core.models import Chain, Asset, utc_now
from backend.protocols.dex import (
    parse_uniswap_v2, parse_uniswap_v3, RawLog, resolve_token_metadata, is_known_router
)


def test_token_metadata_registry():
    # USDT ERC-20 has 6 decimals
    meta_usdt = resolve_token_metadata(Chain.ETHEREUM, "0xdac17f958d2ee523a2206206994597c13d831ec7")
    assert meta_usdt == (Asset.USDT_ERC20, 6)

    # DAI ERC-20 has 18 decimals
    meta_dai = resolve_token_metadata(Chain.ETHEREUM, "0x6b175474e89094c44da98b954eedeac495271d0f")
    assert meta_dai == (Asset.DAI_ERC20, 18)


def test_uniswap_v2_decimal_scaling_usdt_to_dai():
    now = utc_now()
    # Mock Uniswap v2 Swap event: 10,000 USDT (in) -> 10,000 * 10^18 DAI (out)
    # amount0In = 0, amount1In = 0, amount0Out = 10,000 * 10^18, amount1Out = 0
    dai_raw_out = 10000 * (10 ** 18)
    data_hex = "0x" + ("0" * 64) + ("0" * 64) + f"{dai_raw_out:064x}" + ("0" * 64)

    raw_log = RawLog(
        tx_hash="0x_swap_tx",
        contract_address="0x_pair_usdt_dai",
        topics=["0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"],
        data=data_hex,
        log_index=1,
        block_number=15000000,
        block_timestamp=now,
    )

    swap = parse_uniswap_v2(
        router_tx_hash="0x_router_tx",
        router_address="0x7a250d5630b4cf539739df2c5dacb4c659f2488d",
        swap_log=raw_log,
        recipient="0x_swapper",
        chain=Chain.ETHEREUM,
        in_asset=Asset.USDT_ERC20,
        in_amount=Decimal("10000.00"),
        out_token_contract="0x6b175474e89094c44da98b954eedeac495271d0f", # DAI
    )

    assert swap is not None
    assert swap.output_asset == Asset.DAI_ERC20
    assert swap.output_decimals == 18
    assert swap.output_amount == Decimal("10000.00")
