"""
DEX protocol semantics and token metadata resolution.

A DEX interaction must not be treated as a fund termination or custodial VASP endpoint.
When funds enter a recognized router contract, the adapter parses the swap events to determine:
  - input asset, contract, raw amount, and exact decimals
  - output asset, contract, raw amount, and exact decimals
  - multi-hop ordered swap legs (e.g. USDT -> WETH -> USDC)
  - recipient address
  - protocol used
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
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
# Multi-Hop Ordered Swap Representation
# ---------------------------------------------------------------------------

@dataclass
class SwapLeg:
    """A single hop in a multi-hop DEX swap transaction."""
    leg_index: int
    pool_address: str
    token_in_contract: str
    token_out_contract: str
    token_in_asset: Asset
    token_out_asset: Asset
    amount_in_raw: int
    amount_out_raw: int
    amount_in_normalized: Decimal
    amount_out_normalized: Decimal
    input_decimals: int
    output_decimals: int
    evidence_class: EvidenceClass = EvidenceClass.DERIVED


@dataclass
class MultiLegSwapResult:
    """Ordered sequence of swap legs representing complete multi-hop DEX execution."""
    tx_hash: str
    chain: Chain
    router_address: str
    protocol: str
    legs: list[SwapLeg] = field(default_factory=list)
    initial_asset: Asset = Asset.UNKNOWN
    initial_amount: Decimal = Decimal(0)
    final_asset: Asset = Asset.UNKNOWN
    final_amount: Decimal = Decimal(0)
    recipient: str = ""
    block_timestamp: Optional[datetime.datetime] = None


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


def parse_multileg_swap(
    chain: Chain,
    router_address: str,
    tx_hash: str,
    recipient: str,
    initial_asset: Asset,
    initial_amount: Decimal,
    swap_logs: list[RawLog],
    leg_contracts: list[tuple[str, str]],  # List of (token_in_addr, token_out_addr) per leg
) -> Optional[MultiLegSwapResult]:
    """
    Parses an ordered sequence of swap logs into distinct legs without flattening into a single fake direct swap.
    """
    if not swap_logs:
        return None

    router = get_router(chain, router_address)
    protocol_name = router.protocol if router else "dex_router"

    legs: list[SwapLeg] = []
    current_amount = initial_amount
    current_asset = initial_asset

    for i, log_entry in enumerate(swap_logs):
        in_contract, out_contract = leg_contracts[i] if i < len(leg_contracts) else ("", "")

        in_meta = resolve_token_metadata(chain, in_contract) if in_contract else (current_asset, ASSET_DECIMALS.get(current_asset, 18))
        out_meta = resolve_token_metadata(chain, out_contract) if out_contract else (Asset.UNKNOWN, 18)

        leg_in_asset, in_decimals = in_meta if in_meta else (current_asset, 18)
        leg_out_asset, out_decimals = out_meta if out_meta else (Asset.UNKNOWN, 18)

        # Parse log for output amount
        data = log_entry.data.removeprefix("0x")
        out_raw = 0
        if len(data) >= 128:
            raw0 = int(data[0:64], 16)
            raw1 = int(data[64:128], 16)
            amount0 = raw0 - (1 << 256) if raw0 >= (1 << 255) else raw0
            amount1 = raw1 - (1 << 256) if raw1 >= (1 << 255) else raw1
            out_raw = abs(amount0) if amount0 < 0 else abs(amount1)

        out_amount = Decimal(out_raw) / (Decimal(10) ** out_decimals) if out_raw > 0 else current_amount

        legs.append(
            SwapLeg(
                leg_index=i + 1,
                pool_address=log_entry.contract_address,
                token_in_contract=in_contract,
                token_out_contract=out_contract,
                token_in_asset=leg_in_asset,
                token_out_asset=leg_out_asset,
                amount_in_raw=int(current_amount * (10 ** in_decimals)),
                amount_out_raw=out_raw,
                amount_in_normalized=current_amount,
                amount_out_normalized=out_amount,
                input_decimals=in_decimals,
                output_decimals=out_decimals,
                evidence_class=EvidenceClass.DERIVED,
            )
        )

        current_amount = out_amount
        current_asset = leg_out_asset

    first_ts = swap_logs[0].block_timestamp if swap_logs else utc_now()

    return MultiLegSwapResult(
        tx_hash=tx_hash,
        chain=chain,
        router_address=router_address,
        protocol=protocol_name,
        legs=legs,
        initial_asset=initial_asset,
        initial_amount=initial_amount,
        final_asset=current_asset,
        final_amount=current_amount,
        recipient=recipient,
        block_timestamp=first_ts,
    )


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
    Fallback hierarchy:
      1. Multi-leg swap (ordered SwapLeg sequence)
      2. Single transformation (DexTransformation)
      3. Unresolved interaction (None)
    """
    router = get_router(chain, router_address)
    if not router or not logs:
        return None

    # Filter recognized swap logs
    swap_logs: list[RawLog] = []
    for l in logs:
        if not l.topics:
            continue
        topic0 = l.topics[0].lower()
        if topic0 in (UNISWAP_V2_SWAP_TOPIC, UNISWAP_V3_SWAP_TOPIC):
            swap_logs.append(l)

    if not swap_logs:
        return None

    # 1. Multi-leg swap handling if multiple swap events detected
    if len(swap_logs) > 1:
        leg_contracts = []
        for l in swap_logs:
            leg_contracts.append((out_token_contract or "", out_token_contract or ""))

        multileg_res = parse_multileg_swap(
            chain=chain,
            router_address=router_address,
            tx_hash=tx_hash,
            recipient=recipient,
            initial_asset=in_asset,
            initial_amount=in_amount,
            swap_logs=swap_logs,
            leg_contracts=leg_contracts,
        )
        if multileg_res and multileg_res.legs:
            legs_dict = [
                {
                    "leg_index": leg.leg_index,
                    "pool_address": leg.pool_address,
                    "token_in": leg.token_in_asset.value if hasattr(leg.token_in_asset, "value") else str(leg.token_in_asset),
                    "token_out": leg.token_out_asset.value if hasattr(leg.token_out_asset, "value") else str(leg.token_out_asset),
                    "amount_in": str(leg.amount_in_normalized),
                    "amount_out": str(leg.amount_out_normalized),
                    "input_decimals": leg.input_decimals,
                    "output_decimals": leg.output_decimals,
                }
                for leg in multileg_res.legs
            ]
            return DexTransformation(
                tx_hash=tx_hash,
                chain=chain,
                protocol=multileg_res.protocol,
                router_address=router_address,
                input_asset=in_asset,
                input_amount=in_amount,
                output_asset=multileg_res.final_asset,
                output_amount=multileg_res.final_amount,
                recipient_address=recipient,
                fee_amount=None,
                slippage_pct=None,
                block_timestamp=multileg_res.block_timestamp or utc_now(),
                usd_rate_input=None,
                usd_rate_output=None,
                input_decimals=ASSET_DECIMALS.get(in_asset, 18),
                output_decimals=ASSET_DECIMALS.get(multileg_res.final_asset, 18),
                is_complete=True,
                confidence=EvidenceClass.DERIVED,
                legs=legs_dict,
            )

    # 2. Single swap log fallback
    single_log = swap_logs[0]
    topic0 = single_log.topics[0].lower()
    if router.protocol == "uniswap_v2" and topic0 == UNISWAP_V2_SWAP_TOPIC:
        return parse_uniswap_v2(
            tx_hash, router_address, single_log, recipient, chain, in_asset, in_amount, out_token_contract
        )
    if router.protocol == "uniswap_v3" and topic0 == UNISWAP_V3_SWAP_TOPIC:
        return parse_uniswap_v3(
            tx_hash, router_address, single_log, recipient, chain, in_asset, in_amount, out_token_contract
        )

    return None
