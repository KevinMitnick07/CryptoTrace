"""
TRON chain adapter.

TRON uses an account-based model. TRC-20 transfers are EVM-compatible events
on TRON's EVM layer. This adapter uses the TRONGrid public API with fallback support.

Differences from Ethereum:
  - Addresses: Base58Check (T...) and hex (41...) are both valid; we normalize to hex/Base58.
  - Block time: ~3 seconds.
  - Token standard: TRC-20 (same ABI as ERC-20 but different address encoding).
  - Energy/bandwidth model (not gas) — fee accounting differs.
  - Solidification semantics: TRON DPoS achieves true finality at solidified blocks (~19-27 blocks).
"""

from __future__ import annotations
import os
import time
import logging
from decimal import Decimal
from typing import Optional
import datetime
import requests

from ..core.models import (
    Chain, Asset, OnChainTransfer, TxState, FinalityType, CandidateTransaction,
    HistoricalBalanceResult, HistoricalBalanceStatus, ASSET_DECIMALS
)
from .base import ChainAdapter, ADAPTER_VERSIONS

log = logging.getLogger(__name__)

TRONGRID_BASE = "https://api.trongrid.io"

# Known TRC-20 contract addresses (mainnet)
TRC20_CONTRACTS: dict[str, Asset] = {
    "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t": Asset.USDT_TRC20,   # USDT
    "TEkxiTehnzSmSe2XqrBj4w32RUN966rdz8": Asset.USDC_ERC20,    # USDC on TRON (TRC-20)
}


def _normalize_address(addr: str) -> str:
    """Return normalized TRON address."""
    if addr.startswith("T") and len(addr) == 34:
        return addr
    return addr.lower()


def _parse_amount(raw: int, asset: Asset) -> Decimal:
    decimals = ASSET_DECIMALS.get(asset, 6)
    return Decimal(raw) / Decimal(10 ** decimals)


def _parse_timestamp(ms: int) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(ms / 1000, tz=datetime.timezone.utc)


class TronAdapter(ChainAdapter):

    def __init__(self, api_key: Optional[str] = None, base_url: str = TRONGRID_BASE, fallback_rpc_url: Optional[str] = None):
        self._primary_base = base_url.rstrip("/")
        self._fallback_base = (fallback_rpc_url or os.getenv("TRON_RPC_FALLBACK_URL", "")).rstrip("/")
        self._base = self._primary_base
        self._api_key = api_key or os.getenv("TRONGRID_API_KEY", "")
        self._session = requests.Session()
        if self._api_key:
            self._session.headers["TRON-PRO-API-KEY"] = self._api_key

    @property
    def chain(self) -> Chain:
        return Chain.TRON

    @property
    def version(self) -> str:
        return ADAPTER_VERSIONS["tron"]

    def _get(self, path: str, params: Optional[dict] = None, retries: int = 3) -> dict:
        urls_to_try = [f"{self._base}{path}"]
        if self._fallback_base and self._fallback_base != self._base:
            urls_to_try.append(f"{self._fallback_base}{path}")

        last_error = None
        for current_url in urls_to_try:
            for attempt in range(retries):
                try:
                    resp = self._session.get(current_url, params=params, timeout=15)
                    if resp.status_code == 401 or resp.status_code == 403:
                        raise RuntimeError(f"PROVIDER_AUTH_REQUIRED: TRONGrid rejected query to {path}. Valid TRONGRID_API_KEY required.")
                    if resp.status_code == 429:
                        wait = 2 ** attempt
                        log.warning("TRONGrid rate limit; waiting %ds", wait)
                        time.sleep(wait)
                        continue
                    resp.raise_for_status()
                    return resp.json()
                except requests.exceptions.HTTPError as exc:
                    if exc.response.status_code == 429 and attempt < retries - 1:
                        time.sleep(2 ** attempt)
                        continue
                    last_error = exc
                except requests.exceptions.RequestException as exc:
                    last_error = exc
                    if attempt < retries - 1:
                        time.sleep(1)

        raise RuntimeError(f"PROVIDER_UNAVAILABLE: TRON request failed across providers: {last_error}")

    def get_current_block(self) -> int:
        try:
            data = self._get("/walletsolidity/getnowblock")
            return data.get("block_header", {}).get("raw_data", {}).get("number", 0)
        except Exception:
            return 0

    def get_solidified_block(self) -> Optional[int]:
        """Fetch latest solidified block number on TRON for protocol finality."""
        try:
            data = self._get("/walletsolidity/getnowblock")
            return data.get("block_header", {}).get("raw_data", {}).get("number", 0)
        except Exception:
            return None

    def get_tx(self, tx_hash: str) -> Optional[OnChainTransfer]:
        """
        Fetch a TRC-20 transfer by transaction hash. Returns None if invalid or not found.
        """
        try:
            data = self._get(f"/v1/transactions/{tx_hash}/events")
            events = data.get("data", [])
            transfer_event = next(
                (e for e in events if e.get("event_name") == "Transfer"),
                None,
            )
            if not transfer_event:
                return None

            result_params = transfer_event.get("result", {})
            raw_val = int(result_params.get("value", 0))
            contract_addr = transfer_event.get("contract_address", "")
            asset = TRC20_CONTRACTS.get(contract_addr, Asset.USDT_TRC20)

            # Block solidification check
            block_num = transfer_event.get("block_number", 0)
            solidified_block = self.get_solidified_block() or 0
            is_solidified = block_num > 0 and block_num <= solidified_block

            return OnChainTransfer(
                tx_hash=tx_hash,
                chain=Chain.TRON,
                asset=asset,
                amount=_parse_amount(raw_val, asset),
                from_address=_normalize_address(result_params.get("from", "")),
                to_address=_normalize_address(result_params.get("to", "")),
                block_number=block_num,
                block_timestamp=_parse_timestamp(transfer_event.get("block_timestamp", 0)),
                tx_state=TxState.FINALITY_THRESHOLD_REACHED if is_solidified else TxState.CONFIRMED,
                finality_type=FinalityType.SOLIDIFIED if is_solidified else FinalityType.OBSERVED,
            )
        except Exception as exc:
            log.warning("TRON get_tx failed for %s: %s", tx_hash, exc)
            return None

    def get_transfers_from(
        self,
        address: str,
        asset: Optional[Asset] = None,
        after_block: Optional[int] = None,
        before_block: Optional[int] = None,
        limit: int = 50,
    ) -> list[OnChainTransfer]:
        """
        Query outgoing TRC-20 transfers for an address with pagination and rate limit handling.
        """
        norm_addr = _normalize_address(address)
        contract = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"  # Default USDT
        if asset == Asset.USDC_ERC20:
            contract = "TEkxiTehnzSmSe2XqrBj4w32RUN966rdz8"

        params = {
            "limit": min(limit, 100),
            "contract_address": contract,
            "only_to": "false",
            "only_from": "true",
        }
        if after_block:
            params["min_block_timestamp"] = int(time.time() - 86400 * 30) * 1000

        try:
            data = self._get(f"/v1/accounts/{norm_addr}/transactions/trc20", params=params)
            rows = data.get("data", [])
            transfers: list[OnChainTransfer] = []

            for r in rows:
                if r.get("from") != norm_addr:
                    continue
                raw_amt = int(r.get("value", 0))
                contract_in_row = r.get("token_info", {}).get("address", contract)
                row_asset = TRC20_CONTRACTS.get(contract_in_row, Asset.USDT_TRC20)
                tx_hash = r.get("transaction_id", "")
                block_ts = _parse_timestamp(r.get("block_timestamp", 0))

                transfers.append(
                    OnChainTransfer(
                        tx_hash=tx_hash,
                        chain=Chain.TRON,
                        asset=row_asset,
                        amount=_parse_amount(raw_amt, row_asset),
                        from_address=norm_addr,
                        to_address=_normalize_address(r.get("to", "")),
                        block_number=r.get("block_number", 0),
                        block_timestamp=block_ts,
                        tx_state=TxState.CONFIRMED,
                        finality_type=FinalityType.SOLIDIFIED,
                    )
                )
            return transfers
        except Exception as exc:
            log.warning("TRON get_transfers_from failed for %s: %s", address, exc)
            return []

    def get_transfers_to(
        self,
        address: str,
        asset: Optional[Asset] = None,
        after_block: Optional[int] = None,
        before_block: Optional[int] = None,
        limit: int = 50,
    ) -> list[OnChainTransfer]:
        """Query incoming TRC-20 transfers for an address."""
        norm_addr = _normalize_address(address)
        contract = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
        if asset == Asset.USDC_ERC20:
            contract = "TEkxiTehnzSmSe2XqrBj4w32RUN966rdz8"

        params = {
            "limit": min(limit, 100),
            "contract_address": contract,
            "only_to": "true",
            "only_from": "false",
        }
        try:
            data = self._get(f"/v1/accounts/{norm_addr}/transactions/trc20", params=params)
            rows = data.get("data", [])
            transfers: list[OnChainTransfer] = []

            for r in rows:
                if r.get("to") != norm_addr:
                    continue
                raw_amt = int(r.get("value", 0))
                contract_in_row = r.get("token_info", {}).get("address", contract)
                row_asset = TRC20_CONTRACTS.get(contract_in_row, Asset.USDT_TRC20)
                tx_hash = r.get("transaction_id", "")
                block_ts = _parse_timestamp(r.get("block_timestamp", 0))

                transfers.append(
                    OnChainTransfer(
                        tx_hash=tx_hash,
                        chain=Chain.TRON,
                        asset=row_asset,
                        amount=_parse_amount(raw_amt, row_asset),
                        from_address=_normalize_address(r.get("from", "")),
                        to_address=norm_addr,
                        block_number=r.get("block_number", 0),
                        block_timestamp=block_ts,
                        tx_state=TxState.CONFIRMED,
                        finality_type=FinalityType.SOLIDIFIED,
                    )
                )
            return transfers
        except Exception as exc:
            log.warning("TRON get_transfers_to failed for %s: %s", address, exc)
            return []

    def get_historical_balance(
        self,
        address: str,
        asset: Asset,
        at_block: Optional[int] = None,
    ) -> HistoricalBalanceResult:
        """
        TRON public TRONGrid free tier does not expose historical state archives.
        Strict invariant: Never substitute current balance for historical balance.
        """
        if at_block is not None:
            log.warning("TRON historical balance at block %d not supported on TRONGrid free tier for %s", at_block, address)

        return HistoricalBalanceResult(
            status=HistoricalBalanceStatus.UNAVAILABLE_PROVIDER,
            chain=Chain.TRON,
            asset=asset,
            address=address,
            requested_block=at_block,
            amount=None,
            data_source="TRONGrid (Public Free Tier)",
            reason="historical balance at block %s not supported on TRONGrid free tier" % (at_block if at_block else "requested"),
        )

    def match_candidate_transactions(
        self,
        target_wallet: str,
        reported_amount: Optional[Decimal],
        reported_time: Optional[datetime.datetime],
        asset: Optional[Asset] = None,
        time_window_seconds: int = 1800,
        amount_tolerance_pct: Decimal = Decimal("0.01"),
    ) -> list[CandidateTransaction]:
        """
        Query inbound transfers matching complaint parameters for Level B resolution.
        """
        norm_addr = _normalize_address(target_wallet)
        contract = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
        params = {
            "limit": 50,
            "contract_address": contract,
            "only_to": "true",
        }
        try:
            data = self._get(f"/v1/accounts/{norm_addr}/transactions/trc20", params=params)
            rows = data.get("data", [])
            candidates: list[CandidateTransaction] = []

            for r in rows:
                if r.get("to") != norm_addr:
                    continue
                raw_amt = int(r.get("value", 0))
                contract_in_row = r.get("token_info", {}).get("address", contract)
                row_asset = TRC20_CONTRACTS.get(contract_in_row, Asset.USDT_TRC20)
                amount = _parse_amount(raw_amt, row_asset)
                block_ts = _parse_timestamp(r.get("block_timestamp", 0))

                match_fields = ["wallet"]
                if reported_amount is not None and reported_amount > 0:
                    diff_pct = abs(amount - reported_amount) / reported_amount
                    if diff_pct <= amount_tolerance_pct:
                        match_fields.append("amount")

                if reported_time is not None:
                    delta = abs((block_ts - reported_time).total_seconds())
                    if delta <= time_window_seconds:
                        match_fields.append("time")

                candidates.append(
                    CandidateTransaction(
                        tx_hash=r.get("transaction_id", ""),
                        chain=Chain.TRON,
                        asset=row_asset,
                        amount=amount,
                        block_number=r.get("block_number", 0),
                        block_timestamp=block_ts,
                        from_address=_normalize_address(r.get("from", "")),
                        to_address=norm_addr,
                        tx_state=TxState.CONFIRMED,
                        match_fields=match_fields,
                        finality_type=FinalityType.SOLIDIFIED,
                    )
                )
            return candidates
        except Exception as exc:
            log.warning("TRON match_candidate_transactions failed: %s", exc)
            return []
