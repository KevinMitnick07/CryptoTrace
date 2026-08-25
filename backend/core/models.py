"""
Domain types for victim-centric VASP attribution.

These types model the investigation, not the blockchain.
The blockchain is the evidence source; the investigation is what we build.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from decimal import Decimal
import datetime


def utc_now() -> datetime.datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.datetime.now(datetime.timezone.utc)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class Chain(str, Enum):
    TRON = "TRON"
    ETHEREUM = "ETHEREUM"
    BITCOIN = "BITCOIN"
    BSC = "BSC"
    POLYGON = "POLYGON"
    ARBITRUM = "ARBITRUM"
    OPTIMISM = "OPTIMISM"
    UNKNOWN = "UNKNOWN"


class Asset(str, Enum):
    USDT_TRC20 = "USDT_TRC20"
    USDT_ERC20 = "USDT_ERC20"
    USDC_ERC20 = "USDC_ERC20"
    DAI_ERC20 = "DAI_ERC20"
    ETH = "ETH"
    BTC = "BTC"
    TRX = "TRX"
    BNB = "BNB"
    MATIC = "MATIC"
    UNKNOWN = "UNKNOWN"


# Standard token base decimals mapping
ASSET_DECIMALS: dict[Asset, int] = {
    Asset.USDT_TRC20: 6,
    Asset.USDT_ERC20: 6,
    Asset.USDC_ERC20: 6,
    Asset.DAI_ERC20: 18,
    Asset.ETH: 18,
    Asset.BTC: 8,
    Asset.TRX: 6,
    Asset.BNB: 18,
    Asset.MATIC: 18,
    Asset.UNKNOWN: 18,
}


class AnchorLevel(str, Enum):
    """
    How confidently can we identify the victim's specific on-chain transaction?
    Higher levels represent stronger evidence.
    """
    A = "A"  # Verified transaction hash
    B = "B"  # Wallet + asset + exact amount + narrow timestamp window
    C = "C"  # Wallet + victim payment evidence (receipt screenshot, etc.)
    D = "D"  # Wallet-only — lowest confidence


class AnchorStatus(str, Enum):
    VERIFIED = "VERIFIED"
    AMBIGUOUS = "AMBIGUOUS"   # Multiple candidate transactions; investigator review required
    UNRESOLVABLE = "UNRESOLVABLE"  # Cannot match complaint fields to any on-chain event


class TxState(str, Enum):
    """Finality state of an on-chain transaction."""
    SEEN = "SEEN"                        # Observed in mempool or unconfirmed block
    CONFIRMED = "CONFIRMED"              # Chain-specific confirmation threshold met
    FINALITY_THRESHOLD_REACHED = "FINALITY_THRESHOLD_REACHED"
    REORGED = "REORGED"
    DROPPED = "DROPPED"


class FinalityType(str, Enum):
    """Explicit distinction between local confirmation policy and protocol finality."""
    OBSERVED = "OBSERVED"
    INVESTIGATIVE_CONFIRMATION_POLICY = "INVESTIGATIVE_CONFIRMATION_POLICY"
    PROTOCOL_FINALIZED = "PROTOCOL_FINALIZED"  # Ethereum PoS finalized checkpoint
    SOLIDIFIED = "SOLIDIFIED"                  # TRON DPoS solidified block
    UNKNOWN = "UNKNOWN"


class HistoricalBalanceStatus(str, Enum):
    """Analytical status of account balance retrieval at historical block."""
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    UNAVAILABLE_PROVIDER = "UNAVAILABLE_PROVIDER"
    UNSUPPORTED_CHAIN = "UNSUPPORTED_CHAIN"


@dataclass(frozen=True)
class HistoricalBalanceResult:
    """Structured response for historical balance queries."""
    status: HistoricalBalanceStatus
    chain: Chain
    asset: Asset
    address: str
    requested_block: Optional[int]
    amount: Optional[Decimal]
    data_source: str
    reason: Optional[str] = None


class AllocationModel(str, Enum):
    CONSERVATIVE = "CONSERVATIVE"      # Only direct continuations consistent with victim value
    PROPORTIONAL = "PROPORTIONAL"      # Haircut: each outgoing carries V/total_out fraction
    FIFO = "FIFO"                      # Victim value fills earliest outgoing transfers first
    LIFO = "LIFO"                      # Victim value fills latest outgoing transfers first


class EvidenceClass(str, Enum):
    """
    Evidence types are not a ranking. They answer different questions.
    OBSERVED: directly on-chain or in complaint.
    DERIVED:  deterministic calculation from observed data.
    ATTRIBUTED: entity/service assertion from an intelligence source.
    CORRELATED: supported by multiple signals, not directly observed.
    EXTERNALLY_CONFIRMED: authorized off-chain confirmation.
    """
    OBSERVED = "OBSERVED"
    DERIVED = "DERIVED"
    ATTRIBUTED = "ATTRIBUTED"
    CORRELATED = "CORRELATED"
    EXTERNALLY_CONFIRMED = "EXTERNALLY_CONFIRMED"


class TraceabilityState(str, Enum):
    DETERMINISTIC = "DETERMINISTIC"   # On-chain evidence sufficient
    SUPPORTED = "SUPPORTED"           # Multiple signals support the path
    AMBIGUOUS = "AMBIGUOUS"           # Evidence insufficient for single conclusion
    OBFUSCATED = "OBFUSCATED"         # Mixer/tumbler boundary reached
    OFF_CHAIN = "OFF_CHAIN"           # Evidence exhausted; off-chain movement suspected
    UNRESOLVED = "UNRESOLVED"         # Traversal incomplete or budget exhausted


class ActionabilityState(str, Enum):
    NO_ACTIONABLE_ENDPOINT = "NO_ACTIONABLE_ENDPOINT"
    CANDIDATE_VASP = "CANDIDATE_VASP"
    SUPPORTED_VASP = "SUPPORTED_VASP"
    RECENT_SUPPORTED_CUSTODIAL_EXPOSURE = "RECENT_SUPPORTED_CUSTODIAL_EXPOSURE"
    STALE_EXPOSURE = "STALE_EXPOSURE"
    TRACEABILITY_LOST = "TRACEABILITY_LOST"


class EndpointStability(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNRESOLVED = "UNRESOLVED"


class CaseState(str, Enum):
    ACTIVE = "ACTIVE"
    FUNDS_STATIONARY = "FUNDS_STATIONARY"
    NEW_MOVEMENT = "NEW_MOVEMENT"
    FAN_OUT = "FAN_OUT"
    ASSET_TRANSFORMATION = "ASSET_TRANSFORMATION"
    CROSS_CHAIN_MOVEMENT = "CROSS_CHAIN_MOVEMENT"
    VASP_CANDIDATE = "VASP_CANDIDATE"
    SUPPORTED_VASP = "SUPPORTED_VASP"
    CUSTODIAL_BOUNDARY = "CUSTODIAL_BOUNDARY"
    CLOSED = "CLOSED"


class BranchDisposition(str, Enum):
    FULLY_TRACED = "FULLY_TRACED"
    DEPRIORITIZED_ECONOMIC = "DEPRIORITIZED_ECONOMIC"   # Below value threshold
    DEPRIORITIZED_DUST = "DEPRIORITIZED_DUST"
    DEFERRED_BUDGET = "DEFERRED_BUDGET"                 # Material branch deferred due to per-hop budget
    CONTEXTUAL = "CONTEXTUAL"                            # Stored but not traversed
    MIXER_BOUNDARY = "MIXER_BOUNDARY"
    VASP_BOUNDARY = "VASP_BOUNDARY"
    UNRECOGNIZED_CONTRACT = "UNRECOGNIZED_CONTRACT"
    OFF_CHAIN_BOUNDARY = "OFF_CHAIN_BOUNDARY"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"


class BridgeMatchStrength(str, Enum):
    STRONG = "STRONG"       # Protocol-specific message ID / nonce match
    MODERATE = "MODERATE"   # Token + amount + recipient + tight timing
    WEAK = "WEAK"           # Amount + timing only
    NONE = "NONE"           # No match found


class AttributionSource(str, Enum):
    INTERNAL_LEA = "INTERNAL_LEA"
    COMMERCIAL_INTELLIGENCE = "COMMERCIAL_INTELLIGENCE"
    VASP_CONFIRMED = "VASP_CONFIRMED"
    PUBLIC_VERIFIED = "PUBLIC_VERIFIED"
    COMMUNITY_LABEL = "COMMUNITY_LABEL"
    INVESTIGATION_DERIVED = "INVESTIGATION_DERIVED"
    UNVERIFIED_NOTE = "UNVERIFIED_NOTE"
    PROTOTYPE_REGISTRY = "PROTOTYPE_REGISTRY"


class AttributionConfidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    STALE = "STALE"       # Once HIGH but past validity threshold
    DISPUTED = "DISPUTED"  # Conflicting sources


class VaspClaimStatus(str, Enum):
    RESOLVED = "RESOLVED"
    CONFLICTED = "CONFLICTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    STALE = "STALE"


# ---------------------------------------------------------------------------
# Core value types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ValueInterval:
    """
    Victim-attributed value as a bounded interval.
    The blockchain does not tell us the exact amount; these are analytical bounds.
    lower_bound: most conservative defensible attribution
    upper_bound: maximum feasible attribution (victim value minus fees)
    Values are in USDT-equivalent (USD stablecoin nominal).
    """
    lower_bound: Decimal
    upper_bound: Decimal
    asset: Asset
    usd_equivalent_at: Optional[datetime.datetime] = None  # timestamp of valuation
    non_additive_across_hypotheses: bool = True           # Invariant marker: bounds cannot be summed across models

    def __post_init__(self):
        if self.lower_bound < Decimal(0):
            raise ValueError("lower_bound cannot be negative")
        if self.upper_bound < self.lower_bound:
            raise ValueError("upper_bound cannot be less than lower_bound")

    def is_zero(self) -> bool:
        return self.upper_bound == Decimal(0)

    def midpoint(self) -> Decimal:
        return (self.lower_bound + self.upper_bound) / Decimal(2)


@dataclass(frozen=True)
class ModelAttribution:
    """Single allocation model's victim-value estimate for one address/cluster."""
    model: AllocationModel
    attributed_value: Decimal  # In asset units
    asset: Asset
    confidence_note: str = ""


# ---------------------------------------------------------------------------
# Trace anchor
# ---------------------------------------------------------------------------

@dataclass
class CandidateTransaction:
    tx_hash: str
    chain: Chain
    asset: Asset
    amount: Decimal
    block_number: int
    block_timestamp: datetime.datetime
    from_address: str
    to_address: str
    tx_state: TxState
    match_fields: list[str]  # Which complaint fields matched this tx
    finality_type: FinalityType = FinalityType.OBSERVED


@dataclass
class TraceAnchor:
    """
    The resolved starting point of victim-fund tracing.
    Everything downstream is only as confident as this anchor.
    """
    status: AnchorStatus
    level: AnchorLevel
    chain: Optional[Chain]
    asset: Optional[Asset]
    tx_hash: Optional[str]
    amount: Optional[Decimal]       # Victim-reported amount
    reported_time: Optional[datetime.datetime]
    confirmed_tx: Optional[CandidateTransaction]
    candidate_txs: list[CandidateTransaction] = field(default_factory=list)
    anchor_evidence: str = ""       # Human-readable evidence summary
    ambiguity_reason: str = ""      # Why status is AMBIGUOUS if applicable


# ---------------------------------------------------------------------------
# Graph entities
# ---------------------------------------------------------------------------

@dataclass
class OnChainTransfer:
    """A single observed on-chain token transfer — Evidence class: OBSERVED."""
    tx_hash: str
    chain: Chain
    asset: Asset
    amount: Decimal
    from_address: str
    to_address: str
    block_number: int
    block_timestamp: datetime.datetime
    tx_state: TxState
    is_internal: bool = False       # Internal call, not a top-level transfer
    log_index: Optional[int] = None
    finality_type: FinalityType = FinalityType.OBSERVED


@dataclass
class DexTransformation:
    """
    A DEX swap or similar protocol event that changes asset denomination.
    Evidence class: DERIVED (parsed from contract events).
    """
    tx_hash: str
    chain: Chain
    protocol: str                   # e.g. "uniswap_v3", "sunswap_v2"
    router_address: str
    input_asset: Asset
    input_amount: Decimal
    output_asset: Asset
    output_amount: Decimal
    recipient_address: str
    fee_amount: Optional[Decimal]
    slippage_pct: Optional[Decimal]
    block_timestamp: datetime.datetime
    usd_rate_input: Optional[Decimal]   # Price oracle value at block_timestamp
    usd_rate_output: Optional[Decimal]
    is_swap: bool = True
    is_liquidity_add: bool = False
    is_liquidity_remove: bool = False
    is_wrap: bool = False
    is_unwrap: bool = False
    confidence: EvidenceClass = EvidenceClass.DERIVED
    input_decimals: int = 18
    output_decimals: int = 18
    is_complete: bool = True


@dataclass
class BridgeEvent:
    """
    Cross-chain bridge transition.
    Evidence class depends on match strength.
    """
    source_chain: Chain
    source_tx_hash: str
    source_address: str
    source_asset: Asset
    source_amount: Decimal
    source_block_timestamp: datetime.datetime

    destination_chain: Optional[Chain]
    destination_tx_hash: Optional[str]
    destination_address: Optional[str]
    destination_asset: Optional[Asset]
    destination_amount: Optional[Decimal]
    destination_block_timestamp: Optional[datetime.datetime]

    protocol: str                     # e.g. "arbitrum_canonical", "multichain"
    match_method: str                 # Description of how chains were linked
    match_strength: BridgeMatchStrength
    is_deterministic: bool            # True only for protocol-ID matched events
    bridge_fee: Optional[Decimal]
    confidence_note: str = ""
    ticket_id: Optional[str] = None   # Canonical protocol ticket/sequence ID


# ---------------------------------------------------------------------------
# VASP attribution & Multi-Claim Types
# ---------------------------------------------------------------------------

@dataclass
class VaspRecord:
    """
    A single entity attribution for a blockchain address or cluster.
    Not a fact — an assertion from a source.
    """
    address: str
    chain: Chain
    entity_name: str
    entity_role: str                   # e.g. "deposit_infrastructure", "hot_wallet", "dex_router", "mixer"
    source: AttributionSource
    source_reliability: str            # Human-readable reliability tier
    first_observed: datetime.datetime
    last_verified: datetime.datetime
    confidence: AttributionConfidence
    is_active: bool
    independent_corroboration: bool    # Whether a second source confirms
    notes: str = ""
    effective_until: Optional[datetime.datetime] = None

    def is_stale(self, threshold_days: int = 180) -> bool:
        """Attribution is stale if last_verified is older than threshold_days."""
        age = (utc_now() - self.last_verified.replace(tzinfo=datetime.timezone.utc) if self.last_verified.tzinfo is None else utc_now() - self.last_verified).days
        return age > threshold_days


@dataclass
class VaspLookupResult:
    """Preserves multiple conflicting or corroborating intelligence claims per address."""
    status: VaspClaimStatus
    primary_claim: Optional[VaspRecord]
    claims: list[VaspRecord]
    entity_type: str                   # CUSTODIAL_VASP, DEX, BRIDGE, MIXER, FOUNDATION, UNKNOWN
    is_stale: bool
    dispute_reason: str = ""


@dataclass
class VaspAttribution:
    """
    The attribution conclusion for a specific address during an investigation.
    Wraps VaspRecord with investigation-specific context.
    """
    record: VaspRecord
    address_in_path: str
    hop_from_anchor: int
    victim_value_interval: ValueInterval
    per_model: list[ModelAttribution]
    first_hop_reaching_vasp: bool      # Is this the First Supported VASP?
    is_primary_stable: bool            # Is this the Primary Stable VASP?
    endpoint_stability: EndpointStability
    stability_reason: str
    actionability: ActionabilityState
    lookup_result: Optional[VaspLookupResult] = None


# ---------------------------------------------------------------------------
# Branch audit
# ---------------------------------------------------------------------------

@dataclass
class BranchAuditRecord:
    """
    Records every traversal decision — what was explored and what was not.
    Investigators must be able to inspect deprioritized branches.
    """
    from_address: str
    to_address: str
    tx_hash: str
    chain: Chain
    asset: Asset
    amount: Decimal
    victim_attributed_range: Optional[ValueInterval]
    disposition: BranchDisposition
    reason: str
    tier: int                           # Traversal priority tier (1–5)
    timestamp: datetime.datetime


# ---------------------------------------------------------------------------
# Investigation path
# ---------------------------------------------------------------------------

@dataclass
class PathSegment:
    """One hop in the victim-value investigation path."""
    sequence: int
    transfer: Optional[OnChainTransfer]
    transformation: Optional[DexTransformation]
    bridge_event: Optional[BridgeEvent]
    to_address: str
    to_chain: Chain
    victim_value_by_model: dict[AllocationModel, Decimal]  # model → attributed value
    traceability: TraceabilityState
    evidence_class: EvidenceClass


# ---------------------------------------------------------------------------
# Claim record — mandatory for every material conclusion
# ---------------------------------------------------------------------------

@dataclass
class ClaimRecord:
    """
    Every important conclusion in the investigation carries a claim record.
    This enables forensic reproducibility: a future analyst can determine
    why the system reached a specific conclusion.
    """
    claim_text: str
    evidence_class: EvidenceClass
    supporting_observations: list[str]
    data_source: str
    source_timestamp: Optional[datetime.datetime]
    effective_date: datetime.datetime
    algorithm_or_model: str
    assumptions: list[str]
    confidence: str                    # HIGH / MEDIUM / LOW / UNRESOLVED (qualitative)
    alternative_explanation: Optional[str]
    conflicting_evidence: Optional[str]
    analyst_override: Optional[str]
    software_version: str


# ---------------------------------------------------------------------------
# Case model
# ---------------------------------------------------------------------------

@dataclass
class ComplaintInput:
    """Raw intake from a victim complaint — unvalidated."""
    complaint_ref: str
    reported_wallet: str
    reported_chain: Optional[Chain]
    reported_asset: Optional[Asset] = None
    reported_amount: Optional[Decimal] = None
    reported_tx_hash: Optional[str] = None
    reported_time_utc: Optional[datetime.datetime] = None
    complainant_payment_evidence: Optional[str] = None  # Free-text or file reference
    intake_timestamp: datetime.datetime = field(default_factory=utc_now)


@dataclass
class CaseDelta:
    """
    What changed since the last investigator review.
    This is a first-class feature, not a log.
    """
    review_timestamp: datetime.datetime
    new_transfers: int
    new_bridge_events: int
    new_dex_events: int
    victim_value_moved: Decimal
    vasp_candidate_changes: list[str]        # Human-readable descriptions
    primary_vasp_changed: bool
    related_cases_added: int
    stale_labels_detected: int
    state_transitions: list[str]


@dataclass
class CrossCaseSignal:
    """
    Potential shared infrastructure between multiple complaints.
    Not evidence of coordination — a signal for investigative attention.
    """
    shared_address: str
    chain: Chain
    case_refs: list[str]
    service_baseline_txcount: Optional[int]  # Monthly volume of this address
    normalized_rarity: str                   # HIGH / MEDIUM / LOW / NEGLIGIBLE
    timing_similarity: bool
    amount_relationship: bool
    shared_upstream: bool                    # Cases share intermediary upstream too
    alternative_explanation: str
    convergence_note: str


@dataclass
class InvestigationCase:
    """The top-level investigation object."""
    case_id: str
    complaint: ComplaintInput
    anchor: Optional[TraceAnchor]
    state: CaseState
    traceability: TraceabilityState
    actionability: ActionabilityState

    path_segments: list[PathSegment]
    branch_audit: list[BranchAuditRecord]
    vasp_candidates: list[VaspAttribution]
    cross_case_signals: list[CrossCaseSignal]
    claims: list[ClaimRecord]

    # Outputs
    first_supported_vasp: Optional[VaspAttribution]
    primary_stable_vasp: Optional[VaspAttribution]
    unresolved_value: Optional[ValueInterval]
    deferred_value: Optional[ValueInterval] = None
    trace_completeness_pct: Decimal = Decimal("100.00")
    high_fragmentation_detected: bool = False

    # Monitoring
    last_reviewed: Optional[datetime.datetime] = None
    last_delta: Optional[CaseDelta] = None

    created_at: datetime.datetime = field(default_factory=utc_now)
    updated_at: datetime.datetime = field(default_factory=utc_now)
    software_version: str = "0.2.0-sprint"


# ---------------------------------------------------------------------------
# Graph node/edge types for the four-graph model
# ---------------------------------------------------------------------------

class GraphType(str, Enum):
    EVIDENCE = "EVIDENCE"       # Direct blockchain facts only
    ECONOMIC = "ECONOMIC"       # Victim-value hypothesis flows
    INTELLIGENCE = "INTELLIGENCE"  # Entity/service assertions
    CASE = "CASE"               # Investigation relationships


@dataclass
class GraphNode:
    node_id: str
    graph_type: GraphType
    role: str                   # victim_anchor, suspect_wallet, intermediary, dex, bridge, mixer, vasp, unknown
    chain: Optional[Chain]
    address: Optional[str]
    label: Optional[str]        # VASP name or service name if attributed
    metadata: dict              # Any additional type-specific data


@dataclass
class GraphEdge:
    edge_id: str
    graph_type: GraphType
    from_node: str
    to_node: str
    chain: Chain
    asset: Asset
    amount: Optional[Decimal]
    timestamp: Optional[datetime.datetime]
    evidence_class: EvidenceClass
    victim_value_range: Optional[ValueInterval]
    tx_hash: Optional[str]
    label: Optional[str]


# ---------------------------------------------------------------------------
# Internal Alert Event System (Near-Real-Time Continuous Monitoring)
# ---------------------------------------------------------------------------

class AlertSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertEventType(str, Enum):
    NEW_MOVEMENT = "NEW_MOVEMENT"
    NEW_VASP_ENDPOINT = "NEW_VASP_ENDPOINT"
    PRIMARY_VASP_CHANGED = "PRIMARY_VASP_CHANGED"
    TRACE_BECAME_INCOMPLETE = "TRACE_BECAME_INCOMPLETE"
    MIXER_BOUNDARY_REACHED = "MIXER_BOUNDARY_REACHED"
    PROVIDER_DEGRADED = "PROVIDER_DEGRADED"
    PROVIDER_RECOVERED = "PROVIDER_RECOVERED"


@dataclass
class AlertEvent:
    alert_id: str
    case_id: str
    event_type: AlertEventType
    severity: AlertSeverity
    summary: str
    evidence_reference: Optional[str] = None
    created_at: datetime.datetime = field(default_factory=utc_now)
    acknowledged: bool = False
