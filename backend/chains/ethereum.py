"""
Ethereum chain adapter.

Account-based model. ERC-20 transfers are emitted as Transfer(address,address,uint256)
events in the token contract's logs. This adapter uses a JSON-RPC endpoint.

Features:
  - Supports eth_getLogs for token event querying
  - Supports Ethereum PoS finalized block tag checking for deterministic finality
  - Returns structured HistoricalBalanceResult for archive-state transparency
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
    Chain, Asset, OnChainTransfer, TxState, FinalityType,
    HistoricalBalanceResult, HistoricalBalanceStatus, ASSET_DECIMALS
)
from .base import ChainAdapter, ADAPTER_VERSIONS

log = logging.getLogger(__name__)

# ERC-20 Transfer event topic
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# Known ERC-20 contracts (mainnet)
ERC20_CONTRACTS: dict[str, Asset] = {
    "0xdac17f958d2ee523a2206206994597c13d831ec7": Asset.USDT_ERC20,  # USDT
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": Asset.USDC_ERC20,  # USDC
    "0x6b175474e89094c44da98b954eedeac495271d0f": Asset.DAI_ERC20,   # DAI
}

ETH_RPC_DEFAULT = "https://eth.llamarpc.com"


class EthereumAdapter(ChainAdapter):

    def __init__(self, rpc_url: Optional[str] = None):
        self._rpc = rpc_url or os.getenv("ETH_RPC_URL", ETH_RPC_DEFAULT)
        self._session = requests.Session()
        self._session.headers["Content-Type"] = "application/json"
        self._id = 0

    @property
    def chain(self) -> Chain:
        return Chain.ETHEREUM

    @property
    def version(self) -> str:
        return ADAPTER_VERSIONS["ethereum"]

    def _rpc_call(self, method: str, params: list, retries: int = 3) -> object:
        self._id += 1
        payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": self._id}
        for attempt in range(retries):
            try:
                resp = self._session.post(self._rpc, json=payload, timeout=20)
                if resp.status_code == 429:
                    wait = 2 ** attempt
                    log.warning("Ethereum RPC rate limit; waiting %ds", wait)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                body = resp.json()
                if "error" in body:
                    err_msg = str(body["error"])
                    if "missing trie node" in err_msg.lower() or "header not found" in err_msg.lower() or "archive" in err_msg.lower():
                        raise RuntimeError(f"ARCHIVE_STATE_UNAVAILABLE: {err_msg}")
                    raise RuntimeError(f"RPC_ERROR: {err_msg}")
                return body["result"]
            except requests.exceptions.HTTPError as exc:
                if exc.response.status_code == 429 and attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise RuntimeError(f"PROVIDER_UNAVAILABLE: HTTP error from Ethereum RPC: {exc}")
            except requests.exceptions.RequestException as exc:
                if attempt == retries - 1:
                    raise RuntimeError(f"PROVIDER_UNAVAILABLE: Ethereum RPC connection failed: {exc}")
                time.sleep(1)
        raise RuntimeError(f"PROVIDER_TIMEOUT: RPC call {method} failed after {retries} attempts")

    def get_current_block(self) -> int:
        try:
            result = self._rpc_call("eth_blockNumber", [])
            return int(result, 16)
        except Exception:
            return 0

    def get_finalized_block(self) -> Optional[int]:
        """Query Ethereum PoS finalized checkpoint block number."""
        try:
            result = self._rpc_call("eth_getBlockByNumber", ["finalized", False])
            if result and "number" in result:
                return int(result["number"], 16)
        except Exception:
            pass
        return None

    def _block_timestamp(self, block_number: int) -> datetime.datetime:
        try:
            result = self._rpc_call("eth_getBlockByNumber", [hex(block_number), False])
            if result and "timestamp" in result:
                ts = int(result["timestamp"], 16)
                return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
        except Exception:
            pass
        return datetime.datetime.now(datetime.timezone.utc)

    def get_tx(self, tx_hash: str) -> Optional[OnChainTransfer]:
        """Fetch transaction receipt and parse ERC-20 Transfer log if present."""
        try:
            receipt = self._rpc_call("eth_getTransactionReceipt", [tx_hash])
        except Exception:
            return None

        if not receipt:
            return None
        if receipt.get("status") != "0x1":
            return None

        block_number = int(receipt.get("blockNumber", "0x0"), 16)
        block_ts = self._block_timestamp(block_number)
        finalized_block = self.get_finalized_block()
        tx_state, finality_type = self.classify_tx_state(block_number, provider_finalized_block=finalized_block)

        for log_entry in receipt.get("logs", []):
            topics = log_entry.get("topics", [])
            if not topics or topics[0].lower() != TRANSFER_TOPIC:
                continue
            contract_addr = log_entry.get("address", "").lower()
            asset = ERC20_CONTRACTS.get(contract_addr)
            if not asset:
                continue
            if len(topics) < 3:
                continue
            from_addr = "0x" + topics[1][-40:]
            to_addr = "0x" + topics[2][-40:]
            data_hex = log_entry.get("data", "0x0")
            raw_value = int(data_hex, 16) if data_hex != "0x" else 0
            decimals = ASSET_DECIMALS.get(asset, 18)
            amount = Decimal(raw_value) / Decimal(10 ** decimals)

            return OnChainTransfer(
                tx_hash=tx_hash,
                chain=Chain.ETHEREUM,
                asset=asset,
                amount=amount,
                from_address=from_addr.lower(),
                to_address=to_addr.lower(),
                block_number=block_number,
                block_timestamp=block_ts,
                tx_state=tx_state,
                log_index=int(log_entry.get("logIndex", "0x0"), 16),
                finality_type=finality_type,
            )
        return None

    def get_transfers_from(
        self,
        address: str,
        asset: Optional[Asset] = None,
        after_block: Optional[int] = None,
        before_block: Optional[int] = None,
        limit: int = 50,
    ) -> list[OnChainTransfer]:
        return self._fetch_erc20_logs(
            address=address,
            topic_index=1,
            asset=asset,
            after_block=after_block,
            before_block=before_block,
            limit=limit,
        )

    def get_transfers_to(
        self,
        address: str,
        asset: Optional[Asset] = None,
        after_block: Optional[int] = None,
        before_block: Optional[int] = None,
        limit: int = 50,
    ) -> list[OnChainTransfer]:
        return self._fetch_erc20_logs(
            address=address,
            topic_index=2,
            asset=asset,
            after_block=after_block,
            before_block=before_block,
            limit=limit,
        )

    def _fetch_erc20_logs(
        self,
        address: str,
        topic_index: int,
        asset: Optional[Asset],
        after_block: Optional[int],
        before_block: Optional[int],
        limit: int,
    ) -> list[OnChainTransfer]:
        padded_addr = "0x" + "0" * 24 + address.lower().removeprefix("0x")
        topics = [TRANSFER_TOPIC, None, None]
        topics[topic_index] = padded_addr

        current_block = self.get_current_block()
        from_b = hex(after_block) if after_block else hex(max(0, current_block - 5000))
        to_b = hex(before_block) if before_block else "latest"

        contracts_to_check = []
        if asset:
            contract = next((k for k, v in ERC20_CONTRACTS.items() if v == asset), None)
            if contract:
                contracts_to_check.append((contract, asset))
        else:
            contracts_to_check = list(ERC20_CONTRACTS.items())

        results = []
        finalized_block = self.get_finalized_block()

        for contract_addr, mapped_asset in contracts_to_check:
            filter_params = {
                "fromBlock": from_b,
                "toBlock": to_b,
                "address": contract_addr,
                "topics": topics,
            }
            try:
                logs = self._rpc_call("eth_getLogs", [filter_params])
            except Exception as exc:
                log.warning("eth_getLogs failed for %s: %s", contract_addr, exc)
                continue

            for entry in logs:
                t_topics = entry.get("topics", [])
                if len(t_topics) < 3:
                    continue
                from_a = "0x" + t_topics[1][-40:]
                to_a = "0x" + t_topics[2][-40:]
                data_hex = entry.get("data", "0x0")
                raw_val = int(data_hex, 16) if data_hex != "0x" else 0
                decimals = ASSET_DECIMALS.get(mapped_asset, 18)
                amount = Decimal(raw_val) / Decimal(10 ** decimals)
                block_num = int(entry.get("blockNumber", "0x0"), 16)
                block_ts = self._block_timestamp(block_num)
                tx_state, finality_type = self.classify_tx_state(block_num, provider_finalized_block=finalized_block)

                results.append(OnChainTransfer(
                    tx_hash=entry.get("transactionHash", ""),
                    chain=Chain.ETHEREUM,
                    asset=mapped_asset,
                    amount=amount,
                    from_address=from_a.lower(),
                    to_address=to_a.lower(),
                    block_number=block_num,
                    block_timestamp=block_ts,
                    tx_state=tx_state,
                    log_index=int(entry.get("logIndex", "0x0"), 16),
                    finality_type=finality_type,
                ))
        results.sort(key=lambda t: t.block_timestamp)
        return results[:limit]

    def get_historical_balance(
        self, address: str, asset: Asset, at_block: Optional[int] = None
    ) -> HistoricalBalanceResult:
        """
        Query account balance at specific block height via JSON-RPC.
        Returns explicit UNAVAILABLE_PROVIDER if the RPC is a pruned node.
        """
        block_param = hex(at_block) if at_block else "latest"
        try:
            if asset == Asset.ETH:
                result = self._rpc_call("eth_getBalance", [address, block_param])
                raw = int(result, 16)
                amount = Decimal(raw) / Decimal(10 ** 18)
                return HistoricalBalanceResult(
                    status=HistoricalBalanceStatus.KNOWN,
                    chain=Chain.ETHEREUM,
                    asset=asset,
                    address=address,
                    requested_block=at_block,
                    amount=amount,
                    data_source="Ethereum JSON-RPC",
                )

            # ERC-20: call balanceOf(address)
            contract_addr = next((k for k, v in ERC20_CONTRACTS.items() if v == asset), None)
            if not contract_addr:
                return HistoricalBalanceResult(
                    status=HistoricalBalanceStatus.UNKNOWN,
                    chain=Chain.ETHEREUM,
                    asset=asset,
                    address=address,
                    requested_block=at_block,
                    amount=Decimal(0),
                    data_source="Ethereum JSON-RPC",
                    reason=f"Unregistered contract for asset {asset.value}",
                )

            padded = "0x" + "0" * 24 + address.lower().removeprefix("0x")
            call_data = "0x70a08231" + padded[2:]
            result = self._rpc_call("eth_call", [{"to": contract_addr, "data": call_data}, block_param])
            raw = int(result, 16) if result and result != "0x" else 0
            decimals = ASSET_DECIMALS.get(asset, 18)
            amount = Decimal(raw) / Decimal(10 ** decimals)
            return HistoricalBalanceResult(
                status=HistoricalBalanceStatus.KNOWN,
                chain=Chain.ETHEREUM,
                asset=asset,
                address=address,
                requested_block=at_block,
                amount=amount,
                data_source="Ethereum JSON-RPC",
            )
        except RuntimeError as exc:
            err_str = str(exc)
            if "ARCHIVE_STATE_UNAVAILABLE" in err_str:
                return HistoricalBalanceResult(
                    status=HistoricalBalanceStatus.UNAVAILABLE_PROVIDER,
                    chain=Chain.ETHEREUM,
                    asset=asset,
                    address=address,
                    requested_block=at_block,
                    amount=None,
                    data_source="Ethereum JSON-RPC (Pruned Node)",
                    reason="Connected RPC provider does not retain historical archive state for this block.",
                )
            return HistoricalBalanceResult(
                status=HistoricalBalanceStatus.UNKNOWN,
                chain=Chain.ETHEREUM,
                asset=asset,
                address=address,
                requested_block=at_block,
                amount=None,
                data_source="Ethereum JSON-RPC",
                reason=err_str,
            )
