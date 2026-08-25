"""
Pytest configuration and deterministic test fixtures for CryptoTrace.
All data in this suite is explicitly SYNTHETIC TEST DATA.
"""

from __future__ import annotations
import datetime
import json
import os
from decimal import Decimal
from typing import Optional

import pytest

from backend.core.models import (
    Chain, Asset, OnChainTransfer, TxState,
    CandidateTransaction, TraceAnchor, AnchorLevel, AnchorStatus,
    ComplaintInput, VaspRecord, AttributionSource, AttributionConfidence,
    HistoricalBalanceResult, HistoricalBalanceStatus, utc_now
)
from backend.chains.base import ChainAdapter
from backend.vasp.registry import VaspRegistry


class FakeChainAdapter(ChainAdapter):
    """Deterministic fake chain adapter for offline unit & integration testing."""

    def __init__(self, chain: Chain = Chain.ETHEREUM):
        self._chain = chain
        self.transactions: dict[str, OnChainTransfer] = {}
        self.outgoing_transfers: dict[str, list[OnChainTransfer]] = {}
        self.balances: dict[tuple[str, Asset], Decimal] = {}
        self.anchor_candidates: list[CandidateTransaction] = []
        self.current_block_num: int = 1000000

    @property
    def chain(self) -> Chain:
        return self._chain

    @property
    def version(self) -> str:
        return "0.2.0-fake"

    def get_tx(self, tx_hash: str) -> Optional[OnChainTransfer]:
        return self.transactions.get(tx_hash)

    def get_transfers_from(
        self,
        address: str,
        asset: Optional[Asset],
        after_block: Optional[int],
        before_block: Optional[int],
        limit: int = 50,
    ) -> list[OnChainTransfer]:
        transfers = self.outgoing_transfers.get(address.lower(), [])
        filtered = [
            t for t in transfers
            if (asset is None or t.asset == asset)
            and (after_block is None or t.block_number >= after_block)
            and (before_block is None or t.block_number <= before_block)
        ]
        return filtered[:limit]

    def get_transfers_to(
        self,
        address: str,
        asset: Optional[Asset],
        after_block: Optional[int],
        before_block: Optional[int],
        limit: int = 50,
    ) -> list[OnChainTransfer]:
        return []

    def get_historical_balance(
        self, address: str, asset: Asset, at_block: Optional[int] = None
    ) -> HistoricalBalanceResult:
        amt = self.balances.get((address.lower(), asset), Decimal(0))
        return HistoricalBalanceResult(
            status=HistoricalBalanceStatus.KNOWN,
            chain=self._chain,
            asset=asset,
            address=address,
            requested_block=at_block,
            amount=amt,
            data_source="FakeChainAdapter",
        )

    def get_balance(self, address: str, asset: Asset, at_block: Optional[int] = None) -> Decimal:
        return self.balances.get((address.lower(), asset), Decimal(0))

    def get_current_block(self) -> int:
        return self.current_block_num

    def resolve_anchor_candidates(
        self,
        wallet: str,
        asset: Optional[Asset],
        amount: Optional[Decimal],
        reported_time: Optional[datetime.datetime],
        time_window_minutes: int = 60,
    ) -> list[CandidateTransaction]:
        return self.anchor_candidates


@pytest.fixture
def fake_adapter() -> FakeChainAdapter:
    return FakeChainAdapter()


@pytest.fixture
def fake_eth_adapter() -> FakeChainAdapter:
    return FakeChainAdapter(Chain.ETHEREUM)


@pytest.fixture
def fake_tron_adapter() -> FakeChainAdapter:
    return FakeChainAdapter(Chain.TRON)


@pytest.fixture
def mock_vasp_registry() -> VaspRegistry:
    sample_labels = [
        {
            "chain": "ETHEREUM",
            "address": "0x_binance_deposit_01",
            "entity_name": "Binance",
            "entity_role": "deposit_infrastructure",
            "source": "COMMERCIAL_INTELLIGENCE",
            "source_reliability": "HIGH",
            "first_observed": "2023-01-01T00:00:00",
            "last_verified": utc_now().isoformat(),
            "confidence": "HIGH",
            "is_active": True,
            "independent_corroboration": True
        },
        {
            "chain": "ETHEREUM",
            "address": "0x_okx_hot_01",
            "entity_name": "OKX",
            "entity_role": "deposit_infrastructure",
            "source": "PUBLIC_VERIFIED",
            "source_reliability": "HIGH",
            "first_observed": "2023-01-01T00:00:00",
            "last_verified": utc_now().isoformat(),
            "confidence": "HIGH",
            "is_active": True,
            "independent_corroboration": True
        },
        {
            "chain": "ETHEREUM",
            "address": "0xd90e2f925da726b50c4ed8d0fb90ad053324f31b",
            "entity_name": "Tornado Cash v1",
            "entity_role": "mixer",
            "source": "INTERNAL_LEA",
            "source_reliability": "HIGH",
            "first_observed": "2020-01-01T00:00:00",
            "last_verified": utc_now().isoformat(),
            "confidence": "HIGH",
            "is_active": True,
            "independent_corroboration": True
        }
    ]
    return VaspRegistry(sample_labels)


@pytest.fixture
def test_registry() -> VaspRegistry:
    sample_labels = [
        {
            "chain": "ETHEREUM",
            "address": "0x_okx_hot_01",
            "entity_name": "OKX",
            "entity_role": "deposit_infrastructure",
            "source": "PUBLIC_VERIFIED",
            "source_reliability": "HIGH",
            "first_observed": "2023-01-01T00:00:00",
            "last_verified": utc_now().isoformat(),
            "confidence": "HIGH",
            "is_active": True,
            "independent_corroboration": True
        },
        {
            "chain": "ETHEREUM",
            "address": "0x28c6c06298d514db089934071355e5743bf21d60",
            "entity_name": "Binance 14",
            "entity_role": "deposit_infrastructure",
            "source": "PUBLIC_VERIFIED",
            "source_reliability": "HIGH",
            "first_observed": "2020-01-01T00:00:00",
            "last_verified": "2025-06-01T00:00:00",
            "confidence": "HIGH",
            "is_active": True,
            "independent_corroboration": True
        },
        {
            "chain": "TRON",
            "address": "TKHuVq1oKVruCGLvqVexFs6dawKv6fQgFs",
            "entity_name": "Tether Treasury",
            "entity_role": "deposit_infrastructure",
            "source": "PUBLIC_VERIFIED",
            "source_reliability": "HIGH",
            "first_observed": "2019-01-01T00:00:00",
            "last_verified": utc_now().isoformat(),
            "confidence": "HIGH",
            "is_active": True,
            "independent_corroboration": True
        }
    ]
    return VaspRegistry(sample_labels)


@pytest.fixture
def benchmark_scenarios() -> list[dict]:
    path = os.path.join(os.path.dirname(__file__), "../data/test_scenarios.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["scenarios"]
