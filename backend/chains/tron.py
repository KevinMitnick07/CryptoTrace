"""
TRON chain adapter.

TRON uses an account-based model. TRC-20 transfers are EVM-compatible events
on TRON's EVM layer. This adapter uses the TRONGrid public API.

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

    def __init__(self, api_key: Optional[str] = None, base_url: str = TRONGRID_BASE):
        self._base = base_url.rstrip("/")
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
        url = f"{self._base}{path}"
        for attempt in range(retries):
            try:
                resp = self._session.get(url, params=params, timeout=15)
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
                raise
            except requests.exceptions.RequestException as exc:
                if attempt == retries - 1:
                    raise RuntimeError(f"PROVIDER_UNAVAILABLE: TRONGrid request failed: {exc}")
                time.sleep(1)
        raise RuntimeError(f"PROVIDER_TIMEOUT: TRONGrid request failed after {retries} attempts: {url}")

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
        except Exception:
            return None
        solidified = self.get_solidified_block()

        for event in events:
            if event.get("event_name") != "Transfer":
                continue
            contract_addr = event.get("contract_address", "")
            asset = TRC20_CONTRACTS.get(contract_addr)
            if asset is None:
                continue
            result = event.get("result", {})
            raw_value = int(result.get("value", "0"))
            amount = _parse_amount(raw_value, asset)
            block_number = event.get("block_number", 0)
            block_ts = _parse_timestamp(event.get("block_timestamp", 0))
            tx_state, finality_type = self.classify_tx_state(block_number, provider_finalized_block=solidified)
            return OnChainTransfer(
                tx_hash=tx_hash,
                chain=Chain.TRON,
                asset=asset,
                amount=amount,
                from_address=_normalize_address(result.get("from", "")),
                to_address=_normalize_address(result.get("to", "")),
                block_number=block_number,
                block_timestamp=block_ts,
                tx_state=tx_state,
                log_index=event.get("event_index"),
                finality_type=finality_type,
            )
        return None

    def get_transfers_from(
        self,
        address: str,
        asset: Optional["Asset"] = None,
        after_block: Optional[int] = None,
        before_block: Optional[int] = None,
        limit: int = 50,
    ) -> list[OnChainTransfer]:
        return self._fetch_trc20_transfers(
            address=address,
            asset=asset,
            direction="from",
            after_block=after_block,
            before_block=before_block,
            limit=limit,
        )

    def get_transfers_to(
        self,
        address: str,
        asset: Optional["Asset"] = None,
        after_block: Optional[int] = None,
        before_block: Optional[int] = None,
        limit: int = 50,
    ) -> list[OnChainTransfer]:
        return self._fetch_trc20_transfers(
            address=address,
            asset=asset,
            direction="to",
            after_block=after_block,
            before_block=before_block,
            limit=limit,
        )

    def _fetch_trc20_transfers(
        self,
        address: str,
        asset: Optional["Asset"],
        direction: str,
        after_block: Optional[int],
        before_block: Optional[int],
        limit: int,
    ) -> list[OnChainTransfer]:
        params: dict = {"limit": min(limit, 200)}

        if asset == Asset.USDT_TRC20:
            params["contract_address"] = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

        if direction == "from":
            params["only_from"] = "true"
        else:
            params["only_to"] = "true"

        solidified = self.get_solidified_block()
        results = []
        fingerprint = None

        while len(results) < limit:
            if fingerprint:
                params["fingerprint"] = fingerprint
            data = self._get(f"/v1/accounts/{address}/transactions/trc20", params=params)
            items = data.get("data", [])
            if not items:
                break
            for item in items:
                tx_hash = item.get("transaction_id", "")
                contract_addr = item.get("token_info", {}).get("address", "")
                mapped_asset = TRC20_CONTRACTS.get(contract_addr, Asset.UNKNOWN)
                decimals = int(item.get("token_info", {}).get("decimals", 6))
                raw_value = int(item.get("value", "0"))
                amount = Decimal(raw_value) / Decimal(10 ** decimals)
                block_ts = _parse_timestamp(int(item.get("block_timestamp", 0)))
                block_number = item.get("block", 0)
                tx_state, finality_type = self.classify_tx_state(block_number, provider_finalized_block=solidified)
                transfer = OnChainTransfer(
                    tx_hash=tx_hash,
                    chain=Chain.TRON,
                    asset=mapped_asset,
                    amount=amount,
                    from_address=_normalize_address(item.get("from", "")),
                    to_address=_normalize_address(item.get("to", "")),
                    block_number=block_number,
                    block_timestamp=block_ts,
                    tx_state=tx_state,
                    finality_type=finality_type,
                )
                results.append(transfer)
            meta = data.get("meta", {})
            fingerprint = meta.get("fingerprint")
            if not fingerprint or len(items) < params["limit"]:
                break

        return results[:limit]

    def get_historical_balance(
        self, address: str, asset: Asset, at_block: Optional[int] = None
    ) -> HistoricalBalanceResult:
        """
        Query account balance. Returns explicit UNAVAILABLE_PROVIDER on historical blocks.
        Never substitutes current balance for historical state.
        """
        if at_block is not None:
            log.warning(
                "TronAdapter.get_balance: historical balance at block %d not supported on TRONGrid free tier.",
                at_block,
            )
            return HistoricalBalanceResult(
                status=HistoricalBalanceStatus.UNAVAILABLE_PROVIDER,
                chain=Chain.TRON,
                asset=asset,
                address=address,
                requested_block=at_block,
                amount=None,
                data_source="TRONGrid Free Tier",
                reason="TRONGrid API does not support historical block-height balance queries without archival node.",
            )

        try:
            data = self._get(f"/v1/accounts/{address}")
            accounts = data.get("data", [])
            if not accounts:
                return HistoricalBalanceResult(
                    status=HistoricalBalanceStatus.KNOWN,
                    chain=Chain.TRON,
                    asset=asset,
                    address=address,
                    requested_block=None,
                    amount=Decimal(0),
                    data_source="TRONGrid Latest State",
                )
            account = accounts[0]
            amount = Decimal(0)
            if asset == Asset.TRX:
                raw = account.get("balance", 0)
                amount = _parse_amount(raw, Asset.TRX)
            else:
                for token in account.get("trc20", []):
                    for contract_addr, raw_str in token.items():
                        if TRC20_CONTRACTS.get(contract_addr) == asset:
                            amount = _parse_amount(int(raw_str), asset)
                            break
            return HistoricalBalanceResult(
                status=HistoricalBalanceStatus.KNOWN,
                chain=Chain.TRON,
                asset=asset,
                address=address,
                requested_block=None,
                amount=amount,
                data_source="TRONGrid Latest State",
            )
        except Exception as exc:
            return HistoricalBalanceResult(
                status=HistoricalBalanceStatus.UNKNOWN,
                chain=Chain.TRON,
                asset=asset,
                address=address,
                requested_block=None,
                amount=None,
                data_source="TRONGrid",
                reason=str(exc),
            )
