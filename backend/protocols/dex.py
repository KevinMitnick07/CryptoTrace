"""
DEX protocol semantics and token metadata resolution.

A DEX interaction must not be treated as a fund termination. When funds enter
a recognized router contract, the adapter parses the swap event to determine:
  - input asset, contract, raw amount, and exact decimals
  - output asset, contract, raw amount, and exact decimals
  - recipient address
  - protocol used
"""

from __future__ import annotations
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
import datetime

from ..core.models import Chain, Asset, DexTransformation, EvidenceClass, ASSET_DECIMALS

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known router addresses — protocol registry
# ---------------------------------------------------------------------------

@dataclass
class RouterEntry:
    address: str          # lowercase for Ethereum; Base58Check lower for TRON
    protocol: str
    chain: Chain
    version: str
    requires_live_verification: bool = False  # True = address needs live-chain confirmation before forensic use

ROUTER_REGISTRY: list[RouterEntry] = [
    # Ethereum — Uniswap — verified contract addresses
    RouterEntry("0x7a250d5630b4cf539739df2c5dacb4c659f2488d", "uniswap_v2", Chain.ETHEREUM, "v2"),
    RouterEntry("0xe592427a0aece92de3edee1f18e0157c05861564", "uniswap_v3", Chain.ETHEREUM, "v3"),
    RouterEntry("0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45", "uniswap_v3", Chain.ETHEREUM, "v3_02"),
    # TRON — SunSwap V2 — requires live TRONGrid confirmation before treating as forensic evidence.
    # Address: TXF4UzjyHFDcxFUGqhDDKaUWdGNDuZhEg8 is the published SunSwap V2 router on TRON mainnet.
    # Use scripts/validate_live_tron.py to confirm this contract is active before relying on it.
    RouterEntry("TXF4UzjyHFDcxFUGqhDDKaUWdGNDuZhEg8".lower(), "sunswap_v2", Chain.TRON, "v2", requires_live_verification=True),
]

_ROUTER_LOOKUP: dict[tuple[Chain, str], RouterEntry] = {
    (r.chain, r.address.lower()): r for r in ROUTER_REGISTRY
}


def is_known_router(chain: Chain, address: str) -> bool:
    return (chain, address.lower()) in _ROUTER_LOOKUP


def get_router(chain: Chain, address: str) -> Optional[RouterEntry]:
    return _ROUTER_LOOKUP.get((chain, address.lower()))


# ---------------------------------------------------------------------------
# Immutable Token Metadata Cache
# ---------------------------------------------------------------------------

KNOWN_TOKEN_METADATA: dict[tuple[Chain, str], tuple[Asset, int]] = {
    (Chain.ETHEREUM, "0xdac17f958d2ee523a2206206994597c13d831ec7"): (Asset.USDT_ERC20, 6),
    (Chain.ETHEREUM, "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"): (Asset.USDC_ERC20, 6),
    (Chain.ETHEREUM, "0x6b175474e89094c44da98b954eedeac495271d0f"): (Asset.DAI_ERC20, 18),
    (Chain.ETHEREUM, "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"): (Asset.ETH, 18),        # WETH
    (Chain.ETHEREUM, "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599"): (Asset.BTC, 8),          # WBTC
    (Chain.TRON, "tr7nhqjeqxgctci8q8zy4pl8otszgjlj6t"): (Asset.USDT_TRC20, 6),
}


def resolve_token_metadata(chain: Chain, contract_address: str) -> Optional[tuple[Asset, int]]:
    """Resolve token Asset enum and decimal count for contract address."""
    return KNOWN_TOKEN_METADATA.get((chain, contract_address.lower()))


# ---------------------------------------------------------------------------
# Event signatures
# ---------------------------------------------------------------------------

# Uniswap v2 Swap(address,uint256,uint256,uint256,uint256,address)
UNISWAP_V2_SWAP_TOPIC = "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"

# Uniswap v3 Swap(address,address,int256,int256,uint160,uint128,int24)
UNISWAP_V3_SWAP_TOPIC = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"


@dataclass
class RawLog:
    tx_hash: str
    contract_address: str
    topics: list[str]
    data: str
    log_index: int
    block_number: int
    block_timestamp: datetime.datetime


# ---------------------------------------------------------------------------
# Per-protocol parsers
# ---------------------------------------------------------------------------

def parse_uniswap_v2(
    router_tx_hash: str,
    router_address: str,
    swap_log: RawLog,
    recipient: str,
    chain: Chain,
    in_asset: Asset,
    in_amount: Decimal,
    out_token_contract: Optional[str] = None,
    usd_rate_in: Optional[Decimal] = None,
    usd_rate_out: Optional[Decimal] = None,
) -> Optional[DexTransformation]:
    """
    Uniswap v2 Swap event decoding with exact token decimal resolution.
    """
    try:
        data = swap_log.data.removeprefix("0x")
        if len(data) < 256:
            return None
        amount0_out = int(data[128:192], 16)
        amount1_out = int(data[192:256], 16)
        out_raw = amount0_out if amount0_out > 0 else amount1_out

        # Resolve output token metadata
        out_decimals = 18
        out_asset = Asset.UNKNOWN
        is_complete = True

        if out_token_contract:
            meta = resolve_token_metadata(chain, out_token_contract)
            if meta:
                out_asset, out_decimals = meta
            else:
                is_complete = False
        else:
            # If no pair contract specified, default to ETH pair standard
            out_asset = Asset.ETH
            out_decimals = 18

        out_amount = Decimal(out_raw) / (Decimal(10) ** out_decimals)

        return DexTransformation(
            tx_hash=router_tx_hash,
            chain=chain,
            protocol="uniswap_v2",
            router_address=router_address,
            input_asset=in_asset,
            input_amount=in_amount,
            output_asset=out_asset,
            output_amount=out_amount,
            recipient_address=recipient,
            fee_amount=in_amount * Decimal("0.003"),  # Uniswap v2 fee is 0.3%
            slippage_pct=None,
            block_timestamp=swap_log.block_timestamp,
            usd_rate_input=usd_rate_in,
            usd_rate_output=usd_rate_out,
            input_decimals=ASSET_DECIMALS.get(in_asset, 18),
            output_decimals=out_decimals,
            is_complete=is_complete,
            confidence=EvidenceClass.DERIVED if is_complete else EvidenceClass.ATTRIBUTED,
        )
    except Exception as exc:
        log.warning("Failed to parse Uniswap v2 swap log: %s", exc)
        return None


def parse_uniswap_v3(
    router_tx_hash: str,
    router_address: str,
    swap_log: RawLog,
    recipient: str,
    chain: Chain,
    in_asset: Asset,
    in_amount: Decimal,
    out_token_contract: Optional[str] = None,
    usd_rate_in: Optional[Decimal] = None,
    usd_rate_out: Optional[Decimal] = None,
) -> Optional[DexTransformation]:
    """
    Uniswap v3 Swap event decoding with exact token decimal resolution.
    Swap(address sender, address recipient, int256 amount0, int256 amount1, uint160 sqrtPriceX96, uint128 liquidity, int24 tick)
    """
    try:
        data = swap_log.data.removeprefix("0x")
        if len(data) < 128:
            return None

        # Two 256-bit signed integers: amount0, amount1
        raw0 = int(data[0:64], 16)
        raw1 = int(data[64:128], 16)
        # Convert two's complement for int256
        amount0 = raw0 - (1 << 256) if raw0 >= (1 << 255) else raw0
        amount1 = raw1 - (1 << 256) if raw1 >= (1 << 255) else raw1

        # Negative amount = output from pool to recipient
        out_raw = abs(amount0) if amount0 < 0 else abs(amount1)

        out_decimals = 18
        out_asset = Asset.UNKNOWN
        is_complete = True

        if out_token_contract:
            meta = resolve_token_metadata(chain, out_token_contract)
            if meta:
                out_asset, out_decimals = meta
            else:
                is_complete = False
        else:
            out_asset = Asset.ETH
            out_decimals = 18

        out_amount = Decimal(out_raw) / (Decimal(10) ** out_decimals)

        return DexTransformation(
            tx_hash=router_tx_hash,
            chain=chain,
            protocol="uniswap_v3",
            router_address=router_address,
            input_asset=in_asset,
            input_amount=in_amount,
            output_asset=out_asset,
            output_amount=out_amount,
            recipient_address=recipient,
            fee_amount=None,
            slippage_pct=None,
            block_timestamp=swap_log.block_timestamp,
            usd_rate_input=usd_rate_in,
            usd_rate_output=usd_rate_out,
            input_decimals=ASSET_DECIMALS.get(in_asset, 18),
            output_decimals=out_decimals,
            is_complete=is_complete,
            confidence=EvidenceClass.DERIVED if is_complete else EvidenceClass.ATTRIBUTED,
        )
    except Exception as exc:
        log.warning("Failed to parse Uniswap v3 swap log: %s", exc)
        return None


def interpret_dex_interaction(
    chain: Chain,
    router_address: str,
    tx_hash: str,
    recipient: str,
    in_asset: Asset,
    in_amount: Decimal,
    logs: list[RawLog],
    out_token_contract: Optional[str] = None,
) -> Optional[DexTransformation]:
    """
    Main dispatch for parsing DEX transformations from contract logs.
    """
    router = get_router(chain, router_address)
    if not router:
        return None

    for l in logs:
        if not l.topics:
            continue
        topic0 = l.topics[0].lower()
        if router.protocol == "uniswap_v2" and topic0 == UNISWAP_V2_SWAP_TOPIC:
            return parse_uniswap_v2(
                tx_hash, router_address, l, recipient, chain, in_asset, in_amount, out_token_contract
            )
        if router.protocol == "uniswap_v3" and topic0 == UNISWAP_V3_SWAP_TOPIC:
            return parse_uniswap_v3(
                tx_hash, router_address, l, recipient, chain, in_asset, in_amount, out_token_contract
            )
    return None
