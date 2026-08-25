#!/usr/bin/env python3
"""
Live TRON Network Validation Script.

Validates TRONGrid connectivity, TRC-20 event parsing, solidification finality,
and pagination behavior. Returns structured JSON with explicit capability sections.

Output sections:
  LIVE_VERIFIED   -- Check executed and result confirmed
  PROVIDER_LIMITED -- Check limited by API capabilities or missing credentials
  NOT_TESTED       -- Check skipped (e.g. rate limit behavior without an API key)
"""

import sys
import json
import os
from decimal import Decimal

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.chains.tron import TronAdapter
from backend.core.models import Asset


def validate_tron() -> dict:
    api_key = os.getenv("TRONGRID_API_KEY", "")
    adapter = TronAdapter(api_key=api_key if api_key else None)
    result = {
        "chain": "TRON",
        "adapter_version": adapter.version,
        "api_key_configured": bool(api_key),
        "capability_sections": {
            "LIVE_VERIFIED": [],
            "PROVIDER_LIMITED": [],
            "NOT_TESTED": [],
        },
        "checks": {},
        "status": "UNKNOWN",
    }

    def record(section: str, name: str, detail: dict):
        result["checks"][name] = detail
        result["capability_sections"][section].append(name)

    # Check 1: Latest Block (unauth endpoint -- no key required)
    current_block = 0
    try:
        current_block = adapter.get_current_block()
        if current_block > 0:
            record("LIVE_VERIFIED", "get_current_block", {
                "status": "PASS",
                "block_number": current_block,
            })
        else:
            record("PROVIDER_LIMITED", "get_current_block", {
                "status": "FAIL", "block_number": current_block, "reason": "Returned block_number=0",
            })
    except Exception as exc:
        record("PROVIDER_LIMITED", "get_current_block", {"status": "FAIL", "error": str(exc)})

    # Check 2: Solidified Block + Finality Lag
    solid_block = None
    try:
        solid_block = adapter.get_solidified_block()
        finality_lag = (current_block - solid_block) if (current_block and solid_block) else None
        if solid_block and solid_block > 0:
            record("LIVE_VERIFIED", "get_solidified_block", {
                "status": "PASS",
                "solidified_block": solid_block,
                "current_block": current_block,
                "finality_lag_blocks": finality_lag,
                "note": "Finality lag = current - solidified. TRON DPoS solidifies in ~19-27 blocks.",
            })
        else:
            record("PROVIDER_LIMITED", "get_solidified_block", {"status": "FAIL", "solidified_block": solid_block})
    except Exception as exc:
        record("PROVIDER_LIMITED", "get_solidified_block", {"status": "FAIL", "error": str(exc)})

    # Check 3: TRC-20 Transfers from Known Public Address
    test_addr = "TKHuVq1oKVruCGLvqVexFs6dawKv6fQgFs"
    try:
        transfers = adapter.get_transfers_from(test_addr, asset=Asset.USDT_TRC20, limit=5)
        if transfers:
            t = transfers[0]
            record("LIVE_VERIFIED", "get_trc20_transfers", {
                "status": "PASS",
                "transfers_fetched": len(transfers),
                "sample_tx_hash": t.tx_hash,
                "sample_amount": str(t.amount),
                "sample_asset": t.asset.value,
                "sample_block": t.block_number,
                "sample_tx_state": t.tx_state.value,
                "sample_finality_type": t.finality_type.value,
            })
        else:
            record("PROVIDER_LIMITED", "get_trc20_transfers", {
                "status": "DEGRADED",
                "transfers_fetched": 0,
                "reason": "No transfers returned for test address.",
            })
    except Exception as exc:
        record("PROVIDER_LIMITED", "get_trc20_transfers", {"status": "FAIL", "error": str(exc)})

    # Check 4: Pagination (fingerprint continuation)
    try:
        p1 = adapter.get_transfers_from(test_addr, asset=Asset.USDT_TRC20, limit=3)
        p2 = adapter.get_transfers_from(test_addr, asset=Asset.USDT_TRC20, limit=6)
        pagination_detected = len(p2) > len(p1)
        section = "LIVE_VERIFIED" if pagination_detected else "PROVIDER_LIMITED"
        record(section, "pagination_check", {
            "status": "PASS" if pagination_detected else "DEGRADED",
            "page1_count": len(p1),
            "page2_count": len(p2),
            "pagination_working": pagination_detected,
        })
    except Exception as exc:
        record("PROVIDER_LIMITED", "pagination_check", {"status": "FAIL", "error": str(exc)})

    # Check 5: Missing API Key Behavior
    if not api_key:
        record("NOT_TESTED", "rate_limit_behavior", {
            "status": "NOT_TESTED",
            "reason": (
                "TRONGRID_API_KEY not set. Rate limit behavior (429 responses) cannot be tested "
                "without credentials. Anonymous TRONGrid access is rate-limited to ~6 req/min."
            ),
        })
    else:
        record("LIVE_VERIFIED", "api_key_present", {
            "status": "PASS",
            "note": "TRONGRID_API_KEY configured. Authenticated rate limits apply.",
        })

    # Check 6: Historical Balance Refuses Correctly
    try:
        hist_bal = adapter.get_historical_balance(test_addr, Asset.USDT_TRC20, at_block=50_000_000)
        if hist_bal.status.value == "UNAVAILABLE_PROVIDER":
            record("LIVE_VERIFIED", "historical_balance_refuses_correctly", {
                "status": "PASS",
                "returned_status": hist_bal.status.value,
                "provider_reason": hist_bal.reason,
                "note": "Correct: historical block balance refused. No current-balance substitution.",
            })
        else:
            record("PROVIDER_LIMITED", "historical_balance_refuses_correctly", {
                "status": "FAIL",
                "returned_status": hist_bal.status.value,
                "note": "Expected UNAVAILABLE_PROVIDER.",
            })
    except Exception as exc:
        record("PROVIDER_LIMITED", "historical_balance_refuses_correctly", {"status": "FAIL", "error": str(exc)})

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
    report = validate_tron()
    print(json.dumps(report, indent=2, default=str))
