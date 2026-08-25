"""
Tests for Arbitrum Canonical Bridge deterministic matching and strength classification.
"""

from decimal import Decimal
import datetime
import pytest

from backend.core.models import Chain, Asset, BridgeMatchStrength, utc_now
from backend.protocols.bridge import (
    match_bridge_destination, BridgeDestinationCandidate, is_known_bridge
)


def test_known_bridge_contracts():
    # Arbitrum One Inbox
    assert is_known_bridge(Chain.ETHEREUM, "0x4dbd4fc535bd27247792044051a83d45f971b0ee") is True
    # Arbitrum Bridge Router
    assert is_known_bridge(Chain.ETHEREUM, "0x8315177ab297ba92a06054ce80a67ed4dbd7ed3a") is True
    # Unknown contract
    assert is_known_bridge(Chain.ETHEREUM, "0x1111111111111111111111111111111111111111") is False


def test_deterministic_ticket_match():
    now = utc_now()
    ticket_id = "0x_arb_ticket_789456123"

    candidates = [
        BridgeDestinationCandidate(
            tx_hash="0x_arb_l2_tx",
            chain=Chain.ARBITRUM,
            asset=Asset.USDT_ERC20,
            amount=Decimal("9995.00"),
            recipient="0x_arb_recipient",
            block_timestamp=now + datetime.timedelta(minutes=12),
            protocol_message_id=ticket_id,
        )
    ]

    event = match_bridge_destination(
        source_chain=Chain.ETHEREUM,
        source_tx_hash="0x_l1_bridge_deposit",
        source_address="0x_l1_sender",
        source_asset=Asset.USDT_ERC20,
        source_amount=Decimal("10000.00"),
        source_timestamp=now,
        source_protocol_message_id=ticket_id,
        candidates=candidates,
        bridge_protocol="arbitrum_canonical",
    )

    assert event.match_strength == BridgeMatchStrength.STRONG
    assert event.is_deterministic is True
    assert event.ticket_id == ticket_id
    assert event.bridge_fee == Decimal("5.00")
    assert event.destination_chain == Chain.ARBITRUM


def test_heuristic_moderate_match():
    now = utc_now()
    candidates = [
        BridgeDestinationCandidate(
            tx_hash="0x_arb_heuristic_tx",
            chain=Chain.ARBITRUM,
            asset=Asset.USDT_ERC20,
            amount=Decimal("9990.00"),  # Within 2%
            recipient="0x_same_recipient",
            block_timestamp=now + datetime.timedelta(minutes=10),
            protocol_message_id=None,
        )
    ]

    event = match_bridge_destination(
        source_chain=Chain.ETHEREUM,
        source_tx_hash="0x_l1_dep",
        source_address="0x_same_recipient",
        source_asset=Asset.USDT_ERC20,
        source_amount=Decimal("10000.00"),
        source_timestamp=now,
        source_protocol_message_id=None,
        candidates=candidates,
    )

    assert event.match_strength == BridgeMatchStrength.MODERATE
    assert event.is_deterministic is False


def test_timing_violation_returns_none_match():
    now = utc_now()
    # Transaction 2 hours later (>1800s limit)
    candidates = [
        BridgeDestinationCandidate(
            tx_hash="0x_late_tx",
            chain=Chain.ARBITRUM,
            asset=Asset.USDT_ERC20,
            amount=Decimal("10000.00"),
            recipient="0x_recipient",
            block_timestamp=now + datetime.timedelta(hours=2),
            protocol_message_id=None,
        )
    ]

    event = match_bridge_destination(
        source_chain=Chain.ETHEREUM,
        source_tx_hash="0x_l1_dep",
        source_address="0x_recipient",
        source_asset=Asset.USDT_ERC20,
        source_amount=Decimal("10000.00"),
        source_timestamp=now,
        source_protocol_message_id=None,
        candidates=candidates,
    )

    assert event.match_strength == BridgeMatchStrength.NONE
    assert event.destination_chain is None
