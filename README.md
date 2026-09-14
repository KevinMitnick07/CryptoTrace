# CryptoTrace

A blockchain forensics and VASP attribution analysis platform for investigating cryptocurrency-related cybercrime cases.

**Project Code:** SIH 26183

---

## 📋 Overview

CryptoTrace is a forensic investigation tool designed to analyze cryptocurrency transaction flows and identify service provider endpoints from victim-reported wallet addresses. The system focuses on preserving data integrity and documenting uncertainty throughout the investigation process.

### Primary Use Cases

- Tracing funds in investment fraud cases
- Analyzing cryptocurrency movement in cybercrime investigations
- Identifying exchange and service provider endpoints
- Documenting transaction paths with confidence metrics
- Generating forensic evidence packages for investigative teams

---

## ✅ Current Status

**Development Stage:** Beta Prototype

### Validated Components
- Python 3.14 compatible backend
- FastAPI-based REST API
- SQLite database persistence
- Frontend visualization interface
- 92+ automated test suite passing
- Multi-blockchain analysis capability
- Transaction traversal engine
- VASP registry integration
- Evidence package generation
- Monitoring and alert system

### Important Notice
⚠️ **This system is in development and should only be used in controlled testing environments. Not suitable for production deployment without comprehensive security review.**

---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend Interface                        │
│              (Transaction Graph Visualization)               │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                   FastAPI Backend Server                     │
│          (REST API, Business Logic, Data Processing)         │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│               Processing Layers                              │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐   │
│  │  Traversal   │  │ Attribution  │  │  VASP Registry  │   │
│  │   Engine     │  │   Analysis   │  │   Integration   │   │
│  └──────────────┘  └──────────────┘  └─────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│              Data Layer & Storage                            │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐   │
│  │   SQLite DB  │  │ Cache Layer  │  │ Configuration   │   │
│  └──────────────┘  └──────────────┘  └─────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│         Blockchain Interaction Providers                     │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐   │
│  │ TRON Network │  │ Ethereum     │  │  Bridge & DEX   │   │
│  │  Analysis    │  │  Analysis    │  │  Protocols      │   │
│  └──────────────┘  └──────────────┘  └─────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 🚀 Key Features

### 1. Multi-Blockchain Analysis
- Support for multiple blockchain networks
- Transaction-level tracing capabilities
- Smart contract interaction analysis
- Cross-chain transaction identification
- Network-specific data retrieval and validation

### 2. Fund Flow Traversal
- Multi-level transaction following
- Address relationship mapping
- Transaction chain analysis
- Value flow tracking across networks
- Configurable traversal depth and limits

### 3. Attribution Analysis
- Multiple attribution hypothesis evaluation
- Value allocation modeling
- Service provider identification
- Confidence scoring system
- Stability analysis across different models

### 4. VASP Registry Integration
- Known service provider database
- Address classification system
- Entity role identification
- Multiple data source support
- Record version tracking

### 5. Evidence Generation
- Structured data export formats
- Integrity verification mechanisms
- Transaction documentation
- Finding summary reports
- Investigator action recommendations

### 6. Monitoring System
- Real-time case tracking
- Transaction movement alerts
- System status monitoring
- Event logging and history
- Provider health tracking

---

## 💻 Technology Stack

| Component | Technology |
|-----------|-----------|
| **Backend Framework** | FastAPI |
| **Runtime Environment** | Python 3.14+ |
| **Database** | SQLite |
| **Frontend** | Vanilla JavaScript / HTML / CSS |
| **Visualization** | Graph rendering library |
| **Testing Framework** | Pytest |
| **API Interaction** | HTTP/REST |

### Code Composition
- **Python:** 73.1% - Backend logic and blockchain analysis
- **JavaScript:** 16.1% - Frontend UI and visualization
- **HTML:** 7.8% - Interface templates
- **CSS:** 3.0% - Styling

---

## 📦 Project Structure

```
CryptoTrace/
├── backend/
│   ├── api/
│   │   ├── routes/               # API endpoint definitions
│   │   └── schemas/              # Request/response models
│   ├── core/
│   │   ├── config.py             # Configuration management
│   │   └── security.py           # Security utilities
│   ├── services/
│   │   ├── analysis_service.py   # Main analysis logic
│   │   ├── data_service.py       # Data retrieval
│   │   └── export_service.py     # Report generation
│   ├── database/
│   │   ├── models.py             # Database models
│   │   └── operations.py         # Database operations
│   ├── providers/
│   │   ├── network_provider.py   # Blockchain connections
│   │   └── registry_provider.py  # VASP registry access
│   ├── main.py                   # Application entry point
│   └── tests/
│       ├── unit/                 # Unit tests
│       ├── integration/          # Integration tests
│       └── fixtures/             # Test data
├── frontend/
│   ├── index.html                # Main page
│   ├── assets/
│   │   ├── css/
│   │   │   └── styles.css        # Styling
│   │   └── js/
│   │       ├── app.js            # Main application
│   │       ├── visualization.js  # Graph rendering
│   │       └── api.js            # API communication
│   └── pages/
│       ├── dashboard.html        # Dashboard view
│       ├── analysis.html         # Analysis view
│       └── results.html          # Results view
├── config/
│   └── application.conf          # Application settings
├── docs/
│   ├── API.md                    # API documentation
│   ├── SETUP.md                  # Setup instructions
│   └── ARCHITECTURE.md           # System architecture
├── requirements.txt              # Python dependencies
├── .gitignore                    # Git ignore rules
└── README.md                     # This file
```

---

## 🔧 Installation & Setup

### Prerequisites
- Python 3.14 or higher
- pip package manager
- SQLite3
- Modern web browser (Chrome, Firefox, Safari, Edge)
- 2GB minimum disk space
- Stable internet connection for blockchain network access

### Installation Steps

1. **Clone the repository:**
   ```bash
   git clone https://github.com/KevinMitnick07/CryptoTrace.git
   cd CryptoTrace
   ```

2. **Set up Python environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate
   # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure application:**
   - Copy configuration template
   - Update settings as needed
   - Verify network connectivity
   - Test database initialization

5. **Initialize database:**
   ```bash
   python backend/main.py init-db
   ```

6. **Start backend server:**
   ```bash
   python backend/main.py
   ```
   The server will start on `http://localhost:8000`

7. **Access frontend:**
   Open web browser and navigate to the specified frontend URL.

---

## 📖 Usage Guide

### Basic Investigation Workflow

**Step 1: Create Investigation Case**
- Access the investigation creation interface
- Enter case reference identifier
- Input target wallet address
- Select blockchain network
- Set investigation parameters

**Step 2: Configure Analysis Options**
- Choose analysis depth
- Select attribution models
- Set traversal limits
- Configure alert preferences

**Step 3: Execute Analysis**
- Initiate transaction tracing
- Monitor progress in real-time
- View preliminary findings
- Track system activity

**Step 4: Review Results**
- Examine transaction graph
- Analyze attribution data
- Review identified endpoints
- Assess confidence levels

**Step 5: Generate Report**
- Export findings in available formats
- Include supporting documentation
- Verify data integrity
- Prepare investigator packet

---

## 🔍 Analysis Capabilities

### Transaction Analysis
- Trace transaction chains across multiple hops
- Identify address relationships and patterns
- Calculate value movements and allocations
- Detect potential mixing or obfuscation
- Generate transaction flow diagrams

### Attribution Models
The system evaluates multiple coherent attribution approaches:

- **Conservative Model** - Strict value allocation based on confirmed transfers
- **Proportional Model** - Value distribution based on observed transaction percentages
- **FIFO Model** - First-in-first-out allocation methodology
- **LIFO Model** - Last-in-first-out allocation methodology

Each model generates independent findings that are documented separately.

### Network Support
The system can analyze transactions on:
- TRON network transactions and token transfers
- Ethereum network activities and smart contracts
- Cross-chain bridge transactions
- Decentralized exchange interactions
- Known service provider endpoints

---

## 📊 Data Visualization

### Transaction Graph
- Visual representation of transaction relationships
- Node-based wallet/address display
- Edge-based transaction connections
- Interactive graph exploration
- Zoom and pan functionality
- Legend and information display

### Analysis Dashboard
- Case status overview
- Progress indicators
- Key findings summary
- Alert notifications
- Network statistics

---

## 🧪 Testing

### Running Tests

**All tests:**
```bash
pytest
```

**Specific test suite:**
```bash
pytest tests/unit/
pytest tests/integration/
```

**With coverage report:**
```bash
pytest --cov=backend
```

### Test Coverage
- Unit tests for individual components
- Integration tests for system workflows
- Test fixtures for common scenarios
- Mock data for blockchain interactions
- Benchmark test cases

---

## 📤 Exporting Results

### Export Formats
The system supports multiple export formats:

- **JSON Format** - Structured data export for integration
- **Markdown Format** - Human-readable documentation
- **CSV Format** - Spreadsheet-compatible data

### Export Contents
- Case metadata and reference information
- Transaction details and chains
- Attribution analysis results
- Identified endpoints and services
- Confidence assessments
- Analytical findings summary

### Data Integrity
- Checksum verification included
- Export timestamp recorded
- Source data documented
- Version information included

---

## 🚨 Monitoring & Alerts

### Monitoring Features
- Case progress tracking
- Transaction movement detection
- System health monitoring
- Error and anomaly alerts
- Event history logging

### Alert Types
- New transaction detected
- Analysis milestone reached
- System performance alerts
- Configuration notifications
- Integration status updates

---

## 🔒 Security Considerations

### Data Protection
- Input validation on all data entry points
- Output encoding for all displays
- Secure database operations
- Error message sanitization
- Logging of security events

### Best Practices
- Run in isolated testing environment
- Restrict access to authorized personnel only
- Maintain audit logs
- Regular backup procedures
- Monitor system access

### Known Limitations
- This is a prototype system
- Not suitable for production deployment
- Limited real-time blockchain monitoring
- Some blockchain providers have rate limits
- Cross-chain analysis has limitations

---

## ⚠️ Important Disclaimers

### Legal Notice
This system is intended for legitimate investigative purposes only. Users are responsible for:
- Compliance with all applicable laws and regulations
- Proper authorization before analyzing any addresses or transactions
- Accurate documentation of findings
- Following established investigative procedures
- Respecting privacy laws and data protection requirements

### System Limitations
- Results are based on available blockchain data
- Some transaction paths may be incomplete
- Privacy services may obscure transaction details
- Attribution models are analytical tools, not definitive proof
- All findings require human verification

### Not Recommended For
- Automated enforcement actions
- Unauthorized surveillance
- Privacy invasion
- Circumventing legal procedures
- Any activity outside authorized investigation scope

---

## 📚 Documentation

For detailed information, refer to:
- **Setup Guide:** See `/docs/SETUP.md`
- **API Documentation:** See `/docs/API.md`
- **Architecture Details:** See `/docs/ARCHITECTURE.md`
- **Blockchain Support:** See `/docs/BLOCKCHAIN_SUPPORT.md`

---

## 🤝 Contributing

### Development Guidelines
1. Follow existing code structure and naming conventions
2. Add tests for new functionality
3. Ensure all tests pass before submission
4. Document changes and additions
5. Maintain security best practices

### Reporting Issues
- Use GitHub Issues for bug reports
- Provide clear reproduction steps
- Include system information
- Document expected vs. actual behavior

---

## 📞 Support

For questions or support:
- Review project documentation
- Check existing GitHub issues
- Consult project maintainer

---

## 📋 License

[Add your chosen license here]

---

## 🙏 Acknowledgments

Built for the Smart India Hackathon 2026 - Problem Statement 26183

---

**Last Updated:** September 2026
**Maintainer:** KevinMitnick07
**Status:** Under Development
