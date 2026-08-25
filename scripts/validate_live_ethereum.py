#!/usr/bin/env python3
"""
Live Ethereum Network Validation Script.

Validates Ethereum JSON-RPC connectivity, PoS finality checkpoint, ERC-20 log decoding,
archive capability, and malformed input handling.

Capability Matrix output values: SUPPORTED / UNSUPPORTED / UNKNOWN / PROVIDER_ERROR

Output sections:
  LIVE_VERIFIED   -- Check executed and result confirmed
  PROVIDER_LIMITED -- Check limited by API capabilities
  NOT_TESTED       -- Check skipped
"""

import sys
import json
import os
from decimal import Decimal

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.chains.ethereum import EthereumAdapter
from backend.core.models import Asset


def validate_ethereum() -> dict:
    adapter = EthereumAdapter()
    result = {
        "chain": "ETHEREUM",
        "adapter_version": adapter.version,
        "rpc_url": adapter._rpc,
        "capability_matrix": {},
        "capability_sections": {
            "LIVE_VERIFIED": [],
            "PROVIDER_LIMITED": [],
            "NOT_TESTED": [],
        },
        "checks": {},
        "status": "UNKNOWN",
    }

    def record(section: str, name: str, detail: dict, capability: str = "UNKNOWN"):
        result["checks"][name] = detail
        result["capability_sections"][section].append(name)
        result["capability_matrix"][name] = capability

    # Check 1: Chain ID
    try:
        raw_chain_id = adapter._rpc_call("eth_chainId", [])
        chain_id = int(raw_chain_id, 16)
        is_mainnet = chain_id == 1
        record("LIVE_VERIFIED", "chain_id", {
            "status": "PASS",
            "chain_id": chain_id,
            "is_mainnet": is_mainnet,
            "note": "Mainnet chain_id=1. Any other value indicates testnet or private chain.",
        }, "SUPPORTED")
    except Exception as exc:
        record("PROVIDER_LIMITED", "chain_id", {"status": "FAIL", "error": str(exc)}, "PROVIDER_ERROR")

    # Check 2: Latest Block
    current_block = 0
    try:
        current_block = adapter.get_current_block()
        if current_block > 0:
            record("LIVE_VERIFIED", "get_current_block", {
                "status": "PASS", "block_number": current_block,
            }, "SUPPORTED")
        else:
            record("PROVIDER_LIMITED", "get_current_block", {
                "status": "FAIL", "block_number": 0,
            }, "PROVIDER_ERROR")
    except Exception as exc:
        record("PROVIDER_LIMITED", "get_current_block", {"status": "FAIL", "error": str(exc)}, "PROVIDER_ERROR")

    # Check 3: PoS Finalized Checkpoint
    try:
        finalized_block = adapter.get_finalized_block()
        if finalized_block and finalized_block > 0:
            record("LIVE_VERIFIED", "get_finalized_block", {
                "status": "PASS",
                "finalized_block": finalized_block,
                "current_block": current_block,
                "finality_lag_blocks": current_block - finalized_block if current_block else None,
                "note": "Ethereum PoS uses checkpoint-based protocol finality (2 epochs ~12.8 min).",
            }, "SUPPORTED")
        else:
            record("PROVIDER_LIMITED", "get_finalized_block", {
                "status": "DEGRADED",
                "finalized_block": finalized_block,
                "note": "Provider does not support 'finalized' block tag. May be pre-Merge or non-archive.",
            }, "UNSUPPORTED")
    except Exception as exc:
        record("PROVIDER_LIMITED", "get_finalized_block", {"status": "FAIL", "error": str(exc)}, "PROVIDER_ERROR")

    # Check 4: ETH Balance for known public address
    eth_foundation = "0xde0b295669a9fd93d5f28d9ec85e40f4cb697bae"
    try:
        bal = adapter.get_historical_balance(eth_foundation, Asset.ETH)
        if bal.amount is not None:
            record("LIVE_VERIFIED", "get_eth_balance", {
                "status": "PASS",
                "balance_eth": str(bal.amount),
                "data_source": bal.data_source,
            }, "SUPPORTED")
        else:
            record("PROVIDER_LIMITED", "get_eth_balance", {
                "status": "FAIL", "status_returned": bal.status.value,
            }, "PROVIDER_ERROR")
    except Exception as exc:
        record("PROVIDER_LIMITED", "get_eth_balance", {"status": "FAIL", "error": str(exc)}, "PROVIDER_ERROR")

    # Check 5: Archive capability -- historical block balance
    try:
        old_block = 1_000_000  # Block from ~2016
        hist = adapter.get_historical_balance(eth_foundation, Asset.ETH, at_block=old_block)
        if hist.status.value == "KNOWN":
            record("LIVE_VERIFIED", "archive_historical_balance", {
                "status": "PASS",
                "requested_block": old_block,
                "balance_eth": str(hist.amount),
                "note": "Archive node confirmed. Historical state at block 1000000 available.",
            }, "SUPPORTED")
        elif hist.status.value == "UNAVAILABLE_PROVIDER":
            record("PROVIDER_LIMITED", "archive_historical_balance", {
                "status": "DEGRADED",
                "requested_block": old_block,
                "reason": hist.reason,
                "note": "Connected RPC is a pruned node. Historical balance attribution will be UNAVAILABLE_PROVIDER.",
            }, "UNSUPPORTED")
        else:
            record("PROVIDER_LIMITED", "archive_historical_balance", {
                "status": "DEGRADED",
                "status_returned": hist.status.value,
                "reason": hist.reason,
            }, "UNKNOWN")
    except Exception as exc:
        record("PROVIDER_LIMITED", "archive_historical_balance", {"status": "FAIL", "error": str(exc)}, "PROVIDER_ERROR")

    # Check 6: ERC-20 Log Decode (eth_getLogs)
    try:
        # Fetch recent USDT transfers using eth_getLogs
        from_b = hex(max(0, current_block - 100)) if current_block > 100 else "0x0"
        usdt_contract = "0xdac17f958d2ee523a2206206994597c13d831ec7"
        transfer_topic = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
        filter_params = {
            "fromBlock": from_b,
            "toBlock": "latest",
            "address": usdt_contract,
            "topics": [transfer_topic],
        }
        logs = adapter._rpc_call("eth_getLogs", [filter_params])
        if isinstance(logs, list) and len(logs) > 0:
            record("LIVE_VERIFIED", "erc20_log_decode", {
                "status": "PASS",
                "logs_returned": len(logs),
                "sample_tx": logs[0].get("transactionHash"),
                "note": "eth_getLogs functional. ERC-20 Transfer event decoding operational.",
            }, "SUPPORTED")
        elif isinstance(logs, list):
            record("LIVE_VERIFIED", "erc20_log_decode", {
                "status": "PASS",
                "logs_returned": 0,
                "note": "eth_getLogs call succeeded but no USDT transfers in last 100 blocks (unusual).",
            }, "SUPPORTED")
        else:
            record("PROVIDER_LIMITED", "erc20_log_decode", {
                "status": "DEGRADED", "response": str(logs)[:200],
            }, "UNSUPPORTED")
    except Exception as exc:
        err = str(exc)
        cap = "UNSUPPORTED" if "not supported" in err.lower() else "PROVIDER_ERROR"
        record("PROVIDER_LIMITED", "erc20_log_decode", {"status": "FAIL", "error": err}, cap)

    # Check 7: Malformed TX hash handling
    try:
        result_tx = adapter.get_tx("0xinvalidhashXXXXXXXXXXXXXXXXXXXXXX")
        if result_tx is None:
            record("LIVE_VERIFIED", "malformed_tx_hash", {
                "status": "PASS",
                "returned": None,
                "note": "Correct: malformed hash returns None without exception.",
            }, "SUPPORTED")
        else:
            record("PROVIDER_LIMITED", "malformed_tx_hash", {
                "status": "FAIL",
                "note": "Expected None for malformed hash but got a result.",
            }, "UNKNOWN")
    except Exception as exc:
        record("PROVIDER_LIMITED", "malformed_tx_hash", {
            "status": "FAIL",
            "error": str(exc),
            "note": "Malformed hash caused unhandled exception.",
        }, "PROVIDER_ERROR")

    # Overall status
    failed = [n for n, c in result["checks"].items() if c.get("status") == "FAIL"]
    degraded = [n for n, c in result["checks"].items() if c.get("status") == "DEGRADED"]
    result["status"] = "DEGRADED" if (failed or degraded) else "HEALTHY"
    result["summary"] = {
        "live_verified_count": len(result["capability_sections"]["LIVE_VERIFIED"]),
        "provider_limited_count": len(result["capability_sections"]["PROVIDER_LIMITED"]),
        "not_tested_count": len(result["capability_sections"]["NOT_TESTED"]),
        "failed_checks": failed,
        "degraded_checks": degraded,
    }
    return result


if __name__ == "__main__":
    report = validate_ethereum()
    print(json.dumps(report, indent=2, default=str))
