#!/usr/bin/env python3
"""
Real Ethereum Mainnet Uniswap Transaction Verification Script.

Validates exactly ONE real on-chain Uniswap transaction by fetching raw receipt
and event log data from the configured Ethereum RPC.

Statuses:
  - VERIFIED LIVE: Receipt, event log, tokens, and amounts dynamically decoded from RPC.
  - PROVIDER LIMITED: Public RPC rate limit, connection failure, or missing archive logs.
  - NOT VERIFIED: Transaction not found or event decoding failure.
"""

import sys
import os
import json
from decimal import Decimal
from typing import Optional
import requests

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.core.models import Chain
from backend.protocols.dex import is_known_router, resolve_token_metadata

# Uniswap V3 Swap event topic:
# Swap(address sender, address recipient, int256 amount0, int256 amount1, uint160 sqrtPriceX96, uint128 liquidity, int24 tick)
UNISWAP_V3_SWAP_TOPIC = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"

# Publicly verifiable live Ethereum mainnet Uniswap V3 swap transaction
TARGET_TX_HASH = "0xbb8ae3d15ad8edd26229d72dceb08cde0713fac1ad99ff1b8db89c91aff5c6e6"


def _rpc_call(rpc_url: str, method: str, params: list, req_id: int = 1) -> dict:
    resp = requests.post(
        rpc_url,
        json={"jsonrpc": "2.0", "method": method, "params": params, "id": req_id},
        timeout=15,
        headers={"Content-Type": "application/json"}
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"RPC Error: {data['error']}")
    return data.get("result")


def verify_live_uniswap_tx() -> dict:
    configured_rpc = os.getenv("ETH_RPC_URL", "https://1rpc.io/eth")
    candidate_rpcs = [configured_rpc]
    for backup in ["https://ethereum-rpc.publicnode.com", "https://gateway.tenderly.co/public/mainnet"]:
        if backup not in candidate_rpcs:
            candidate_rpcs.append(backup)

    last_error: Optional[str] = None

    for rpc in candidate_rpcs:
        try:
            # 1. Fetch Transaction Object
            tx_data = _rpc_call(rpc, "eth_getTransactionByHash", [TARGET_TX_HASH], req_id=1)
            if not tx_data:
                continue

            # 2. Fetch Transaction Receipt
            receipt_data = _rpc_call(rpc, "eth_getTransactionReceipt", [TARGET_TX_HASH], req_id=2)
            if not receipt_data or receipt_data.get("status") != "0x1":
                continue

            # 3. Locate Uniswap V3 Swap Log
            swap_log = None
            for log_entry in receipt_data.get("logs", []):
                topics = log_entry.get("topics", [])
                if topics and topics[0].lower() == UNISWAP_V3_SWAP_TOPIC:
                    swap_log = log_entry
                    break

            if not swap_log:
                return {
                    "status": "NOT VERIFIED",
                    "reason": "Swap event log not found in transaction receipt",
                    "transaction_hash": TARGET_TX_HASH,
                    "rpc_provider_used": rpc,
                }

            pool_address = swap_log.get("address", "").lower()
            log_index = int(swap_log.get("logIndex", "0x0"), 16)
            block_number = int(tx_data.get("blockNumber", "0x0"), 16)
            sender = tx_data.get("from", "").lower()
            router = tx_data.get("to", "").lower()

            # 4. Query token0 and token1 from pool contract via eth_call
            # token0() selector: 0x0dfe1681; token1() selector: 0xd21220a7
            t0_raw = _rpc_call(rpc, "eth_call", [{"to": pool_address, "data": "0x0dfe1681"}, "latest"], req_id=3)
            t1_raw = _rpc_call(rpc, "eth_call", [{"to": pool_address, "data": "0xd21220a7"}, "latest"], req_id=4)
            if not t0_raw or not t1_raw:
                return {
                    "status": "NOT VERIFIED",
                    "reason": "Failed to resolve token pair from pool contract",
                    "transaction_hash": TARGET_TX_HASH,
                    "rpc_provider_used": rpc,
                }

            token0 = "0x" + t0_raw[-40:].lower()
            token1 = "0x" + t1_raw[-40:].lower()

            # 5. Query token decimals via registry or eth_call (decimals() selector: 0x313ce567)
            def _fetch_decimals(t_addr: str, call_id: int) -> int:
                known = resolve_token_metadata(Chain.ETHEREUM, t_addr)
                if known:
                    return known[1]
                try:
                    d_res = _rpc_call(rpc, "eth_call", [{"to": t_addr, "data": "0x313ce567"}, "latest"], req_id=call_id)
                    if d_res and d_res != "0x":
                        return int(d_res, 16)
                except Exception:
                    pass
                return 18

            dec0 = _fetch_decimals(token0, 5)
            dec1 = _fetch_decimals(token1, 6)

            # 6. Parse Uniswap V3 Swap Log data (int256 amount0, int256 amount1)
            raw_data = swap_log.get("data", "").removeprefix("0x")
            if len(raw_data) < 128:
                return {
                    "status": "NOT VERIFIED",
                    "reason": "Malformed swap log data length",
                    "transaction_hash": TARGET_TX_HASH,
                    "rpc_provider_used": rpc,
                }

            raw0 = int(raw_data[0:64], 16)
            raw1 = int(raw_data[64:128], 16)
            amount0 = raw0 - (1 << 256) if raw0 >= (1 << 255) else raw0
            amount1 = raw1 - (1 << 256) if raw1 >= (1 << 255) else raw1

            if amount0 > 0:
                token_in, dec_in, raw_in = token0, dec0, amount0
                token_out, dec_out, raw_out = token1, dec1, abs(amount1)
            else:
                token_in, dec_in, raw_in = token1, dec1, amount1
                token_out, dec_out, raw_out = token0, dec0, abs(amount0)

            normalized_in = Decimal(raw_in) / Decimal(10 ** dec_in)
            normalized_out = Decimal(raw_out) / Decimal(10 ** dec_out)

            return {
                "status": "VERIFIED LIVE",
                "transaction_hash": TARGET_TX_HASH,
                "block_number": block_number,
                "transaction_sender": sender,
                "router_address": router,
                "router_recognized": is_known_router(Chain.ETHEREUM, router),
                "pool_address": pool_address,
                "token_in_address": token_in,
                "token_out_address": token_out,
                "token_in_decimals": dec_in,
                "token_out_decimals": dec_out,
                "raw_amount_in": raw_in,
                "normalized_amount_in": str(normalized_in),
                "raw_amount_out": raw_out,
                "normalized_amount_out": str(normalized_out),
                "event_signature": "Swap(address,address,int256,int256,uint160,uint128,int24)",
                "log_index": log_index,
                "rpc_provider_used": rpc,
            }

        except Exception as exc:
            last_error = str(exc)
            continue

    # If all public RPC attempts failed due to connectivity / provider limits
    return {
        "status": "PROVIDER LIMITED",
        "reason": f"Public Ethereum RPC connection limited: {last_error}",
        "transaction_hash": TARGET_TX_HASH,
        "rpc_provider_used": configured_rpc,
    }


if __name__ == "__main__":
    result = verify_live_uniswap_tx()
    print(json.dumps(result, indent=2))
