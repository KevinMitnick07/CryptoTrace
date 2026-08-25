#!/usr/bin/env python3
"""
Live TRON Network Validation Script.

Validates TRONGrid connectivity, TRC-20 event parsing, and solidification status.
Returns structured JSON error taxonomy without crashing.
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
    adapter = TronAdapter()
    result = {
        "chain": "TRON",
        "adapter_version": adapter.version,
        "api_key_configured": bool(os.getenv("TRONGRID_API_KEY")),
        "checks": {},
        "status": "UNKNOWN",
    }

    # Check 1: Latest Block
    try:
        current_block = adapter.get_current_block()
        result["checks"]["get_current_block"] = {
            "status": "PASS" if current_block > 0 else "FAIL",
            "block_number": current_block,
        }
    except Exception as exc:
        result["checks"]["get_current_block"] = {
            "status": "FAIL",
            "error": str(exc),
        }

    # Check 2: Solidified Block
    try:
        solid_block = adapter.get_solidified_block()
        result["checks"]["get_solidified_block"] = {
            "status": "PASS" if solid_block and solid_block > 0 else "FAIL",
            "solidified_block": solid_block,
        }
    except Exception as exc:
        result["checks"]["get_solidified_block"] = {
            "status": "FAIL",
            "error": str(exc),
        }

    # Check 3: Known Public Address Transfers (Tether Treasury on TRON)
    test_addr = "TKHuVq1oKVruCGLvqVexFs6dawKv6fQgFs"  # Known Tether Treasury TRON
    try:
        transfers = adapter.get_transfers_from(test_addr, asset=Asset.USDT_TRC20, limit=5)
        result["checks"]["get_transfers_from"] = {
            "status": "PASS",
            "transfers_fetched": len(transfers),
            "sample_tx": transfers[0].tx_hash if transfers else None,
        }
    except Exception as exc:
        result["checks"]["get_transfers_from"] = {
            "status": "FAIL",
            "error": str(exc),
        }

    # Check 4: Historical Balance Status
    try:
        hist_bal = adapter.get_historical_balance(test_addr, Asset.USDT_TRC20, at_block=50000000)
        result["checks"]["get_historical_balance_check"] = {
            "status": "PASS" if hist_bal.status.value == "UNAVAILABLE_PROVIDER" else "FAIL",
            "returned_status": hist_bal.status.value,
            "provider_reason": hist_bal.reason,
        }
    except Exception as exc:
        result["checks"]["get_historical_balance_check"] = {
            "status": "FAIL",
            "error": str(exc),
        }

    # Determine overall status
    all_passed = all(c.get("status") == "PASS" for c in result["checks"].values())
    result["status"] = "HEALTHY" if all_passed else "DEGRADED"
    return result


if __name__ == "__main__":
    report = validate_tron()
    print(json.dumps(report, indent=2))
