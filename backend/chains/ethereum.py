"""
Ethereum chain adapter.

Account-based model. ERC-20 transfers are emitted as Transfer(address,address,uint256)
events in the token contract's logs. This adapter uses a JSON-RPC endpoint with fallback support.

Features:
  - Supports eth_getLogs for token event querying
  - Supports Ethereum PoS finalized block tag checking for deterministic finality
  - Returns structured HistoricalBalanceResult for archive-state transparency
  - Support for fallback RPC URLs (ETH_RPC_FALLBACK_URL)
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

    def __init__(self, rpc_url: Optional[str] = None, fallback_rpc_url: Optional[str] = None):
        self._primary_rpc = rpc_url or os.getenv("ETH_RPC_URL", ETH_RPC_DEFAULT)
        self._fallback_rpc = fallback_rpc_url or os.getenv("ETH_RPC_FALLBACK_URL", "")
        self._rpc = self._primary_rpc
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

        rpcs_to_try = [self._rpc]
        if self._fallback_rpc and self._fallback_rpc != self._rpc:
            rpcs_to_try.append(self._fallback_rpc)

        last_error = None
        for current_rpc in rpcs_to_try:
            for attempt in range(retries):
                try:
                    resp = self._session.post(current_rpc, json=payload, timeout=20)
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
                    last_error = exc
                except requests.exceptions.RequestException as exc:
                    last_error = exc
                    if attempt < retries - 1:
                        time.sleep(1)

        raise RuntimeError(f"PROVIDER_UNAVAILABLE: Ethereum RPC connection failed across endpoints: {last_error}")

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

        logs = receipt.get("logs", [])
        transfer_log = next(
            (l for l in logs if len(l.get("topics", [])) == 3 and l["topics"][0].lower() == TRANSFER_TOPIC.lower()),
            None,
        )
        if not transfer_log:
            return None

        contract = transfer_log["address"].lower()
        asset = ERC20_CONTRACTS.get(contract, Asset.USDT_ERC20)
        from_addr = "0x" + transfer_log["topics"][1][-40:]
        to_addr = "0x" + transfer_log["topics"][2][-40:]
        raw_val = int(transfer_log["data"], 16)
        decimals = ASSET_DECIMALS.get(asset, 18)
        amount = Decimal(raw_val) / Decimal(10 ** decimals)
        block_num = int(receipt["blockNumber"], 16)

        # Finality check against PoS finalized checkpoint
        finalized_block = self.get_finalized_block() or 0
        is_finalized = block_num > 0 and block_num <= finalized_block

        return OnChainTransfer(
            tx_hash=tx_hash,
            chain=Chain.ETHEREUM,
            asset=asset,
            amount=amount,
            from_address=from_addr.lower(),
            to_address=to_addr.lower(),
            block_number=block_num,
            block_timestamp=self._block_timestamp(block_num),
            tx_state=TxState.FINALITY_THRESHOLD_REACHED if is_finalized else TxState.CONFIRMED,
            log_index=int(transfer_log.get("logIndex", "0x0"), 16),
            finality_type=FinalityType.PROTOCOL_FINALIZED if is_finalized else FinalityType.OBSERVED,
        )

    def get_transfers_from(
        self,
        address: str,
        asset: Optional[Asset] = None,
        after_block: Optional[int] = None,
        before_block: Optional[int] = None,
        limit: int = 50,
    ) -> list[OnChainTransfer]:
        """
        Query ERC-20 Transfer logs where from_address == address.
        """
        topic_from = "0x" + address.lower().removeprefix("0x").zfill(64)
        from_blk = hex(after_block) if after_block else "earliest"
        to_blk = hex(before_block) if before_block else "latest"

        contracts = list(ERC20_CONTRACTS.keys())
        if asset:
            contracts = [c for c, a in ERC20_CONTRACTS.items() if a == asset]

        params = [{
            "fromBlock": from_blk,
            "toBlock": to_blk,
            "address": contracts if len(contracts) > 1 else contracts[0] if contracts else None,
            "topics": [TRANSFER_TOPIC, topic_from],
        }]

        try:
            logs = self._rpc_call("eth_getLogs", params)
            if not logs:
                return []

            transfers: list[OnChainTransfer] = []
            for l in logs[:limit]:
                if len(l.get("topics", [])) < 3:
                    continue
                to_addr = "0x" + l["topics"][2][-40:]
                contract = l["address"].lower()
                row_asset = ERC20_CONTRACTS.get(contract, Asset.USDT_ERC20)
                raw_val = int(l["data"], 16)
                decimals = ASSET_DECIMALS.get(row_asset, 18)
                amount = Decimal(raw_val) / Decimal(10 ** decimals)
                blk_num = int(l["blockNumber"], 16)

                transfers.append(
                    OnChainTransfer(
                        tx_hash=l["transactionHash"],
                        chain=Chain.ETHEREUM,
                        asset=row_asset,
                        amount=amount,
                        from_address=address.lower(),
                        to_address=to_addr.lower(),
                        block_number=blk_num,
                        block_timestamp=self._block_timestamp(blk_num),
                        tx_state=TxState.CONFIRMED,
                        log_index=int(l.get("logIndex", "0x0"), 16),
                        finality_type=FinalityType.OBSERVED,
                    )
                )
            return transfers
        except Exception as exc:
            log.warning("Ethereum get_transfers_from failed: %s", exc)
            return []

    def get_transfers_to(
        self,
        address: str,
        asset: Optional[Asset] = None,
        after_block: Optional[int] = None,
        before_block: Optional[int] = None,
        limit: int = 50,
    ) -> list[OnChainTransfer]:
        """Query ERC-20 Transfer logs where to_address == address."""
        topic_to = "0x" + address.lower().removeprefix("0x").zfill(64)
        from_blk = hex(after_block) if after_block else "earliest"
        to_blk = hex(before_block) if before_block else "latest"

        contracts = list(ERC20_CONTRACTS.keys())
        if asset:
            contracts = [c for c, a in ERC20_CONTRACTS.items() if a == asset]

        params = [{
            "fromBlock": from_blk,
            "toBlock": to_blk,
            "address": contracts if len(contracts) > 1 else contracts[0] if contracts else None,
            "topics": [TRANSFER_TOPIC, None, topic_to],
        }]

        try:
            logs = self._rpc_call("eth_getLogs", params)
            if not logs:
                return []

            transfers: list[OnChainTransfer] = []
            for l in logs[:limit]:
                if len(l.get("topics", [])) < 3:
                    continue
                from_addr = "0x" + l["topics"][1][-40:]
                contract = l["address"].lower()
                row_asset = ERC20_CONTRACTS.get(contract, Asset.USDT_ERC20)
                raw_val = int(l["data"], 16)
                decimals = ASSET_DECIMALS.get(row_asset, 18)
                amount = Decimal(raw_val) / Decimal(10 ** decimals)
                blk_num = int(l["blockNumber"], 16)

                transfers.append(
                    OnChainTransfer(
                        tx_hash=l["transactionHash"],
                        chain=Chain.ETHEREUM,
                        asset=row_asset,
                        amount=amount,
                        from_address=from_addr.lower(),
                        to_address=address.lower(),
                        block_number=blk_num,
                        block_timestamp=self._block_timestamp(blk_num),
                        tx_state=TxState.CONFIRMED,
                        log_index=int(l.get("logIndex", "0x0"), 16),
                        finality_type=FinalityType.OBSERVED,
                    )
                )
            return transfers
        except Exception as exc:
            log.warning("Ethereum get_transfers_to failed: %s", exc)
            return []

    def get_historical_balance(
        self,
        address: str,
        asset: Asset,
        at_block: Optional[int] = None,
    ) -> HistoricalBalanceResult:
        """
        Query historical ERC-20 token balance at a specific historical block.
        Returns ARCHIVE_STATE_UNAVAILABLE when querying past pruned state boundaries.
        Strict invariant: Never substitute current balance for historical balance.
        """
        block_number = at_block or self.get_current_block()
        contract = next((c for c, a in ERC20_CONTRACTS.items() if a == asset), None)
        if not contract:
            return HistoricalBalanceResult(
                status=HistoricalBalanceStatus.UNKNOWN,
                chain=Chain.ETHEREUM,
                asset=asset,
                address=address,
                requested_block=block_number,
                amount=None,
                data_source="Ethereum JSON-RPC",
                reason=f"No known ERC-20 contract for asset {asset}",
            )

        clean_addr = address.lower().removeprefix("0x").zfill(64)
        call_data = f"0x70a08231{clean_addr}"
        call_params = [{"to": contract, "data": call_data}, hex(block_number)]

        try:
            raw_hex = self._rpc_call("eth_call", call_params)
            raw_val = int(raw_hex, 16)
            decimals = ASSET_DECIMALS.get(asset, 18)
            amount = Decimal(raw_val) / Decimal(10 ** decimals)
            return HistoricalBalanceResult(
                status=HistoricalBalanceStatus.KNOWN,
                chain=Chain.ETHEREUM,
                asset=asset,
                address=address,
                requested_block=block_number,
                amount=amount,
                data_source="Ethereum JSON-RPC (Archive Supported)",
            )
        except Exception as exc:
            err_str = str(exc)
            status = HistoricalBalanceStatus.UNAVAILABLE_PROVIDER
            reason = f"Provider lacks historical state at block {block_number}: {err_str}"
            return HistoricalBalanceResult(
                status=status,
                chain=Chain.ETHEREUM,
                asset=asset,
                address=address,
                requested_block=block_number,
                amount=None,
                data_source="Ethereum JSON-RPC (Full Node / Pruned State)",
                reason=reason,
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
        Query incoming transfers matching complaint parameters for Level B resolution.
        """
        topic_to = "0x" + target_wallet.lower().removeprefix("0x").zfill(64)
        contracts = list(ERC20_CONTRACTS.keys())
        if asset:
            contracts = [c for c, a in ERC20_CONTRACTS.items() if a == asset]

        params = [{
            "fromBlock": "earliest",
            "toBlock": "latest",
            "address": contracts if len(contracts) > 1 else contracts[0] if contracts else None,
            "topics": [TRANSFER_TOPIC, None, topic_to],
        }]

        try:
            logs = self._rpc_call("eth_getLogs", params)
            candidates: list[CandidateTransaction] = []

            for l in (logs or [])[:50]:
                if len(l.get("topics", [])) < 3:
                    continue
                from_addr = "0x" + l["topics"][1][-40:]
                contract = l["address"].lower()
                row_asset = ERC20_CONTRACTS.get(contract, Asset.USDT_ERC20)
                raw_val = int(l["data"], 16)
                decimals = ASSET_DECIMALS.get(row_asset, 18)
                amount = Decimal(raw_val) / Decimal(10 ** decimals)
                blk_num = int(l["blockNumber"], 16)
                block_ts = self._block_timestamp(blk_num)

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
                        tx_hash=l["transactionHash"],
                        chain=Chain.ETHEREUM,
                        asset=row_asset,
                        amount=amount,
                        block_number=blk_num,
                        block_timestamp=block_ts,
                        from_address=from_addr.lower(),
                        to_address=target_wallet.lower(),
                        tx_state=TxState.CONFIRMED,
                        match_fields=match_fields,
                        finality_type=FinalityType.OBSERVED,
                    )
                )
            return candidates
        except Exception as exc:
            log.warning("Ethereum match_candidate_transactions failed: %s", exc)
            return []
