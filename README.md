CryptoTrace
SIH 2026 — Problem Statement 26183

Real-Time Identification of Fraud-Linked Cryptocurrency Exchanges from Victim-Reported Suspect Wallet Addresses through Automated Blockchain Analytics.
CryptoTrace is a blockchain forensics prototype focused on tracing victim-reported cryptocurrency fund flows, identifying supported VASP/service endpoints, and exposing uncertainty instead of hiding it behind a single score.

Current Status
Beta / Work in Progress
Current verified local baseline:
Python 3.14
FastAPI backend
SQLite persistence
Vanilla JavaScript frontend
Cytoscape transaction graph
92 automated tests passing
TRON live traversal validated
Ethereum live provider path validated with provider limitations
Uniswap V3 live transaction decoding validated
Cross-chain bridge logic synthetically validated
NCRP / SAHYOG integration-ready, not directly connected
This repository is not production-ready and should not be treated as a completed forensic platform.

Problem
Cybercrime complaints may contain suspect cryptocurrency wallet addresses used in:
investment scams
task-based fraud
sextortion
ransomware
phishing
darknet activity
organized cyber-enabled financial crime
The reported wallet may be:
non-custodial
temporary
an intermediary
part of a peeling chain
part of a high fan-out flow
connected to a DEX
connected through a bridge
linked to a mixer/privacy boundary
The objective is not simply to find the nearest labeled address.
CryptoTrace attempts to trace the reported value while preserving uncertainty and determining whether a VASP/service endpoint remains supported across different fund-allocation hypotheses.

Core Workflow

Victim Complaint
      ↓
Anchor Resolution
      ↓
Blockchain Data Retrieval
      ↓
Fund-Flow Traversal
      ↓
Multi-Hypothesis Attribution
      ↓
VASP / Service Attribution
      ↓
Endpoint Stability Analysis
      ↓
Uncertainty & Value Accounting
      ↓
Transaction Graph
      ↓
Investigator Action Packet




Core Capabilities

Complaint & Anchor Resolution
Complaint intake supports:
complaint reference
reported wallet
transaction hash
blockchain
asset
reported amount
Anchor resolution preserves different confidence levels instead of assuming the reported wallet is sufficient evidence.


Multi-Hypothesis Attribution
CryptoTrace evaluates multiple coherent value-allocation hypotheses:
Conservative
Proportional / Haircut
FIFO
LIFO
The system preserves model-specific allocations and does not treat incompatible model outputs as one globally valid allocation.
Value intervals across hypotheses are explicitly treated as non-additive.
Fund-Flow Traversal
The traversal engine supports:
multi-hop tracing
intermediary wallets
peeling chains
fan-out
high fragmentation
deferred branches
traversal budgets
unresolved value
mixer boundaries
Traversal limits are treated as computation limits, not forensic proof that no endpoint exists.
VASP & Service Attribution
The attribution layer supports known infrastructure classifications such as:
custodial VASP
deposit/sweep infrastructure
hot wallet
cold storage
DEX
bridge
mixer
unknown service
The registry preserves:
multiple intelligence claims
stale records
conflicting records
provenance
entity role
Known-address attribution is currently stronger than unknown-wallet behavioral clustering.


Stability & Actionability
CryptoTrace evaluates whether endpoint attribution remains stable across attribution hypotheses.
Typical states include:

HIGH
MEDIUM
LOW
UNRESOLVED
Actionability is evidence-oriented and does not generate a generic fraud probability.


Blockchain Support
TRON
Current support includes:
TRX / TRC20 data retrieval
live TRONGrid interaction
transaction traversal
pagination
solidification/finality metadata
provider limitation handling
Historical balance requests are not silently replaced with current balance when archival data is unavailable.
Ethereum
Current support includes:
Ethereum JSON-RPC
transaction lookup
receipts
finalized block information
ERC-20 related processing
historical balance capability where supported by provider
structured provider-limit handling
Public RPC limitations are exposed rather than hidden.
DEX Support
Current implementation includes protocol handling for:
Uniswap V2
Uniswap V3
SunSwap V2
A live Ethereum mainnet Uniswap V3 swap has been decoded from transaction receipt data with:
router identification
pool address
token contracts
token decimals
raw amounts
normalized amounts
event signature
log index
DEX support should still be treated as protocol-specific rather than universal DeFi coverage.
Cross-Chain Bridges
Bridge analysis currently supports structured matching for protocols including:
Hop
Across
Multichain
Stargate
Bridge results distinguish between deterministic and heuristic evidence.
Current bridge validation is primarily synthetic.
Live cross-chain end-to-end validation remains pending.
Mixers & Privacy Boundaries
CryptoTrace does not fabricate deterministic paths through known privacy boundaries.
When evidence becomes insufficient, the system can mark the trace as:

OBFUSCATED
UNRESOLVED
and preserve the unresolved value.


Monitoring & Alerts
The monitoring service supports:
persisted case watchers
checkpoints
restart recovery
duplicate suppression
provider error tracking
provider recovery tracking
case deltas
Internal alert events include support for states such as:
NEW_MOVEMENT
PROVIDER_DEGRADED
PROVIDER_RECOVERED
Additional alert event types exist in the model and may require further trigger integration.
This is near-real-time polling-based monitoring, not a blockchain WebSocket subscription engine.
Investigator Action Packet
Evidence exports include an investigator-oriented action section containing relevant technical information such as:
supported VASP/service endpoint
wallet/address
transaction hashes
blockchain
asset
attribution range
model agreement
trace completeness
unresolved/deferred value
label provenance
provider limitations
suggested record categories
All legal or statutory action remains subject to authorized human review.
CryptoTrace does not automatically decide freezing, preservation, or legal process.
Evidence Package
CryptoTrace can generate:
JSON evidence package
Markdown evidence package
Packages use SHA-256 for integrity verification.
Correct terminology:
SHA-256 integrity-hashed Forensic Evidence Package
The hash is an integrity fingerprint and is not treated as a digital signature.
Advisory Analytics
The project includes local advisory analysis for:
graph topology features
structural patterns
case similarity
cross-case convergence
investigator summaries
These components remain advisory.
Deterministic blockchain evidence remains the primary source of truth.
Synthetic Benchmark Suite
The project includes 16 benchmark scenarios covering cases such as:
direct VASP deposit
commingling
stable and unstable attribution
250-branch fragmentation
peeling chains
DEX transformations
bridge matching
false bridge matches
mixer boundaries
stale labels
conflicting labels
ambiguous anchors
budget exhaustion
convergence
Synthetic scenarios are explicitly separated from live blockchain validation.

Project Structure

CryptoTrace/
├── backend/
│   ├── ai/
│   ├── api/
│   ├── chains/
│   ├── core/
│   ├── protocols/
│   ├── services/
│   ├── storage/
│   └── vasp/
│
├── data/
│   └── test_scenarios.json
│
├── frontend/
│   ├── css/
│   ├── js/
│   └── index.html
│
├── scripts/
│   ├── validate_live_ethereum.py
│   ├── validate_live_tron.py
│   ├── verify_live_dex.py
│   ├── verify_live_ethereum_e2e.py
│   └── verify_live_tron_e2e.py
│
├── tests/
├── main.py
├── requirements.txt
├── pytest.ini
├── .env.example
└── .gitignore






