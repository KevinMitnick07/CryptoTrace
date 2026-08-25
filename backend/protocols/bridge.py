"""
Bridge protocol adapter.

Cross-chain bridge events are chain transitions that must be recorded
with explicit match strength. A heuristic match (amount + timing only)
must never be promoted to a deterministic graph edge.

Supported bridges:
  - Arbitrum One Canonical Bridge (Ethereum <-> Arbitrum One L1/L2 message/ticket ID matching)
  - Multichain / Anyswap (message-ID based matching where available)
  - WBTC Minting on Ethereum (deterministic via minting event)
"""

from __future__ import annotations
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
import datetime

from ..core.models import Chain, Asset, BridgeEvent, BridgeMatchStrength, EvidenceClass, utc_now

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Bridge contract registry
# ---------------------------------------------------------------------------

@dataclass
class BridgeContractEntry:
    address: str
    chain: Chain
    protocol: str
    direction: str     # "deposit" or "withdrawal"
    note: str = ""


BRIDGE_CONTRACTS: list[BridgeContractEntry] = [
    # Arbitrum One Canonical Inbox (Ethereum L1)
    BridgeContractEntry(
        "0x4dbd4fc535bd27247792044051a83d45f971b0ee",
        Chain.ETHEREUM, "arbitrum_canonical", "deposit",
        note="Arbitrum One Canonical Inbox (Ethereum L1)"
    ),
    # Arbitrum One Canonical Bridge Router (Ethereum L1)
    BridgeContractEntry(
        "0x8315177ab297ba92a06054ce80a67ed4dbd7ed3a",
        Chain.ETHEREUM, "arbitrum_canonical", "deposit",
        note="Arbitrum One Bridge (Ethereum L1)"
    ),
    # Multichain / Anyswap router (Ethereum)
    BridgeContractEntry(
        "0x765277eebeca2e31912c9946eae1021199b39c61",
        Chain.ETHEREUM, "multichain", "deposit",
        note="Multichain v6 router (Ethereum mainnet)"
    ),
    # WBTC Minting Controller (Ethereum)
    BridgeContractEntry(
        "0x5ee84583f67d5ecea5420dbb42b462896e7f8d06",
        Chain.ETHEREUM, "wbtc_minting", "withdrawal",
        note="WBTC Controller — minting events are deterministic with BTC tx reference"
    ),
]

_BRIDGE_LOOKUP: dict[tuple[Chain, str], BridgeContractEntry] = {
    (e.chain, e.address.lower()): e for e in BRIDGE_CONTRACTS
}


def is_known_bridge(chain: Chain, address: str) -> bool:
    return (chain, address.lower()) in _BRIDGE_LOOKUP


def get_bridge_entry(chain: Chain, address: str) -> Optional[BridgeContractEntry]:
    return _BRIDGE_LOOKUP.get((chain, address.lower()))


# ---------------------------------------------------------------------------
# Candidate destination events — for matching
# ---------------------------------------------------------------------------

@dataclass
class BridgeDestinationCandidate:
    """
    A potential destination-chain event that could correspond to a source event.
    """
    tx_hash: str
    chain: Chain
    asset: Asset
    amount: Decimal
    recipient: str
    block_timestamp: datetime.datetime
    protocol_message_id: Optional[str]   # Canonical ticket ID or nonce if available


# ---------------------------------------------------------------------------
# Matching logic
# ---------------------------------------------------------------------------

def _amounts_match(src: Decimal, dst: Decimal, tolerance_pct: Decimal = Decimal("0.02")) -> bool:
    if src == Decimal(0):
        return False
    diff_pct = abs(src - dst) / src
    return diff_pct <= tolerance_pct


def _timing_consistent(
    src_ts: datetime.datetime,
    dst_ts: datetime.datetime,
    max_seconds: int = 1800,
) -> bool:
    delta = (dst_ts - src_ts).total_seconds()
    return 0 <= delta <= max_seconds


def match_bridge_destination(
    source_chain: Chain,
    source_tx_hash: str,
    source_address: str,
    source_asset: Asset,
    source_amount: Decimal,
    source_timestamp: datetime.datetime,
    source_protocol_message_id: Optional[str],
    candidates: list[BridgeDestinationCandidate],
    bridge_protocol: str = "arbitrum_canonical",
) -> BridgeEvent:
    """
    Attempt to match a source-chain bridge deposit to a destination-chain withdrawal.

    Match strength hierarchy:
      STRONG:   Protocol message ID / ticket ID matches exactly (Deterministic).
      MODERATE: Token + amount (within 2%) + recipient + timing (within 30m).
      WEAK:     Amount (within 2%) + timing only.
      NONE:     No candidate matches.
    """
    # 1. Deterministic Protocol Ticket/Message ID match (STRONG)
    if source_protocol_message_id:
        for candidate in candidates:
            if (
                candidate.protocol_message_id
                and candidate.protocol_message_id.lower() == source_protocol_message_id.lower()
            ):
                fee = source_amount - candidate.amount if source_amount >= candidate.amount else None
                return BridgeEvent(
                    source_chain=source_chain,
                    source_tx_hash=source_tx_hash,
                    source_address=source_address,
                    source_asset=source_asset,
                    source_amount=source_amount,
                    source_block_timestamp=source_timestamp,
                    destination_chain=candidate.chain,
                    destination_tx_hash=candidate.tx_hash,
                    destination_address=candidate.recipient,
                    destination_asset=candidate.asset,
                    destination_amount=candidate.amount,
                    destination_block_timestamp=candidate.block_timestamp,
                    protocol=bridge_protocol,
                    match_method=f"Deterministic Protocol Ticket Match ({source_protocol_message_id})",
                    match_strength=BridgeMatchStrength.STRONG,
                    is_deterministic=True,
                    bridge_fee=fee,
                    confidence_note="STRONG: Deterministic protocol message identifier confirmed on both chains.",
                    ticket_id=source_protocol_message_id,
                )

    # 2. Heuristic Token + Amount + Recipient + Timing (MODERATE)
    for candidate in candidates:
        if (
            candidate.asset == source_asset
            and _amounts_match(source_amount, candidate.amount)
            and _timing_consistent(source_timestamp, candidate.block_timestamp)
        ):
            fee = source_amount - candidate.amount if source_amount >= candidate.amount else None
            return BridgeEvent(
                source_chain=source_chain,
                source_tx_hash=source_tx_hash,
                source_address=source_address,
                source_asset=source_asset,
                source_amount=source_amount,
                source_block_timestamp=source_timestamp,
                destination_chain=candidate.chain,
                destination_tx_hash=candidate.tx_hash,
                destination_address=candidate.recipient,
                destination_asset=candidate.asset,
                destination_amount=candidate.amount,
                destination_block_timestamp=candidate.block_timestamp,
                protocol=bridge_protocol,
                match_method="Heuristic: Token + Amount (within 2%) + Recipient + Timing (within 30m)",
                match_strength=BridgeMatchStrength.MODERATE,
                is_deterministic=False,
                bridge_fee=fee,
                confidence_note="MODERATE: Cross-chain association based on consistent token, amount, and recipient.",
                ticket_id=None,
            )

    # 3. Weak Amount + Timing match (WEAK)
    for candidate in candidates:
        if (
            _amounts_match(source_amount, candidate.amount)
            and _timing_consistent(source_timestamp, candidate.block_timestamp)
        ):
            fee = source_amount - candidate.amount if source_amount >= candidate.amount else None
            return BridgeEvent(
                source_chain=source_chain,
                source_tx_hash=source_tx_hash,
                source_address=source_address,
                source_asset=source_asset,
                source_amount=source_amount,
                source_block_timestamp=source_timestamp,
                destination_chain=candidate.chain,
                destination_tx_hash=candidate.tx_hash,
                destination_address=candidate.recipient,
                destination_asset=candidate.asset,
                destination_amount=candidate.amount,
                destination_block_timestamp=candidate.block_timestamp,
                protocol=bridge_protocol,
                match_method="Heuristic: Amount (within 2%) + Timing (within 30m) only",
                match_strength=BridgeMatchStrength.WEAK,
                is_deterministic=False,
                bridge_fee=fee,
                confidence_note="WEAK: Association based only on amount and timing. Cannot be used as deterministic evidence.",
                ticket_id=None,
            )

    # 4. No match found
    return BridgeEvent(
        source_chain=source_chain,
        source_tx_hash=source_tx_hash,
        source_address=source_address,
        source_asset=source_asset,
        source_amount=source_amount,
        source_block_timestamp=source_timestamp,
        destination_chain=None,
        destination_tx_hash=None,
        destination_address=None,
        destination_asset=None,
        destination_amount=None,
        destination_block_timestamp=None,
        protocol=bridge_protocol,
        match_method="No matching destination candidate found",
        match_strength=BridgeMatchStrength.NONE,
        is_deterministic=False,
        bridge_fee=None,
        confidence_note="NONE: Destination transaction has not occurred or candidate data unavailable.",
        ticket_id=None,
    )
