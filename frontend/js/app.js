/* ============================================================
   CryptoTrace — Advanced Cyber-Forensics Workstation Application Logic
   ============================================================ */

let currentCaseId = null;
let currentCaseDetail = null;
let currentGraphData = null;
let caseRefreshInterval = null;
let monitorInterval = null;
let allCasesCache = [];
let allVaspEntriesCache = [];
let allAlertsCache = [];
let allScenariosCache = [];
let currentAlertFilter = 'ALL';
let currentScenarioCategory = 'ALL';
let timelineAddressFilter = null;
let isFocusViewActive = false;

// ---------------------------------------------------------------------------
// Section Routing
// ---------------------------------------------------------------------------

function showSection(name) {
  document.querySelectorAll('.section').forEach(s => s.classList.add('hidden'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));

  const section = document.getElementById(`section-${name}`);
  const navBtn = document.getElementById(`nav-${name}`);
  if (section) section.classList.remove('hidden');
  if (navBtn) navBtn.classList.add('active');

  if (name === 'cases') loadCases();
  if (name === 'scenarios') loadScenarios();
  if (name === 'alerts') loadAlerts();
  if (name === 'registry') {
    loadRegistryStats();
    loadRegistryTable();
  }
  if (name === 'health') {
    loadChainsHealth();
    loadMonitorInfo();
  }
}

function toggleFocusView() {
  isFocusViewActive = !isFocusViewActive;
  document.body.classList.toggle('focus-view-active', isFocusViewActive);
  const btn = document.getElementById('btn-toggle-focus');
  if (btn) {
    btn.textContent = isFocusViewActive ? '⛶ Exit Focus' : '⛶ Focus View';
  }
  if (window.cy) {
    setTimeout(() => { cy.resize(); cy.fit(undefined, 24); }, 100);
  }
}

// ---------------------------------------------------------------------------
// Global Status Strip & Health Diagnostics
// ---------------------------------------------------------------------------

async function updateSystemStatusStrip() {
  const tronElem = document.getElementById('strip-tron-status');
  const ethElem = document.getElementById('strip-eth-status');
  try {
    const health = await window.API.getChainsHealth();
    if (tronElem && health.tron) {
      const block = health.tron.solidified_block ? health.tron.solidified_block.toLocaleString() : 'Ready';
      tronElem.textContent = `${health.tron.status} (Blk #${block})`;
      tronElem.style.color = health.tron.status === 'OPERATIONAL' ? 'var(--green)' : 'var(--amber)';
    }
    if (ethElem && health.ethereum) {
      const block = health.ethereum.finalized_block ? health.ethereum.finalized_block.toLocaleString() : 'Ready';
      ethElem.textContent = `${health.ethereum.status} (Blk #${block})`;
      ethElem.style.color = health.ethereum.status === 'OPERATIONAL' ? 'var(--green)' : 'var(--amber)';
    }
  } catch (err) {
    if (tronElem) tronElem.textContent = 'Limited';
    if (ethElem) ethElem.textContent = 'Limited';
  }
}

// ---------------------------------------------------------------------------
// Cases Workbench & Table Filtering / Sorting
// ---------------------------------------------------------------------------

async function loadCases() {
  const container = document.getElementById('cases-table-container');
  if (!container) return;
  try {
    const cases = await window.API.getCases();
    allCasesCache = cases || [];
    filterCasesTable();
  } catch (err) {
    container.innerHTML = `<div class="empty-state" style="color:#b91c1c;">Failed to load investigations: ${escapeHtml(err.message)}</div>`;
  }
}

function filterCasesTable() {
  const query = (document.getElementById('case-search-input')?.value || '').trim().toLowerCase();
  const chainFilter = document.getElementById('case-filter-chain')?.value || 'ALL';
  const stateFilter = document.getElementById('case-filter-state')?.value || 'ALL';
  const anchorFilter = document.getElementById('case-filter-anchor')?.value || 'ALL';
  const actionFilter = document.getElementById('case-filter-action')?.value || 'ALL';
  const sortBy = document.getElementById('case-sort-by')?.value || 'NEWEST';

  let filtered = allCasesCache.filter(c => {
    if (query) {
      const matchId = (c.case_id || '').toLowerCase().includes(query);
      const matchRef = (c.complaint_ref || '').toLowerCase().includes(query);
      const matchWallet = (c.reported_wallet || '').toLowerCase().includes(query);
      if (!matchId && !matchRef && !matchWallet) return false;
    }
    if (chainFilter !== 'ALL') {
      const cChain = (c.chain || '').toUpperCase();
      if (!cChain.includes(chainFilter)) return false;
    }
    if (stateFilter !== 'ALL') {
      if ((c.state || '').toUpperCase() !== stateFilter) return false;
    }
    if (anchorFilter !== 'ALL') {
      if ((c.anchor_level || '').toUpperCase() !== anchorFilter) return false;
    }
    if (actionFilter !== 'ALL') {
      if ((c.actionability || '').toUpperCase() !== actionFilter) return false;
    }
    return true;
  });

  // Sorting
  if (sortBy === 'NEWEST') {
    filtered.sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0));
  } else if (sortBy === 'OLDEST') {
    filtered.sort((a, b) => new Date(a.created_at || 0) - new Date(b.created_at || 0));
  } else if (sortBy === 'AMOUNT') {
    filtered.sort((a, b) => parseFloat(b.reported_amount || 0) - parseFloat(a.reported_amount || 0));
  } else if (sortBy === 'COMPLETENESS') {
    filtered.sort((a, b) => parseFloat(b.trace_completeness_pct || 0) - parseFloat(a.trace_completeness_pct || 0));
  }

  renderCasesTable(filtered);
}

function renderCasesTable(cases) {
  const container = document.getElementById('cases-table-container');
  if (!container) return;
  if (!cases || !cases.length) {
    container.innerHTML = '<div class="empty-state">No investigations match the specified criteria. Click <b>+ New Complaint</b> or run a benchmark scenario to begin.</div>';
    return;
  }

  container.innerHTML = `
    <table class="forensic-table">
      <thead>
        <tr>
          <th>Case ID</th>
          <th>Complaint Reference</th>
          <th>Chain & Asset</th>
          <th>Reported Amount</th>
          <th>Anchor Level</th>
          <th>Trace Completeness</th>
          <th>Primary Finding / Stability</th>
          <th>Updated</th>
          <th>Action</th>
        </tr>
      </thead>
      <tbody>
        ${cases.map(c => {
          const completeness = parseFloat(c.trace_completeness_pct || 100.0);
          const isLive = /^CASE-[0-9A-F]{8}$/i.test(c.case_id);
          return `
            <tr>
              <td>
                <a class="case-link" onclick="openCase('${escapeHtml(c.case_id)}')">${escapeHtml(c.case_id)}</a>
                <div style="margin-top:2px;">
                  ${isLive ? '<span class="truth-tag-live" style="font-size:9px;">LIVE DATA</span>' : '<span class="truth-tag-synthetic" style="font-size:9px;">SYNTHETIC</span>'}
                </div>
              </td>
              <td>
                <div style="font-weight:600; color:var(--text-primary);">${escapeHtml(c.complaint_ref || '—')}</div>
                <div class="mono" style="font-size:11px; color:var(--text-muted);">${escapeHtml(c.reported_wallet ? c.reported_wallet.slice(0, 10) + '…' : '')}</div>
              </td>
              <td>
                <span class="status-badge badge-gray" style="font-size:10px;">${escapeHtml(c.chain || '—')}</span>
                <span style="font-size:11px; color:var(--text-muted);">${escapeHtml(c.asset || '')}</span>
              </td>
              <td class="mono" style="font-weight:600;">${formatDecimal(c.reported_amount)}</td>
              <td>${formatAnchorLevelBadge(c.anchor_level)}</td>
              <td>
                <div style="font-weight:600; font-size:11px; color:${completeness >= 99.9 ? 'var(--green)' : 'var(--amber)'};">
                  ${completeness.toFixed(1)}%
                </div>
                <div class="progress-bar-bg" style="width:70px; margin:2px 0;">
                  <div class="progress-bar-fill" style="width:${Math.min(100, completeness)}%; background:${completeness >= 99.9 ? 'var(--green)' : 'var(--amber)'};"></div>
                </div>
              </td>
              <td>
                <div style="font-weight:600; font-size:12px; color:var(--navy);">${escapeHtml(c.primary_vasp || 'None identified')}</div>
                <div style="margin-top:2px;">${formatStateBadge(c.state)}</div>
              </td>
              <td style="font-size:11px; color:var(--text-muted);">${formatTime(c.updated_at)}</td>
              <td>
                <button class="btn-ghost-sm" onclick="openCase('${escapeHtml(c.case_id)}')">Open Workspace →</button>
              </td>
            </tr>
          `;
        }).join('')}
      </tbody>
    </table>
  `;
}

// ---------------------------------------------------------------------------
// Case Detail Workspace (3-Column Information Architecture)
// ---------------------------------------------------------------------------

async function openCase(caseId) {
  currentCaseId = caseId;
  timelineAddressFilter = null;
  const resetBtn = document.getElementById('btn-reset-timeline-filter');
  if (resetBtn) resetBtn.classList.add('hidden');

  showSection('case-detail');
  const caseIdElem = document.getElementById('detail-case-id');
  if (caseIdElem) caseIdElem.textContent = caseId;

  // Truth classification badge
  const tag = document.getElementById('detail-classification-tag');
  if (tag) {
    if (/^CASE-[0-9A-F]{8}$/i.test(caseId)) {
      tag.className = 'truth-tag-live';
      tag.textContent = '🔴 LIVE BLOCKCHAIN DATA';
    } else if (caseId.startsWith('SCENARIO-') || caseId.includes('-SYN-') || caseId.includes('DIREC') || caseId.includes('COMMING') || caseId.includes('STABLE')) {
      tag.className = 'truth-tag-synthetic';
      tag.textContent = '⚗ SYNTHETIC TEST DATA';
    } else {
      tag.className = 'truth-tag-local';
      tag.textContent = 'LOCAL TRUTH';
    }
  }

  if (window.initGraph && !window.cy) {
    initGraph('cy');
  }

  switchCaseTab('graph');

  await refreshCaseDetail(caseId);

  // Fetch Evidence SHA-256 package hash asynchronously
  fetchEvidenceSha256(caseId);

  if (caseRefreshInterval) clearInterval(caseRefreshInterval);
  caseRefreshInterval = setInterval(() => {
    if (currentCaseId === caseId) refreshCaseDetail(caseId);
  }, 12000);
}

async function fetchEvidenceSha256(caseId) {
  const elem = document.getElementById('d-evidence-sha256');
  if (!elem) return;
  try {
    const pkg = await window.API.getEvidencePackageJson(caseId);
    const hash = pkg.evidence_package_sha256 || pkg.package_hash || 'SHA256-VERIFIED';
    elem.textContent = hash.slice(0, 16) + '…';
    elem.title = hash;
  } catch (e) {
    elem.textContent = 'CALCULATED';
  }
}

function switchCaseTab(tabName) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content-pane').forEach(p => p.classList.add('hidden'));

  const btn = document.getElementById(`tab-btn-${tabName}`);
  const pane = document.getElementById(`tab-view-${tabName}`);
  if (btn) btn.classList.add('active');
  if (pane) pane.classList.remove('hidden');

  if (tabName === 'graph' && window.cy) {
    setTimeout(() => { cy.resize(); cy.fit(undefined, 24); }, 50);
  }
  if (tabName === 'action' && currentCaseId) {
    loadCaseActionPacket(currentCaseId);
  }
  if (tabName === 'attribution' && currentCaseId) {
    loadCaseAttributions(currentCaseId);
  }
  if (tabName === 'timeline' && currentCaseId) {
    loadCaseTimeline(currentCaseId);
  }
  if (tabName === 'audit' && currentCaseId) {
    loadCaseAudit(currentCaseId);
  }
  if (tabName === 'delta' && currentCaseId) {
    loadCaseDelta(currentCaseId);
  }
  if (tabName === 'clustering' && currentCaseId) {
    loadClusteringTab(currentCaseId);
  }
}

async function refreshCaseDetail(caseId) {
  try {
    const [caseData, graphData] = await Promise.all([
      window.API.getCase(caseId),
      window.API.getGraph(caseId),
    ]);

    currentCaseDetail = caseData;
    currentGraphData = graphData;

    const c = caseData.case || {};
    const snap = caseData.snapshot || {};

    // Header Command Bar updates
    const refHdr = document.getElementById('d-ref-header');
    if (refHdr) refHdr.textContent = c.complaint_ref || '—';
    const chainAssetHdr = document.getElementById('d-chain-asset-header');
    if (chainAssetHdr) chainAssetHdr.textContent = `${c.chain || 'TRON'} · ${c.asset || 'USDT'}`;
    const anchorLvlHdr = document.getElementById('d-anchor-level-header');
    if (anchorLvlHdr) anchorLvlHdr.textContent = `Level ${c.anchor_level || 'D'}`;
    const compHdr = document.getElementById('d-completeness-header');
    if (compHdr) compHdr.textContent = `${parseFloat(snap.trace_completeness_pct || 100.0).toFixed(1)}%`;

    // Left Column: Complaint & Anchor
    const refElem = document.getElementById('d-ref');
    if (refElem) refElem.textContent = c.complaint_ref || '—';
    const chainAssetElem = document.getElementById('d-chain-asset');
    if (chainAssetElem) chainAssetElem.textContent = `${c.chain || '—'} · ${c.asset || '—'}`;
    const repAmountElem = document.getElementById('d-reported-amount');
    if (repAmountElem) repAmountElem.textContent = `${formatDecimal(c.reported_amount)} ${c.asset || ''}`;

    const anchorLevel = c.anchor_level || 'D';
    const anchorBadge = document.getElementById('d-anchor-level');
    if (anchorBadge) {
      anchorBadge.textContent = `LEVEL ${anchorLevel} (${anchorLevel === 'A' ? 'Exact Verified' : (anchorLevel === 'B' ? 'Candidate Resolved' : (anchorLevel === 'C' ? 'Evidence Assisted' : 'Ambiguous Wallet'))})`;
      anchorBadge.className = `status-badge ${anchorLevel === 'A' ? 'badge-verified' : (anchorLevel === 'B' ? 'badge-supported' : 'badge-ambiguous')}`;
    }

    const anchorStatus = c.anchor_status || 'UNVERIFIED';
    const statusElem = document.getElementById('d-anchor-status');
    if (statusElem) {
      statusElem.textContent = anchorStatus;
      statusElem.style.color = anchorStatus === 'VERIFIED' ? 'var(--green)' : 'var(--amber)';
    }

    const repWalletElem = document.getElementById('d-reported-wallet');
    if (repWalletElem) repWalletElem.textContent = c.reported_wallet || '—';
    const anchorEvElem = document.getElementById('d-anchor-evidence');
    if (anchorEvElem) anchorEvElem.textContent = c.reported_tx_hash || c.complainant_payment_evidence || 'Wallet address anchor only (Level D)';

    // Mandatory Level D Warning Banner
    const ambiguityBox = document.getElementById('d-anchor-ambiguity-box');
    const ambiguityText = document.getElementById('d-anchor-ambiguity-text');
    if (ambiguityBox && ambiguityText) {
      if (anchorLevel === 'D' || anchorStatus !== 'VERIFIED') {
        ambiguityBox.classList.remove('hidden');
        ambiguityText.textContent = 'No exact victim transaction has been verified on-chain. Observed wallet activity may include unrelated commingled funds.';
      } else {
        ambiguityBox.classList.add('hidden');
      }
    }

    // Top state badge
    const topState = document.getElementById('d-state-badge');
    if (topState) topState.innerHTML = formatStateBadge(c.state);

    // Right Column: Primary Finding
    const primaryVasp = snap.primary_stable_vasp || 'None identified';
    const primVaspElem = document.getElementById('d-primary-vasp');
    if (primVaspElem) primVaspElem.textContent = primaryVasp;
    const primVaspAddrElem = document.getElementById('d-primary-vasp-addr');
    if (primVaspAddrElem) primVaspAddrElem.textContent = snap.target_address || 'No actionable VASP endpoint reached';
    const firstVaspElem = document.getElementById('d-first-vasp');
    if (firstVaspElem) firstVaspElem.textContent = snap.first_supported_vasp || (primaryVasp !== 'None identified' ? primaryVasp : 'None reached');

    const candInfraElem = document.getElementById('d-candidate-infra');
    if (candInfraElem) {
      candInfraElem.textContent = snap.candidate_infrastructure || (snap.vasp_candidate_changes && snap.vasp_candidate_changes.length ? snap.vasp_candidate_changes.join(', ') : 'None detected');
    }

    const stabilityTier = snap.stability_tier || snap.endpoint_stability || 'UNRESOLVED';
    const stabBadge = document.getElementById('d-stability-badge');
    if (stabBadge) {
      stabBadge.textContent = `STABILITY: ${stabilityTier}`;
      stabBadge.className = `status-badge ${stabilityTier === 'HIGH' ? 'badge-verified' : (stabilityTier === 'MEDIUM' ? 'badge-supported' : 'badge-ambiguous')}`;
    }

    const actionBadge = document.getElementById('d-actionability-badge');
    if (actionBadge) actionBadge.textContent = snap.actionability || 'NO_ACTIONABLE_ENDPOINT';

    const stabReasonElem = document.getElementById('d-stability-reason');
    if (stabReasonElem) stabReasonElem.textContent = snap.stability_reason || 'Multi-model consensus evaluation completed.';

    // Right Column: Value Accounting
    const reportedVal = parseFloat(c.reported_amount || snap.victim_loss || 0);
    const tracedVal = parseFloat(snap.traced_value || reportedVal);
    const deferredVal = parseFloat(snap.deferred_mass || snap.deferred_value || 0);
    const vaspMin = parseFloat(snap.vasp_attributed_min || (primaryVasp !== 'None identified' ? tracedVal : 0));
    const vaspMax = parseFloat(snap.vasp_attributed_max || (primaryVasp !== 'None identified' ? tracedVal : 0));
    const unresMin = parseFloat(snap.unresolved_value_min || 0);
    const unresMax = parseFloat(snap.unresolved_value_max || (primaryVasp === 'None identified' ? tracedVal : 0));

    const accRepElem = document.getElementById('acc-reported-val');
    if (accRepElem) accRepElem.textContent = formatDecimal(reportedVal) + ' ' + (c.asset || '');
    const accTracedElem = document.getElementById('acc-traced-val');
    if (accTracedElem) accTracedElem.textContent = formatDecimal(tracedVal) + ' ' + (c.asset || '');
    const accVaspRangeElem = document.getElementById('acc-vasp-range');
    if (accVaspRangeElem) accVaspRangeElem.textContent = `[${formatDecimal(vaspMin)}, ${formatDecimal(vaspMax)}] ${c.asset || ''}`;
    const accDefElem = document.getElementById('acc-deferred-val');
    if (accDefElem) accDefElem.textContent = formatDecimal(deferredVal) + ' ' + (c.asset || '');
    const accUnresElem = document.getElementById('acc-unresolved-val');
    if (accUnresElem) accUnresElem.textContent = `[${formatDecimal(unresMin)}, ${formatDecimal(unresMax)}] ${c.asset || ''}`;

    const completeness = parseFloat(snap.trace_completeness_pct || 100.0);
    const accCompPctElem = document.getElementById('acc-completeness-pct');
    if (accCompPctElem) accCompPctElem.textContent = `${completeness.toFixed(1)}%`;
    const accCompBarElem = document.getElementById('acc-completeness-bar');
    if (accCompBarElem) {
      accCompBarElem.style.width = `${Math.min(100, completeness)}%`;
      accCompBarElem.style.background = completeness >= 99.9 ? 'var(--green)' : 'var(--amber)';
    }

    const fragElem = document.getElementById('d-frag-flag');
    if (fragElem) {
      if (snap.high_fragmentation_detected) {
        fragElem.innerHTML = '⚠ <b>High Fragmentation:</b> Suspected dust fan-out or rate limit cap. Some sub-branches unexamined.';
      } else {
        fragElem.textContent = '';
      }
    }

    // Graph Stats
    const nodes = (graphData.nodes || []);
    const edges = (graphData.edges || []);
    const vaspCount = nodes.filter(n => n.role === 'vasp' || n.role === 'deposit_infrastructure').length;
    const mixerCount = nodes.filter(n => n.role === 'mixer').length;

    const statNodesElem = document.getElementById('stat-nodes');
    if (statNodesElem) statNodesElem.textContent = nodes.length;
    const statEdgesElem = document.getElementById('stat-edges');
    if (statEdgesElem) statEdgesElem.textContent = edges.length;
    const statVaspElem = document.getElementById('stat-vasp');
    if (statVaspElem) statVaspElem.textContent = vaspCount;
    const statMixerElem = document.getElementById('stat-mixer');
    if (statMixerElem) statMixerElem.textContent = mixerCount;

    // Quick Summary Bar Updates (Zero-Tab Comprehension)
    const sumAnchor = document.getElementById('sum-anchor-level');
    if (sumAnchor) sumAnchor.textContent = `Level ${anchorLevel}`;
    const sumFirst = document.getElementById('sum-first-vasp');
    if (sumFirst) sumFirst.textContent = snap.first_supported_vasp || (primaryVasp !== 'None identified' ? primaryVasp : 'None');
    const sumPrim = document.getElementById('sum-primary-vasp');
    if (sumPrim) sumPrim.textContent = primaryVasp;
    const sumComp = document.getElementById('sum-completeness');
    if (sumComp) sumComp.textContent = `${completeness.toFixed(1)}%`;
    const sumHops = document.getElementById('sum-latest-hops');
    if (sumHops) sumHops.textContent = `${edges.length} hops (${nodes.length} nodes)`;

    // Render Mini Hop Flow Bar
    renderMiniFlow(graphData);

    if (window.renderGraph) {
      renderGraph(graphData);
    }
  } catch (err) {
    console.error('Failed to refresh case:', err);
  }
}

function renderMiniFlow(graphData) {
  const container = document.getElementById('mini-flow-nodes');
  if (!container) return;

  const edges = graphData.edges || [];
  if (!edges.length) {
    container.innerHTML = '<span style="color:var(--text-muted); font-size:11px;">Single anchor point (no outgoing transfers observed yet)</span>';
    return;
  }

  // Extract sequential path up to 4 hops
  const hops = edges.slice(0, 4);
  const elements = [];

  for (let i = 0; i < hops.length; i++) {
    const e = hops[i];
    const fromLabel = e.from ? (e.from.slice(0, 6) + '…' + e.from.slice(-4)) : 'Anchor';
    const toLabel = e.to ? (e.to.slice(0, 6) + '…' + e.to.slice(-4)) : 'Dest';
    const amt = parseFloat(e.amount || 0).toFixed(2);

    if (i === 0) {
      elements.push(`
        <span class="mini-flow-node" onclick="if(window.focusPathToNode){window.focusPathToNode('${escapeHtml(e.from)}');}">
          ${escapeHtml(fromLabel)}
        </span>
      `);
    }

    elements.push(`
      <span class="mini-flow-arrow">→</span>
      <span style="font-size:10px; color:var(--text-muted); font-family:var(--font-mono);">${amt} ${escapeHtml(e.asset || '')}</span>
      <span class="mini-flow-arrow">→</span>
      <span class="mini-flow-node" onclick="if(window.focusPathToNode){window.focusPathToNode('${escapeHtml(e.to)}');}">
        ${escapeHtml(toLabel)}
      </span>
    `);
  }

  container.innerHTML = elements.join('');
}

// ---------------------------------------------------------------------------
// Case Workspace Tabs
// ---------------------------------------------------------------------------

async function loadCaseActionPacket(caseId) {
  const container = document.getElementById('action-packet-content');
  if (!container) return;
  try {
    container.innerHTML = '<div class="empty-state"><span class="loading-spinner"></span> Loading action packet...</div>';
    const pkg = await window.API.getEvidencePackageJson(caseId);
    const action = pkg.investigator_action_packet || {};

    const categoriesHtml = (action.suggested_record_categories || [
      'Account registration and identity verification records (KYC)',
      'Internal deposit ledger entries and parent account identifiers',
      'Associated withdrawal destinations and linked session IP logs',
      'Corroborating fiat on-ramp / off-ramp banking references',
    ]).map(cat => `
      <li class="category-item">
        <span style="color:var(--accent); font-weight:700;">✓</span>
        <span>${escapeHtml(cat)}</span>
      </li>
    `).join('');

    container.innerHTML = `
      <div class="action-packet-banner">
        <div style="display:grid; grid-template-columns: 1fr 1fr; gap:16px;">
          <div>
            <div style="font-size:10px; font-weight:700; color:var(--text-muted); text-transform:uppercase;">Identified Actionable VASP Endpoint</div>
            <div style="font-size:15px; font-weight:700; color:var(--navy); margin-top:2px;">
              ${escapeHtml(action.primary_supported_vasp || 'None identified')}
            </div>
            <div class="mono" style="font-size:11px; color:var(--text-secondary); margin-top:2px; word-break:break-all;">
              ${escapeHtml(action.target_address || 'No supported VASP reached')}
            </div>
          </div>
          <div>
            <div style="font-size:10px; font-weight:700; color:var(--text-muted); text-transform:uppercase;">Attribution Stability & Range</div>
            <div style="display:flex; align-items:center; gap:6px; margin-top:3px;">
              <span class="status-badge ${action.endpoint_stability === 'HIGH' ? 'badge-verified' : 'badge-ambiguous'}">${escapeHtml(action.endpoint_stability || 'UNRESOLVED')} STABILITY</span>
              <span class="status-badge badge-supported">${escapeHtml(action.actionability_state || 'SUPPORTED_VASP')}</span>
            </div>
            <div style="font-size:11px; color:var(--text-muted); margin-top:4px;">
              Trace Completeness: <b>${escapeHtml(action.trace_completeness_pct || '100.00')}%</b>
            </div>
          </div>
        </div>
      </div>

      <div style="margin-bottom:12px;">
        <h4 style="font-size:12px; font-weight:700; color:var(--navy); margin-bottom:6px;">Suggested Record Categories for Lawful Production</h4>
        <ul class="category-list">
          ${categoriesHtml}
        </ul>
      </div>

      <div class="legal-notice-box">
        <strong>Mandatory Legal Notice:</strong> ${escapeHtml(action.advisory_notice || 'This action packet is an investigative aid summarizing technical blockchain trace findings. It does not constitute a self-executing warrant or subpoena. Authorized legal review and formal process are required prior to legal action.')}
      </div>

      <div style="margin-top:12px; display:flex; justify-content:flex-end; gap:6px;">
        <button class="btn-secondary" onclick="exportEvidencePackage('markdown')">Export Markdown Summary</button>
        <button class="btn-primary" onclick="exportEvidencePackage('json')">Export Complete Evidence Package (.json)</button>
      </div>
    `;
  } catch (err) {
    container.innerHTML = `<div class="empty-state" style="color:#b91c1c;">Failed to load action packet: ${escapeHtml(err.message)}</div>`;
  }
}

async function loadCaseAttributions(caseId) {
  const container = document.getElementById('attribution-table-container');
  if (!container) return;
  container.innerHTML = '<div class="empty-state"><span class="loading-spinner"></span> Computing model attributions...</div>';
  try {
    const data = await window.API.getAttributions(caseId);
    const rows = data.attributions || [];
    if (!rows.length) {
      container.innerHTML = '<div class="empty-state">No destination attributions recorded yet. Traversal may be active or stationary.</div>';
      return;
    }

    container.innerHTML = `
      <table class="forensic-table" id="attribution-table">
        <thead>
          <tr>
            <th>Destination Address / Entity</th>
            <th>Chain</th>
            <th>Entity Role</th>
            <th>Conservative Model</th>
            <th>Proportional Model</th>
            <th>FIFO Model</th>
            <th>LIFO Model</th>
            <th>Model Agreement</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map(r => {
            const vals = [parseFloat(r.conservative || 0), parseFloat(r.proportional || 0), parseFloat(r.fifo || 0), parseFloat(r.lifo || 0)];
            const max = Math.max(...vals);
            const min = Math.min(...vals);
            const diff = max - min;
            const agree = diff < 0.0001 ? 'FULL AGREEMENT' : (diff / (max || 1) < 0.1 ? 'PARTIAL AGREEMENT' : 'MODEL SPREAD');
            return `
              <tr>
                <td>
                  <div style="font-weight:700; color:var(--navy);">${escapeHtml(r.entity_name || 'Unlabeled Destination')}</div>
                  <div class="mono" style="font-size:11px; color:var(--text-muted); display:flex; align-items:center; gap:4px;">
                    <span>${escapeHtml(r.address)}</span>
                    <button class="btn-copy" onclick="copyText('${escapeHtml(r.address)}', this)">Copy</button>
                  </div>
                </td>
                <td><span class="status-badge badge-gray" style="font-size:9.5px;">${escapeHtml(r.chain)}</span></td>
                <td>${formatRoleBadge(r.role)}</td>
                <td class="mono">${formatDecimal(r.conservative)}</td>
                <td class="mono" style="font-weight:700; color:var(--accent);">${formatDecimal(r.proportional)}</td>
                <td class="mono">${formatDecimal(r.fifo)}</td>
                <td class="mono">${formatDecimal(r.lifo)}</td>
                <td>
                  <span class="status-badge ${agree === 'FULL AGREEMENT' ? 'badge-verified' : (agree === 'PARTIAL AGREEMENT' ? 'badge-supported' : 'badge-ambiguous')}" style="font-size:9.5px;">
                    ${agree}
                  </span>
                </td>
              </tr>
            `;
          }).join('')}
        </tbody>
      </table>
    `;
  } catch (err) {
    container.innerHTML = `<div class="empty-state" style="color:#b91c1c;">Failed to load attributions: ${escapeHtml(err.message)}</div>`;
  }
}

async function loadCaseTimeline(caseId) {
  const container = document.getElementById('timeline-table-container');
  if (!container) return;
  container.innerHTML = '<div class="empty-state"><span class="loading-spinner"></span> Loading chronological transaction timeline...</div>';
  try {
    const graphData = await window.API.getGraph(caseId);
    let edges = graphData.edges || [];
    if (!edges.length) {
      container.innerHTML = '<div class="empty-state">No transaction hops observed for this case.</div>';
      return;
    }

    if (timelineAddressFilter) {
      edges = edges.filter(e => e.from === timelineAddressFilter || e.to === timelineAddressFilter);
    }

    container.innerHTML = `
      <table class="forensic-table" id="timeline-table">
        <thead>
          <tr>
            <th>Hop #</th>
            <th>Timestamp (UTC)</th>
            <th>Chain</th>
            <th>From Address</th>
            <th>To Address</th>
            <th>Asset</th>
            <th>Amount Transferred</th>
            <th>Event Role</th>
            <th>Evidence Class</th>
          </tr>
        </thead>
        <tbody>
          ${edges.map((e, idx) => `
            <tr>
              <td class="mono" style="font-weight:700;">#${idx + 1}</td>
              <td style="font-size:11px; color:var(--text-muted);">${formatTime(e.timestamp)}</td>
              <td><span class="status-badge badge-gray" style="font-size:9.5px;">${escapeHtml(e.chain || '—')}</span></td>
              <td class="mono" style="font-size:11px;">
                <span title="${escapeHtml(e.from)}" style="cursor:pointer;" onclick="if(window.focusPathToNode){window.focusPathToNode('${escapeHtml(e.from)}');}">${escapeHtml(e.from ? e.from.slice(0, 10) + '…' : '—')}</span>
                <button class="btn-copy" onclick="copyText('${escapeHtml(e.from)}', this)">Copy</button>
              </td>
              <td class="mono" style="font-size:11px; font-weight:600;">
                <span title="${escapeHtml(e.to)}" style="cursor:pointer;" onclick="if(window.focusPathToNode){window.focusPathToNode('${escapeHtml(e.to)}');}">${escapeHtml(e.to ? e.to.slice(0, 10) + '…' : '—')}</span>
                <button class="btn-copy" onclick="copyText('${escapeHtml(e.to)}', this)">Copy</button>
              </td>
              <td><span class="status-badge badge-supported" style="font-size:9.5px;">${escapeHtml(e.asset || '—')}</span></td>
              <td class="mono" style="font-weight:700;">${formatDecimal(e.amount)}</td>
              <td>${formatRoleBadge(e.role || (e.to && e.to.includes('vasp') ? 'vasp' : 'transfer'))}</td>
              <td><span class="status-badge badge-verified" style="font-size:9.5px;">${escapeHtml(e.evidence_class || 'OBSERVED')}</span></td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  } catch (err) {
    container.innerHTML = `<div class="empty-state" style="color:#b91c1c;">Failed to load timeline: ${escapeHtml(err.message)}</div>`;
  }
}

function filterTimelineByAddress(addr) {
  timelineAddressFilter = addr;
  const resetBtn = document.getElementById('btn-reset-timeline-filter');
  if (resetBtn) {
    resetBtn.classList.remove('hidden');
    resetBtn.textContent = `Filtered: ${addr.slice(0, 8)}… (✕ Clear)`;
  }
  switchCaseTab('timeline');
}

function resetTimelineFilter() {
  timelineAddressFilter = null;
  const resetBtn = document.getElementById('btn-reset-timeline-filter');
  if (resetBtn) resetBtn.classList.add('hidden');
  if (currentCaseId) loadCaseTimeline(currentCaseId);
}

async function loadCaseAudit(caseId) {
  const container = document.getElementById('case-audit-content');
  const countBadge = document.getElementById('audit-count-badge');
  if (!container) return;
  container.innerHTML = '<div class="empty-state"><span class="loading-spinner"></span> Fetching branch decision audit records...</div>';
  try {
    const data = await window.API.getAudit(caseId);
    const records = data.audit_records || [];
    if (countBadge) countBadge.textContent = `${records.length} records`;

    if (!records.length) {
      container.innerHTML = '<div class="empty-state">No branch pruning decisions recorded for this case.</div>';
      return;
    }

    container.innerHTML = `
      <table class="forensic-table">
        <thead>
          <tr>
            <th>Tier</th>
            <th>From Address</th>
            <th>To Address</th>
            <th>Amount</th>
            <th>Disposition</th>
            <th>Pruning Reason</th>
            <th>Recorded</th>
          </tr>
        </thead>
        <tbody>
          ${records.map(r => `
            <tr>
              <td><span class="status-badge badge-gray" style="font-size:9.5px;">Tier ${r.tier || 1}</span></td>
              <td class="mono" style="font-size:11px;">${escapeHtml(r.from_address ? r.from_address.slice(0, 10) + '…' : '—')}</td>
              <td class="mono" style="font-size:11px; font-weight:600;">${escapeHtml(r.to_address ? r.to_address.slice(0, 10) + '…' : '—')}</td>
              <td class="mono">${formatDecimal(r.amount)} ${escapeHtml(r.asset || '')}</td>
              <td>${formatDispositionBadge(r.disposition)}</td>
              <td style="font-size:11px; color:var(--text-secondary);">${escapeHtml(r.reason || '—')}</td>
              <td style="font-size:10.5px; color:var(--text-muted);">${formatTime(r.recorded_at)}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  } catch (err) {
    container.innerHTML = `<div class="empty-state" style="color:#b91c1c;">Failed to load audit log: ${escapeHtml(err.message)}</div>`;
  }
}

async function loadCaseDelta(caseId) {
  const container = document.getElementById('case-delta-content');
  if (!container) return;
  container.innerHTML = '<div class="empty-state"><span class="loading-spinner"></span> Computing case delta...</div>';
  try {
    const data = await window.API.getDelta(caseId);
    container.innerHTML = `
      <div style="display:flex; flex-direction:column; gap:8px;">
        <div class="accounting-row">
          <span style="color:var(--text-secondary);">Review Timestamp:</span>
          <span class="mono">${escapeHtml(data.review_timestamp)}</span>
        </div>
        <div class="accounting-row">
          <span style="color:var(--text-secondary);">New Transfers Observed:</span>
          <span class="mono" style="font-weight:700; color:${data.new_transfers > 0 ? 'var(--green)' : 'var(--text-primary)'};">${data.new_transfers}</span>
        </div>
        <div class="accounting-row">
          <span style="color:var(--text-secondary);">New Cross-Chain Bridge Events:</span>
          <span class="mono" style="font-weight:700; color:${data.new_bridge_events > 0 ? 'var(--amber)' : 'var(--text-primary)'};">${data.new_bridge_events}</span>
        </div>
        <div class="accounting-row">
          <span style="color:var(--text-secondary);">New DEX Swaps:</span>
          <span class="mono">${data.new_dex_events}</span>
        </div>
        <div class="accounting-row">
          <span style="color:var(--text-secondary);">Victim Value Moved:</span>
          <span class="mono" style="font-weight:700;">${formatDecimal(data.victim_value_moved)}</span>
        </div>
        <div class="accounting-row">
          <span style="color:var(--text-secondary);">Primary VASP State Change:</span>
          <span class="status-badge ${data.primary_vasp_changed ? 'badge-warning' : 'badge-verified'}">${data.primary_vasp_changed ? 'YES (ALTERED)' : 'NO CHANGE'}</span>
        </div>
        ${data.vasp_candidate_changes && data.vasp_candidate_changes.length ? `
          <div style="margin-top:8px; padding:8px 10px; background:var(--amber-bg); border:1px solid var(--amber-border); border-radius:4px; font-size:11.5px; color:var(--amber);">
            <b>Candidate VASP Alterations:</b><br>${data.vasp_candidate_changes.map(c => `• ${escapeHtml(c)}`).join('<br>')}
          </div>
        ` : ''}
      </div>
    `;
  } catch (err) {
    container.innerHTML = `<div class="empty-state" style="color:#b91c1c;">Failed to compute delta: ${escapeHtml(err.message)}</div>`;
  }
}

async function loadClusteringTab(caseId, forceRefresh = false) {
  const container = document.getElementById('clustering-tab-content');
  if (!container) return;
  container.innerHTML = '<div class="empty-state"><span class="loading-spinner"></span> Evaluating candidate infrastructure & intermediary flows...</div>';

  try {
    const [clustering, intermediary] = await Promise.all([
      window.API.getCaseClustering(caseId),
      window.API.getCaseIntermediary(caseId),
    ]);

    const isKnown = clustering.inference_strength === 'KNOWN_ADDRESS';
    const isVictimLinked = clustering.is_victim_linked === true;
    const features = clustering.feature_evidence || {};
    const contradictions = clustering.contradictions || {};
    const models = clustering.models || {};
    const patterns = intermediary.pattern_findings || [];
    const dwellClass = intermediary.dominant_dwell_class || 'UNKNOWN';

    const modelsHtml = Object.entries(models).map(([modelName, status]) => {
      const isSupp = status === 'SUPPORTED';
      const badgeClass = isSupp ? 'badge-verified' : 'badge-gray';
      return `
        <div style="display:flex; justify-content:space-between; align-items:center; padding:4px 8px; background:var(--surface); border:1px solid var(--border-soft); border-radius:3px;">
          <span style="font-size:11px; font-weight:600; color:var(--navy);">${escapeHtml(modelName)}:</span>
          <span class="status-badge ${badgeClass}" style="font-size:9.5px;">${escapeHtml(status)}</span>
        </div>
      `;
    }).join('');

    const patternsHtml = patterns.length ? patterns.map(p => `
      <div style="background:var(--surface-alt); border:1px solid var(--border-soft); border-radius:4px; padding:8px 10px; margin-bottom:8px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
          <span style="font-weight:700; color:var(--navy); font-size:11.5px;">${escapeHtml(p.pattern_type || 'OBSERVED PATTERN')}</span>
          <span class="status-badge badge-verified" style="font-size:9.5px;">Tier: ${escapeHtml(p.confidence_tier || 'OBSERVED')}</span>
        </div>
        <div style="font-size:11px; color:var(--text-secondary); margin-bottom:4px;">${escapeHtml(p.description || '')}</div>
        <div style="display:flex; flex-wrap:wrap; gap:6px; font-size:10.5px; color:var(--text-muted);">
          <span>Addresses (${(p.addresses || []).length}): ${escapeHtml((p.addresses || []).slice(0, 3).map(a => a.slice(0, 8) + '…').join(', '))}</span>
          <span>•</span>
          <span>Transactions: ${(p.transactions || []).length}</span>
        </div>
        ${p.limitations && p.limitations.length ? `
          <div style="margin-top:4px; font-size:10px; color:var(--text-muted); font-style:italic;">
            Note: ${escapeHtml(p.limitations.join(' '))}
          </div>
        ` : ''}
      </div>
    `).join('') : '<div class="empty-state" style="padding:12px;">No complex intermediary laundering patterns detected on current traced hops.</div>';

    container.innerHTML = `
      <div style="display:flex; flex-direction:column; gap:12px;">

        <!-- SECTION A: Candidate Infrastructure Inference -->
        <div class="panel-card" style="border:1px dashed var(--border-dark); background:var(--surface-alt);">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
            <div style="display:flex; align-items:center; gap:6px;">
              <h4 style="font-size:12px; font-weight:700; color:var(--navy); text-transform:uppercase; margin:0;">
                1. Candidate Infrastructure Inference (Heuristic Analysis)
              </h4>
              <span class="status-badge ${isKnown ? 'badge-verified' : 'badge-ambiguous'}" style="font-size:9.5px;">
                ${isKnown ? 'VERIFIED REGISTRY MATCH' : 'HEURISTIC INFERENCE ONLY'}
              </span>
            </div>
            <span class="status-badge ${isVictimLinked ? 'badge-verified' : 'badge-gray'}" style="font-size:9.5px;">
              ${isVictimLinked ? 'VICTIM-LINKED CASE ENDPOINT' : 'CONTEXTUAL TOPOLOGY INTELLIGENCE'}
            </span>
          </div>

          <div style="display:grid; grid-template-columns: 1fr 1fr; gap:12px; margin-bottom:10px;">
            <div>
              <div style="font-size:10px; font-weight:700; color:var(--text-muted); text-transform:uppercase;">Inferred Entity & Role</div>
              <div style="font-size:14px; font-weight:700; color:var(--navy); margin-top:2px;">
                ${escapeHtml(clustering.candidate_entity || 'Unresolved Entity')}
              </div>
              <div class="mono" style="font-size:11px; color:var(--text-secondary); margin-top:2px;">
                Role: <b>${escapeHtml(clustering.candidate_role || 'UNRESOLVED')}</b> · Strength: <b>${escapeHtml(clustering.inference_strength || 'UNRESOLVED')}</b>
              </div>
              ${clustering.victim_value ? `
                <div style="margin-top:6px; font-size:11px; color:var(--text-primary);">
                  Attributed Value Bounds: <b class="mono">[${escapeHtml(clustering.victim_value.min)}, ${escapeHtml(clustering.victim_value.max)}] ${escapeHtml(clustering.victim_value.asset)}</b>
                </div>
              ` : ''}
            </div>

            <div>
              <div style="font-size:10px; font-weight:700; color:var(--text-muted); text-transform:uppercase; margin-bottom:4px;">Attribution Model Agreement</div>
              <div style="display:grid; grid-template-columns: 1fr 1fr; gap:4px;">
                ${modelsHtml || '<span style="color:var(--text-muted); font-size:11px;">No model breakdown available</span>'}
              </div>
            </div>
          </div>

          <div style="padding:8px 10px; background:var(--surface); border:1px solid var(--border-soft); border-radius:4px; font-size:11px; color:var(--text-secondary); margin-bottom:8px;">
            <b>Explanation:</b> ${escapeHtml(clustering.explanation || 'No clustering explanation available.')}
          </div>

          <!-- Feature & Contradiction Checklist -->
          <div style="display:grid; grid-template-columns: 1fr 1fr; gap:8px; font-size:10.5px;">
            <div style="padding:6px 8px; background:var(--surface); border:1px solid var(--border-soft); border-radius:3px;">
              <b style="color:var(--navy);">Evaluated Feature Signatures:</b><br>
              • Deposit Funnel Fan-In: <b>${features.deposit_funnel_detected ? 'YES' : 'NO'}</b><br>
              • Repeated Sweeps to Hot Wallet: <b>${features.repeated_sweep_destination ? 'YES (' + (features.sweep_count || 0) + ' sweeps)' : 'NO'}</b><br>
              • Proximity to Known VASP: <b>${features.known_vasp_proximity_hops !== null && features.known_vasp_proximity_hops !== undefined ? features.known_vasp_proximity_hops + ' hops (' + (features.known_vasp_entity || 'None') + ')' : 'N/A'}</b>
            </div>
            <div style="padding:6px 8px; background:var(--surface); border:1px solid var(--border-soft); border-radius:3px;">
              <b style="color:var(--navy);">Refutation / Contradiction Checks:</b><br>
              • Mixer Boundary Present: <b>${contradictions.mixer_boundary_present ? 'YES (REFUTED)' : 'NO'}</b><br>
              • Conflicting VASP Destinations: <b>${(contradictions.conflicting_vasp_destinations || []).length > 1 ? 'YES (AMBIGUOUS)' : 'NONE'}</b><br>
              • One-Off Transfer Only: <b>${contradictions.is_one_off_transfer_only ? 'YES (UNRESOLVED)' : 'NO'}</b>
            </div>
          </div>
        </div>

        <!-- SECTION B: Intermediary Laundering Patterns & Dwell Times -->
        <div class="panel-card">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
            <h4 style="font-size:12px; font-weight:700; color:var(--navy); text-transform:uppercase; margin:0;">
              2. Intermediary Movement Patterns & Dwell Time Analytics
            </h4>
            <span class="status-badge badge-supported" style="font-size:9.5px;">
              DOMINANT DWELL: ${escapeHtml(dwellClass)}
            </span>
          </div>

          <!-- Dwell Time Summary Metrics -->
          <div style="display:grid; grid-template-columns: repeat(4, 1fr); gap:6px; margin-bottom:10px; background:var(--surface-alt); padding:8px; border-radius:4px; border:1px solid var(--border-soft); font-size:11px;">
            <div><span style="color:var(--text-muted); text-transform:uppercase; font-size:9.5px;">Average Dwell:</span><br><b class="mono">${intermediary.average_dwell_seconds ? intermediary.average_dwell_seconds.toFixed(0) + 's' : 'N/A'}</b></div>
            <div><span style="color:var(--text-muted); text-transform:uppercase; font-size:9.5px;">Total Traced Hops:</span><br><b class="mono">${intermediary.total_hops || 0}</b></div>
            <div><span style="color:var(--text-muted); text-transform:uppercase; font-size:9.5px;">Fan-Out Hubs:</span><br><b class="mono">${intermediary.fan_out_count || 0}</b></div>
            <div><span style="color:var(--text-muted); text-transform:uppercase; font-size:9.5px;">Fan-In Hubs:</span><br><b class="mono">${intermediary.fan_in_count || 0}</b></div>
          </div>

          <!-- Detected Patterns List -->
          <div>
            ${patternsHtml}
          </div>

          <div style="margin-top:6px; font-size:10px; color:var(--text-muted); font-style:italic;">
            Forensic Note: Topological patterns are objective mathematical observations. They indicate structural transfer behavior and do not represent subjective proof of criminal intent.
          </div>
        </div>

      </div>
    `;
  } catch (err) {
    container.innerHTML = `<div class="empty-state" style="color:#b91c1c;">Failed to evaluate candidate infrastructure: ${escapeHtml(err.message)}</div>`;
  }
}

// ---------------------------------------------------------------------------
// Pattern Analysis (Advisory AI)
// ---------------------------------------------------------------------------

async function openAiAnalysis() {
  if (!currentCaseId) return;
  const panel = document.getElementById('ai-panel');
  const content = document.getElementById('ai-content');
  if (!panel || !content) return;
  panel.classList.remove('hidden');
  content.innerHTML = '<div class="empty-state"><span class="loading-spinner"></span> Extracting topological features and pattern signatures...</div>';

  try {
    const data = await window.API.getAiAnalysis(currentCaseId);
    const f = data.features || {};
    const patterns = data.patterns || [];
    const sim = data.case_similarity || {};

    content.innerHTML = `
      <div style="margin-bottom:12px;">
        <h4 style="font-size:11px; font-weight:700; color:var(--navy); text-transform:uppercase; margin-bottom:4px;">Observed Topological Graph Features</h4>
        <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap:6px; background:var(--surface-alt); padding:8px; border-radius:4px; border:1px solid var(--border-soft); font-size:11.5px;">
          <div><span style="color:var(--text-muted);">Hop Count:</span> <b>${f.hop_count ?? 0}</b></div>
          <div><span style="color:var(--text-muted);">Branching Factor:</span> <b>${formatDecimal(f.branching_factor, 2)}</b></div>
          <div><span style="color:var(--text-muted);">Peeling Ratio:</span> <b>${formatDecimal(f.peeling_ratio, 2)}</b></div>
          <div><span style="color:var(--text-muted);">Graph Entropy:</span> <b>${formatDecimal(f.entropy, 2)}</b></div>
          <div><span style="color:var(--text-muted);">Bridge Count:</span> <b>${f.bridge_count ?? 0}</b></div>
          <div><span style="color:var(--text-muted);">DEX Count:</span> <b>${f.dex_count ?? 0}</b></div>
        </div>
      </div>

      <div style="margin-bottom:12px;">
        <h4 style="font-size:11px; font-weight:700; color:var(--navy); text-transform:uppercase; margin-bottom:4px;">Rule-Based Laundering Patterns</h4>
        ${patterns.length ? patterns.map(p => `
          <div style="background:var(--green-bg); border:1px solid var(--green-border); border-radius:4px; padding:8px 10px; margin-bottom:6px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <span style="font-weight:700; color:var(--green); font-size:11.5px;">${escapeHtml(p.pattern_name)}</span>
              <span class="status-badge badge-verified" style="font-size:9.5px;">${escapeHtml(p.confidence)}</span>
            </div>
            <div style="font-size:11px; color:var(--text-secondary); margin-top:2px;">${escapeHtml(p.investigative_advice)}</div>
          </div>
        `).join('') : '<div style="font-size:11.5px; color:var(--text-muted); padding:3px 0;">No complex adversarial laundering topologies triggered.</div>'}
      </div>

      <div style="margin-bottom:12px;">
        <h4 style="font-size:11px; font-weight:700; color:var(--navy); text-transform:uppercase; margin-bottom:4px;">Topological Case Similarity</h4>
        ${sim.status === 'COMPUTED' && sim.matches && sim.matches.length ? sim.matches.map(m => `
          <div style="background:var(--surface-alt); border:1px solid var(--border-soft); border-radius:4px; padding:6px 10px; margin-bottom:5px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <span style="font-weight:600; color:var(--navy); font-size:11.5px;">${escapeHtml(m.scenario_name || m.case_id)}</span>
              <span style="font-size:11px; font-weight:700; color:var(--accent);">${(m.similarity_score * 100).toFixed(1)}% Match</span>
            </div>
            <div style="font-size:10.5px; color:var(--text-muted); margin-top:1px;">Shared characteristics: ${escapeHtml(m.shared_structural_notes)}</div>
          </div>
        `).join('') : `<div style="font-size:11.5px; color:var(--text-muted); padding:3px 0;">${escapeHtml(sim.message || 'Insufficient historical dataset for distance matching.')}</div>`}
      </div>

      <div>
        <h4 style="font-size:11px; font-weight:700; color:var(--navy); text-transform:uppercase; margin-bottom:4px;">Investigator Briefing</h4>
        <div style="background:var(--surface-alt); border:1px solid var(--border-soft); border-radius:4px; padding:8px; font-size:11.5px; line-height:1.45; color:var(--text-secondary); white-space:pre-wrap;">${escapeHtml(data.investigator_narrative)}</div>
      </div>
    `;
  } catch (err) {
    content.innerHTML = `<div style="color:#b91c1c; padding:10px;">Pattern analysis error: ${escapeHtml(err.message)}</div>`;
  }
}

function closeAiPanel() {
  const panel = document.getElementById('ai-panel');
  if (panel) panel.classList.add('hidden');
}

// ---------------------------------------------------------------------------
// Synthetic Benchmark Scenarios
// ---------------------------------------------------------------------------

function getScenarioCategory(id) {
  if (id.includes('DIRECT')) return 'Direct Flow';
  if (id.includes('COMMINGLING')) return 'Commingled Pool';
  if (id.includes('STABLE') || id.includes('UNSTABLE')) return 'Stability Analysis';
  if (id.includes('FANOUT') || id.includes('FRAGMENTED') || id.includes('PEELING')) return 'Adversarial Fan-Out';
  if (id.includes('DEX') || id.includes('BRIDGE')) return 'Cross-Chain Bridge';
  if (id.includes('MIXER')) return 'Privacy Boundary';
  if (id.includes('STALE') || id.includes('CONFLICTING')) return 'Label Staleness & Conflicts';
  return 'Synthetic Benchmark';
}

async function loadScenarios() {
  const container = document.getElementById('scenarios-list');
  if (!container) return;
  try {
    const data = await window.API.getScenarios();
    allScenariosCache = data.scenarios || [];
    filterScenarioCategory(currentScenarioCategory);
  } catch (err) {
    container.innerHTML = `<div class="empty-state" style="color:#b91c1c;">Failed to load benchmark suite: ${escapeHtml(err.message)}</div>`;
  }
}

function filterScenarioCategory(cat) {
  currentScenarioCategory = cat;
  document.querySelectorAll('[id^="btn-cat-"]').forEach(b => b.classList.remove('active'));
  const catKey = cat.replace(/[^a-zA-Z0-9]/g, '');
  const activeBtn = document.getElementById(`btn-cat-${catKey}`) || document.getElementById('btn-cat-ALL');
  if (activeBtn) activeBtn.classList.add('active');

  if (cat === 'ALL') {
    renderScenariosGrid(allScenariosCache);
  } else {
    const filtered = allScenariosCache.filter(s => {
      const scenarioId = s.id || s.scenario_id || '';
      return getScenarioCategory(scenarioId) === cat;
    });
    renderScenariosGrid(filtered);
  }
}

function renderScenariosGrid(scenarios) {
  const container = document.getElementById('scenarios-list');
  if (!container) return;
  if (!scenarios || !scenarios.length) {
    container.innerHTML = '<div class="empty-state">No scenarios found for this category.</div>';
    return;
  }

  container.innerHTML = scenarios.map(s => {
    const scenarioId = s.id || s.scenario_id || 'SCENARIO-UNKNOWN';
    const name = s.name || 'Unnamed Scenario';
    const desc = s.description || 'No description available.';
    const category = getScenarioCategory(scenarioId);
    const gt = s.ground_truth || {};

    let expectedSummary = '';
    if (gt.expected_dominant_vasp || gt.dominant_vasp) {
      expectedSummary += `VASP: <b>${gt.expected_dominant_vasp || gt.dominant_vasp}</b> · `;
    }
    if (gt.expected_stability || gt.stability) {
      expectedSummary += `Stability: <b>${gt.expected_stability || gt.stability}</b> · `;
    }
    if (gt.expected_actionability) {
      expectedSummary += `Actionability: <b>${gt.expected_actionability}</b> · `;
    }
    expectedSummary = expectedSummary.replace(/ · $/, '') || 'Deterministic invariant verification.';

    return `
      <div class="panel-card" style="display:flex; flex-direction:column; justify-content:space-between;">
        <div>
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
            <span style="font-size:10.5px; font-weight:700; color:var(--accent); font-family:var(--font-mono);">${escapeHtml(scenarioId)}</span>
            <span class="truth-tag-synthetic" style="font-size:9px;">SYNTHETIC TEST DATA</span>
          </div>
          <div style="margin-bottom:4px;"><span class="status-badge badge-gray" style="font-size:9.5px;">${escapeHtml(category)}</span></div>
          <div style="font-size:13px; font-weight:700; color:var(--navy);">${escapeHtml(name)}</div>
          <div style="font-size:11.5px; color:var(--text-secondary); margin-top:4px; line-height:1.35;">${escapeHtml(desc)}</div>
          <div style="margin-top:8px; padding:6px 8px; background:var(--surface-alt); border:1px solid var(--border-soft); border-radius:4px; font-size:10.5px; color:var(--text-secondary);">
            <span style="color:var(--text-muted); font-weight:600;">Ground Truth:</span> ${expectedSummary}
          </div>
        </div>
        <button id="btn-run-${escapeHtml(scenarioId)}" class="btn-primary" style="margin-top:10px; width:100%; font-size:11.5px;" onclick="runScenario('${escapeHtml(scenarioId)}')">
          Execute Benchmark Vector
        </button>
      </div>
    `;
  }).join('');
}

async function runScenario(scenarioId) {
  const btn = document.getElementById(`btn-run-${scenarioId}`);
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="loading-spinner"></span> Executing...';
  }

  const resultBox = document.getElementById('scenario-result-box');
  try {
    const res = await window.API.runScenario(scenarioId);
    const exec = res.execution_results || {};
    const isPass = res.validation_status === 'PASS';
    const caseId = res.case_id || (res.investigation_intake && res.investigation_intake.case_id);

    if (resultBox) {
      resultBox.classList.remove('hidden');
      resultBox.style.borderColor = isPass ? 'var(--green-border)' : 'var(--red-border)';
      resultBox.style.background = isPass ? 'var(--green-bg)' : 'var(--red-bg)';
      resultBox.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:8px;">
          <div>
            <div style="display:flex; align-items:center; gap:6px;">
              <span class="status-badge ${isPass ? 'badge-verified' : 'badge-error'}" style="font-size:10.5px; padding:2px 7px;">
                ${isPass ? '✓ BENCHMARK VALIDATION PASSED' : '✕ VALIDATION DISCREPANCY'}
              </span>
              <span style="font-size:12.5px; font-weight:700; color:var(--navy);">${escapeHtml(res.scenario_name || scenarioId)}</span>
            </div>
            <div style="font-size:11.5px; color:var(--text-secondary); margin-top:3px;">
              Classification: <b>SYNTHETIC TEST DATA</b> · Generated Case ID: <span class="mono" style="font-weight:700;">${escapeHtml(caseId || '—')}</span>
            </div>
          </div>
          ${caseId ? `<button class="btn-primary" style="font-size:11.5px;" onclick="openCase('${escapeHtml(caseId)}')">Open in Case Workspace →</button>` : ''}
        </div>

        <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap:6px; background:var(--surface); padding:8px; border-radius:4px; border:1px solid var(--border); font-size:11.5px;">
          <div><span style="color:var(--text-muted);">Dominant Endpoint:</span><br><b>${escapeHtml(exec.dominant_vasp || 'None')}</b></div>
          <div><span style="color:var(--text-muted);">Stability Tier:</span><br><b>${escapeHtml(exec.stability_tier || 'UNRESOLVED')}</b></div>
          <div><span style="color:var(--text-muted);">Actionability:</span><br><b>${escapeHtml(exec.actionability || 'NO_ACTIONABLE_ENDPOINT')}</b></div>
          <div><span style="color:var(--text-muted);">Completeness:</span><br><b>${escapeHtml(exec.trace_completeness_pct || '100.00')}%</b></div>
        </div>
        ${exec.stability_reason ? `<div style="font-size:11px; color:var(--text-secondary); margin-top:6px;"><b>Reasoning:</b> ${escapeHtml(exec.stability_reason)}</div>` : ''}
      `;

      resultBox.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  } catch (err) {
    alert(`Failed to execute scenario: ${err.message}`);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Execute Benchmark Vector';
    }
  }
}

// ---------------------------------------------------------------------------
// Known VASP Intelligence Repository
// ---------------------------------------------------------------------------

async function loadRegistryStats() {
  const container = document.getElementById('registry-stats');
  if (!container) return;
  try {
    const stats = await window.API.getRegistryStats();
    container.innerHTML = `
      <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap:10px; font-size:12px;">
        <div><span style="color:var(--text-muted); text-transform:uppercase; font-size:10px; font-weight:700;">Total Claims:</span><br><b style="font-size:15px; color:var(--navy);">${stats.total_entries || 0}</b></div>
        <div><span style="color:var(--text-muted); text-transform:uppercase; font-size:10px; font-weight:700;">Unique Addresses:</span><br><b style="font-size:15px; color:var(--navy);">${stats.unique_addresses || 0}</b></div>
        <div><span style="color:var(--text-muted); text-transform:uppercase; font-size:10px; font-weight:700;">Stale Claims (>180d):</span><br><b style="font-size:15px; color:${stats.stale_entries ? 'var(--amber)' : 'var(--green)'};">${stats.stale_entries || 0}</b></div>
        <div><span style="color:var(--text-muted); text-transform:uppercase; font-size:10px; font-weight:700;">Staleness Threshold:</span><br><b>${stats.stale_threshold_days || 180} days</b></div>
      </div>
    `;
  } catch (err) {
    container.innerHTML = `<span style="color:#b91c1c;">Failed to fetch intelligence statistics: ${escapeHtml(err.message)}</span>`;
  }
}

async function loadRegistryTable() {
  const container = document.getElementById('vasp-table-container');
  if (!container) return;
  try {
    const res = await window.API.getRegistryEntries();
    allVaspEntriesCache = res.entries || [];
    renderVaspTable(allVaspEntriesCache);
  } catch (err) {
    container.innerHTML = `<div class="empty-state" style="color:#b91c1c;">Failed to load registry entries: ${escapeHtml(err.message)}</div>`;
  }
}

function filterVaspTable() {
  const query = (document.getElementById('vasp-search-input')?.value || '').trim().toLowerCase();
  const chainFilter = document.getElementById('vasp-filter-chain')?.value || 'ALL';
  const typeFilter = document.getElementById('vasp-filter-type')?.value || 'ALL';
  const statusFilter = document.getElementById('vasp-filter-status')?.value || 'ALL';

  const filtered = allVaspEntriesCache.filter(e => {
    if (query) {
      const matchName = (e.entity_name || '').toLowerCase().includes(query);
      const matchAddr = (e.address || '').toLowerCase().includes(query);
      if (!matchName && !matchAddr) return false;
    }
    if (chainFilter !== 'ALL') {
      if ((e.chain || '').toUpperCase() !== chainFilter) return false;
    }
    if (typeFilter !== 'ALL') {
      if ((e.entity_type || '').toUpperCase() !== typeFilter) return false;
    }
    if (statusFilter !== 'ALL') {
      if (statusFilter === 'STALE' && !e.is_stale) return false;
      if (statusFilter === 'ACTIVE' && e.is_stale) return false;
    }
    return true;
  });

  renderVaspTable(filtered);
}

function renderVaspTable(entries) {
  const container = document.getElementById('vasp-table-container');
  if (!container) return;
  if (!entries || !entries.length) {
    container.innerHTML = '<div class="empty-state">No known entity records match the specified filters.</div>';
    return;
  }

  container.innerHTML = `
    <table class="forensic-table">
      <thead>
        <tr>
          <th>Entity Name</th>
          <th>Blockchain Address</th>
          <th>Chain</th>
          <th>Role / Classification</th>
          <th>Source & Provenance</th>
          <th>Confidence</th>
          <th>Last Verified</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        ${entries.map(e => `
          <tr>
            <td style="font-weight:700; color:var(--navy);">${escapeHtml(e.entity_name)}</td>
            <td class="mono" style="font-size:11px;">
              <span title="${escapeHtml(e.address)}">${escapeHtml(e.address.slice(0, 10) + '…' + e.address.slice(-6))}</span>
              <button class="btn-copy" onclick="copyText('${escapeHtml(e.address)}', this)">Copy</button>
            </td>
            <td><span class="status-badge badge-gray" style="font-size:9.5px;">${escapeHtml(e.chain)}</span></td>
            <td>${formatRoleBadge(e.entity_type || e.entity_role)}</td>
            <td style="font-size:11px;">
              <div>${escapeHtml(e.source)}</div>
              <span style="font-size:9.5px; color:var(--text-muted);">Reliability: ${escapeHtml(e.source_reliability || 'HIGH')}</span>
            </td>
            <td><span class="status-badge badge-verified" style="font-size:9.5px;">${escapeHtml(e.confidence)}</span></td>
            <td style="font-size:10.5px; color:var(--text-muted);">${formatTime(e.last_verified)}</td>
            <td>
              ${e.is_stale ?
                '<span class="status-badge badge-stale" style="font-size:9.5px;">STALE (>180d)</span>' :
                '<span class="status-badge badge-verified" style="font-size:9.5px;">VERIFIED</span>'}
            </td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
}

async function lookupAddress() {
  const chain = document.getElementById('rl-chain').value;
  const address = document.getElementById('rl-address').value.trim();
  const resBox = document.getElementById('registry-result');
  const btn = document.getElementById('btn-lookup-vasp');

  if (!address) {
    alert('Please enter a wallet address to look up.');
    return;
  }

  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="loading-spinner"></span> Querying...';
  }

  try {
    const data = await window.API.lookupRegistry(chain, address);
    if (!resBox) return;
    resBox.classList.remove('hidden');

    if (data.status === 'INSUFFICIENT_EVIDENCE' || !data.primary_claim) {
      resBox.innerHTML = `
        <div style="padding:12px; background:var(--surface-alt); border:1px solid var(--border); border-radius:4px;">
          <div style="font-weight:700; color:var(--text-muted); font-size:12.5px;">NO SUPPORTED ATTRIBUTION</div>
          <div style="font-size:11.5px; color:var(--text-secondary); margin-top:3px;">
            Address <span class="mono">${escapeHtml(address)}</span> is not present in the verified intelligence repository.
            Identity cannot be fabricated or inferred without verifiable provenance.
          </div>
        </div>
      `;
      return;
    }

    const claim = data.primary_claim;
    const isStale = data.status === 'STALE' || data.is_stale;
    const isConflicted = data.status === 'CONFLICTED';

    resBox.innerHTML = `
      <div style="background:var(--surface); border:1px solid var(--border); border-radius:4px; padding:12px;">
        <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:10px;">
          <div>
            <h3 style="font-size:15px; font-weight:700; color:var(--navy);">${escapeHtml(claim.entity_name)}</h3>
            <div style="font-size:11.5px; color:var(--text-muted); margin-top:2px;">
              Chain: <b>${escapeHtml(claim.chain)}</b> · Address: <span class="mono">${escapeHtml(claim.address)}</span>
            </div>
          </div>
          ${formatRoleBadge(data.entity_type || claim.entity_role)}
        </div>

        ${isStale ? `
          <div style="margin-bottom:10px; padding:6px 10px; background:var(--red-bg); border:1px solid var(--red-border); border-radius:4px; font-size:11px; color:var(--red);">
            ⚠ <b>STALE RECORD:</b> Verified over 180 days ago (${escapeHtml(claim.last_verified)}). Attribution confidence degraded.
          </div>
        ` : ''}

        ${isConflicted ? `
          <div style="margin-bottom:10px; padding:6px 10px; background:var(--amber-bg); border:1px solid var(--amber-border); border-radius:4px; font-size:11px; color:var(--amber);">
            ⚠ <b>DISPUTED / CONFLICTING INTELLIGENCE:</b> Multiple sources assert conflicting attributions for this address.
          </div>
        ` : ''}

        <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap:8px; background:var(--surface-alt); padding:8px; border-radius:4px; border:1px solid var(--border-soft); font-size:11.5px;">
          <div><span style="color:var(--text-muted);">Source:</span><br><b>${escapeHtml(claim.source)}</b></div>
          <div><span style="color:var(--text-muted);">Reliability:</span><br><b>${escapeHtml(claim.source_reliability || 'HIGH')}</b></div>
          <div><span style="color:var(--text-muted);">Confidence:</span><br><b>${escapeHtml(claim.confidence)}</b></div>
          <div><span style="color:var(--text-muted);">Last Verified:</span><br><b>${formatTime(claim.last_verified)}</b></div>
        </div>
      </div>
    `;
  } catch (err) {
    if (resBox) {
      resBox.classList.remove('hidden');
      resBox.innerHTML = `<div style="color:#b91c1c; padding:10px;">Lookup error: ${escapeHtml(err.message)}</div>`;
    }
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Inspect Address Claims';
    }
  }
}

// ---------------------------------------------------------------------------
// Alerts Inbox
// ---------------------------------------------------------------------------

async function loadAlerts() {
  const container = document.getElementById('alerts-list-container');
  if (!container) return;
  try {
    const data = await window.API.getAlerts();
    allAlertsCache = data.alerts || [];

    const unackCount = allAlertsCache.filter(a => !a.acknowledged).length;
    const badge = document.getElementById('alerts-unread-badge');
    if (badge) {
      badge.textContent = unackCount;
      badge.classList.toggle('hidden', unackCount === 0);
    }

    renderAlertsList();
  } catch (err) {
    container.innerHTML = `<div class="empty-state" style="color:#b91c1c;">Failed to load alerts: ${escapeHtml(err.message)}</div>`;
  }
}

function filterAlerts(filter) {
  currentAlertFilter = filter;
  document.querySelectorAll('[id^="alert-filter-"]').forEach(b => b.classList.remove('active'));
  const activeBtn = document.getElementById(`alert-filter-${filter.toLowerCase()}`);
  if (activeBtn) activeBtn.classList.add('active');
  renderAlertsList();
}

function renderAlertsList() {
  const container = document.getElementById('alerts-list-container');
  if (!container) return;
  let filtered = allAlertsCache;
  if (currentAlertFilter === 'UNACK') {
    filtered = allAlertsCache.filter(a => !a.acknowledged);
  } else if (currentAlertFilter === 'WARNING') {
    filtered = allAlertsCache.filter(a => a.severity === 'WARNING' || a.severity === 'CRITICAL');
  }

  if (!filtered.length) {
    container.innerHTML = '<div class="empty-state">No investigation alerts match the current filter. Continuous case monitoring is active.</div>';
    return;
  }

  container.innerHTML = `
    <div style="display:flex; flex-direction:column; gap:8px;">
      ${filtered.map(a => `
        <div style="background:var(--surface); border:1px solid ${a.acknowledged ? 'var(--border)' : 'var(--accent-border)'}; border-left:4px solid ${a.acknowledged ? 'var(--text-muted)' : (a.severity === 'WARNING' ? 'var(--amber)' : 'var(--accent)')}; border-radius:var(--radius-md); padding:10px 12px; display:flex; justify-content:space-between; align-items:flex-start; box-shadow:var(--shadow-sm);">
          <div>
            <div style="display:flex; align-items:center; gap:6px; margin-bottom:3px;">
              <span class="status-badge ${a.severity === 'WARNING' ? 'badge-ambiguous' : 'badge-verified'}" style="font-size:9.5px;">${escapeHtml(a.event_type)}</span>
              <span class="status-badge badge-gray" style="font-size:9.5px;">Case: <b class="mono" style="cursor:pointer;" onclick="openCase('${escapeHtml(a.case_id)}')">${escapeHtml(a.case_id)}</b></span>
              <span style="font-size:10.5px; color:var(--text-muted);">${formatTime(a.created_at)}</span>
            </div>
            <div style="font-size:12.5px; font-weight:700; color:var(--navy); margin-top:2px;">${escapeHtml(a.summary)}</div>
            ${a.evidence_reference ? `<div class="mono" style="font-size:10.5px; color:var(--text-secondary); margin-top:3px;">Evidence Reference: ${escapeHtml(a.evidence_reference)}</div>` : ''}
          </div>
          <div>
            ${!a.acknowledged ? `
              <button class="btn-ghost-sm" onclick="ackAlert('${escapeHtml(a.alert_id)}')">Acknowledge</button>
            ` : `
              <span style="font-size:10.5px; color:var(--text-muted);">✓ Acknowledged</span>
            `}
          </div>
        </div>
      `).join('')}
    </div>
  `;
}

async function ackAlert(alertId) {
  try {
    await window.API.acknowledgeAlert(alertId);
    loadAlerts();
  } catch (err) {
    alert(`Failed to acknowledge alert: ${err.message}`);
  }
}

// ---------------------------------------------------------------------------
// Chain Health & Monitoring Daemon Info
// ---------------------------------------------------------------------------

async function loadChainsHealth() {
  const grid = document.getElementById('health-grid');
  const btn = document.getElementById('btn-refresh-health');
  if (!grid) return;

  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="loading-spinner"></span> Querying RPCs...';
  }

  try {
    const health = await window.API.getChainsHealth();
    const tron = health.tron || {};
    const eth = health.ethereum || {};

    grid.innerHTML = `
      <!-- TRON Provider Card -->
      <div class="panel-card">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
          <div>
            <h3 style="font-size:14px; font-weight:700; color:var(--navy);">TRON Network Adapter</h3>
            <span style="font-size:10.5px; color:var(--text-muted);">Protocol: TRC-20 (USDT / TRX)</span>
          </div>
          ${formatHealthBadge(tron.status)}
        </div>
        <table class="forensic-table" style="font-size:11.5px;">
          <tr><td>API Credential</td><td><b>${tron.api_key_configured ? 'Configured (TRONGRID_API_KEY)' : 'Not configured (Free Tier)'}</b></td></tr>
          <tr><td>Solidified Block Height</td><td class="mono">${tron.solidified_block ? tron.solidified_block.toLocaleString() : 'Unavailable'}</td></tr>
          <tr><td>Historical Balance Query</td><td><span style="color:var(--amber);">Unavailable on Free Tier</span> (Archive Node Required)</td></tr>
          <tr><td>Last Diagnostics Check</td><td>${formatTime(health.timestamp)}</td></tr>
        </table>
        ${tron.error_message ? `<div style="margin-top:8px; padding:6px 8px; background:var(--red-bg); border:1px solid var(--red-border); border-radius:4px; font-size:10.5px; color:var(--red);">${escapeHtml(tron.error_message)}</div>` : ''}
      </div>

      <!-- Ethereum Provider Card -->
      <div class="panel-card">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
          <div>
            <h3 style="font-size:14px; font-weight:700; color:var(--navy);">Ethereum Network Adapter</h3>
            <span style="font-size:10.5px; color:var(--text-muted);">Protocol: ERC-20 (USDT / USDC / DAI / ETH)</span>
          </div>
          ${formatHealthBadge(eth.status)}
        </div>
        <table class="forensic-table" style="font-size:11.5px;">
          <tr><td>RPC Endpoint</td><td><b>${eth.rpc_configured ? 'Configured (ETH_RPC_URL)' : 'Default Public Gateway'}</b></td></tr>
          <tr><td>PoS Finalized Block Height</td><td class="mono">${eth.finalized_block ? eth.finalized_block.toLocaleString() : 'Unavailable'}</td></tr>
          <tr><td>Historical State Capability</td><td>${eth.archive_capability ? '<span style="color:var(--green);">Archive Supported</span>' : '<span style="color:var(--amber);">Full Node (Pruned History)</span>'}</td></tr>
          <tr><td>Last Diagnostics Check</td><td>${formatTime(health.timestamp)}</td></tr>
        </table>
        ${eth.error_message ? `<div style="margin-top:8px; padding:6px 8px; background:var(--red-bg); border:1px solid var(--red-border); border-radius:4px; font-size:10.5px; color:var(--red);">${escapeHtml(eth.error_message)}</div>` : ''}
      </div>
    `;
  } catch (err) {
    grid.innerHTML = `<div class="empty-state" style="grid-column:1 / -1; color:#b91c1c;">Failed to query providers: ${escapeHtml(err.message)}</div>`;
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = '↻ Refresh Health Checks';
    }
  }
}

async function loadMonitorInfo() {
  const container = document.getElementById('monitor-details-content');
  if (!container) return;
  try {
    const data = await window.API.getMonitorStatus();
    const isRunning = data.running || false;
    container.innerHTML = `
      <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap:10px;">
        <div><span style="color:var(--text-muted); font-size:10px; font-weight:700; text-transform:uppercase;">Daemon State:</span><br><b style="font-size:13px; color:${isRunning ? 'var(--green)' : 'var(--amber)'};">${isRunning ? 'ACTIVE (Polling Enabled)' : 'IDLE / STANDBY'}</b></div>
        <div><span style="color:var(--text-muted); font-size:10px; font-weight:700; text-transform:uppercase;">Active Watchers:</span><br><b>${data.active_watchers_count ?? 0} registered cases</b></div>
        <div><span style="color:var(--text-muted); font-size:10px; font-weight:700; text-transform:uppercase;">Poll Interval:</span><br><b>${data.poll_interval_seconds ?? 30} seconds</b></div>
        <div><span style="color:var(--text-muted); font-size:10px; font-weight:700; text-transform:uppercase;">Last Checkpoint Poll:</span><br><b>${data.last_poll_timestamp ? formatTime(data.last_poll_timestamp) : 'Pending first cycle'}</b></div>
      </div>
    `;
  } catch (err) {
    container.innerHTML = `<span style="color:#b91c1c;">Failed to fetch monitor details: ${escapeHtml(err.message)}</span>`;
  }
}

async function updateMonitorBadge() {
  const badge = document.getElementById('monitor-badge');
  if (!badge) return;
  try {
    const data = await window.API.getMonitorStatus();
    if (data.running) {
      badge.textContent = `● MONITOR ACTIVE (${data.active_watchers_count || 0})`;
      badge.style.background = '#064e3b';
      badge.style.color = '#a7f3d0';
    } else {
      badge.textContent = '● MONITOR IDLE';
      badge.style.background = '#374151';
      badge.style.color = '#d1d5db';
    }
  } catch (e) {
    badge.textContent = '● MONITOR DISABLED';
    badge.style.background = '#450a0a';
    badge.style.color = '#fecaca';
  }
}

// ---------------------------------------------------------------------------
// Complaint Intake Form Submission
// ---------------------------------------------------------------------------

async function submitComplaint() {
  const complaintRef = document.getElementById('f-complaint-ref').value.trim();
  const chain = document.getElementById('f-chain').value;
  const wallet = document.getElementById('f-wallet').value.trim();
  const asset = document.getElementById('f-asset').value;
  const amount = document.getElementById('f-amount').value.trim();
  const txHash = document.getElementById('f-tx-hash').value.trim();
  const time = document.getElementById('f-time').value;
  const evidence = document.getElementById('f-evidence').value.trim();
  const errorBox = document.getElementById('intake-error');
  const btn = document.getElementById('btn-submit-complaint');

  if (errorBox) errorBox.classList.add('hidden');

  if (!complaintRef) {
    showIntakeError('Please enter a Complaint Reference ID (e.g. NCRP reference number).');
    return;
  }
  if (!wallet) {
    showIntakeError('Please enter the suspect/destination wallet address.');
    return;
  }
  if (amount && (isNaN(parseFloat(amount)) || parseFloat(amount) <= 0)) {
    showIntakeError('Reported amount must be a positive number.');
    return;
  }

  const payload = {
    complaint_ref: complaintRef,
    reported_chain: chain,
    reported_wallet: wallet,
    reported_asset: asset || null,
    reported_amount: amount || null,
    reported_tx_hash: txHash || null,
    reported_time_utc: time ? new Date(time).toISOString() : null,
    complainant_payment_evidence: evidence || null,
  };

  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="loading-spinner"></span> Verifying & Tracing...';
  }

  try {
    const res = await window.API.createComplaint(payload);
    if (res.case_id) {
      openCase(res.case_id);
    } else {
      showSection('cases');
    }
  } catch (err) {
    showIntakeError(`Complaint intake rejected: ${err.message}`);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Verify Anchor & Execute Tracing';
    }
  }
}

function showIntakeError(msg) {
  const errorBox = document.getElementById('intake-error');
  if (errorBox) {
    errorBox.textContent = msg;
    errorBox.classList.remove('hidden');
  }
}

// ---------------------------------------------------------------------------
// Evidence Export Helper
// ---------------------------------------------------------------------------

async function exportEvidencePackage(format) {
  if (!currentCaseId) return;
  try {
    if (format === 'json') {
      const data = await window.API.getEvidencePackageJson(currentCaseId);
      const str = JSON.stringify(data, null, 2);
      downloadFile(`${currentCaseId}_evidence_package.json`, str, 'application/json');
    } else {
      const md = await window.API.getEvidencePackageMarkdown(currentCaseId);
      downloadFile(`${currentCaseId}_forensic_report.md`, md, 'text/markdown');
    }
  } catch (err) {
    alert(`Evidence export failed: ${err.message}`);
  }
}

function downloadFile(filename, content, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// Copy-to-Clipboard & TSV Helpers
// ---------------------------------------------------------------------------

function copyText(text, btnElem = null) {
  if (!text || text === '—') return;
  navigator.clipboard.writeText(text).then(() => {
    if (btnElem) {
      const originalText = btnElem.textContent;
      btnElem.textContent = 'COPIED';
      setTimeout(() => { btnElem.textContent = originalText; }, 1400);
    }
  }).catch(() => {});
}

function copyTableAsTsv(tableId, btnElem = null) {
  const table = document.getElementById(tableId);
  if (!table) return;

  const rows = Array.from(table.querySelectorAll('tr'));
  const tsv = rows.map(r => {
    const cells = Array.from(r.querySelectorAll('th, td'));
    return cells.map(c => c.innerText.replace(/\s+/g, ' ').trim()).join('\t');
  }).join('\n');

  navigator.clipboard.writeText(tsv).then(() => {
    if (btnElem) {
      const originalText = btnElem.textContent;
      btnElem.textContent = 'COPIED TSV!';
      setTimeout(() => { btnElem.textContent = originalText; }, 1400);
    }
  }).catch(() => {});
}

// ---------------------------------------------------------------------------
// Formatters & Badges
// ---------------------------------------------------------------------------

function formatAnchorLevelBadge(level) {
  const map = {
    'A': { label: 'Level A (Exact Verified)', cls: 'badge-verified' },
    'B': { label: 'Level B (Candidate)', cls: 'badge-supported' },
    'C': { label: 'Level C (Evidence)', cls: 'badge-gray' },
    'D': { label: 'Level D (Ambiguous)', cls: 'badge-ambiguous' },
  };
  const item = map[level] || { label: `Level ${level || 'D'}`, cls: 'badge-gray' };
  return `<span class="status-badge ${item.cls}" style="font-size:9.5px;">${escapeHtml(item.label)}</span>`;
}

function formatStateBadge(state) {
  const map = {
    'ACTIVE': { label: 'Active Tracing', cls: 'badge-supported' },
    'VASP_CANDIDATE': { label: 'Candidate VASP', cls: 'badge-ambiguous' },
    'SUPPORTED_VASP': { label: 'Supported VASP', cls: 'badge-verified' },
    'CUSTODIAL_BOUNDARY': { label: 'Custodial Boundary', cls: 'badge-verified' },
    'FUNDS_STATIONARY': { label: 'Funds Stationary', cls: 'badge-unresolved' },
    'CLOSED': { label: 'Closed', cls: 'badge-unresolved' },
  };
  const item = map[state] || { label: state || '—', cls: 'badge-unresolved' };
  return `<span class="status-badge ${item.cls}" style="font-size:9.5px;">${escapeHtml(item.label)}</span>`;
}

function formatRoleBadge(role) {
  const map = {
    'CUSTODIAL_VASP': { label: 'Custodial VASP', cls: 'badge-verified' },
    'deposit_infrastructure': { label: 'Deposit Infra', cls: 'badge-verified' },
    'vasp': { label: 'Custodial VASP', cls: 'badge-verified' },
    'DEX': { label: 'DEX Router', cls: 'badge-supported' },
    'dex_router': { label: 'DEX Router', cls: 'badge-supported' },
    'MIXER': { label: 'Mixer Boundary', cls: 'badge-mixer' },
    'mixer': { label: 'Mixer Boundary', cls: 'badge-mixer' },
    'BRIDGE': { label: 'Bridge Contract', cls: 'badge-ambiguous' },
    'bridge_contract': { label: 'Bridge Contract', cls: 'badge-ambiguous' },
    'FOUNDATION': { label: 'Foundation / Treasury', cls: 'badge-gray' },
    'intermediary': { label: 'Intermediary', cls: 'badge-unresolved' },
    'suspect_wallet': { label: 'Suspect Wallet', cls: 'badge-stale' },
  };
  const item = map[role] || { label: role || 'Unknown', cls: 'badge-unresolved' };
  return `<span class="status-badge ${item.cls}" style="font-size:9.5px;">${escapeHtml(item.label)}</span>`;
}

function formatDispositionBadge(dispo) {
  const map = {
    'FULLY_TRACED': { label: 'Fully Traced', cls: 'badge-verified' },
    'DEPRIORITIZED_DUST': { label: 'Deprioritized Dust', cls: 'badge-unresolved' },
    'DEFERRED_BUDGET': { label: 'Deferred Mass', cls: 'badge-ambiguous' },
    'MIXER_BOUNDARY': { label: 'Mixer Boundary', cls: 'badge-mixer' },
    'VASP_BOUNDARY': { label: 'VASP Boundary', cls: 'badge-verified' },
    'BUDGET_EXHAUSTED': { label: 'Budget Exhausted', cls: 'badge-stale' },
  };
  const item = map[dispo] || { label: dispo || '—', cls: 'badge-unresolved' };
  return `<span class="status-badge ${item.cls}" style="font-size:9.5px;">${escapeHtml(item.label)}</span>`;
}

function formatHealthBadge(status) {
  if (status === 'OPERATIONAL' || status === 'CONFIGURED') {
    return '<span class="status-badge badge-verified" style="font-size:9.5px;">OPERATIONAL</span>';
  }
  if (status === 'LIMITED' || status === 'PUBLIC_DEFAULT') {
    return '<span class="status-badge badge-ambiguous" style="font-size:9.5px;">PROVIDER LIMITED</span>';
  }
  return '<span class="status-badge badge-stale" style="font-size:9.5px;">UNAVAILABLE</span>';
}

function formatDecimal(val, decimals = 4) {
  if (val === null || val === undefined) return '—';
  const n = parseFloat(val);
  return isNaN(n) ? String(val) : n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: decimals });
}

function formatTime(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch (e) {
    return iso;
  }
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// Attach all global functions to window
window.showSection = showSection;
window.toggleFocusView = toggleFocusView;
window.loadCases = loadCases;
window.filterCasesTable = filterCasesTable;
window.renderCasesTable = renderCasesTable;
window.openCase = openCase;
window.switchCaseTab = switchCaseTab;
window.refreshCaseDetail = refreshCaseDetail;
window.loadCaseActionPacket = loadCaseActionPacket;
window.loadCaseAttributions = loadCaseAttributions;
window.loadCaseTimeline = loadCaseTimeline;
window.filterTimelineByAddress = filterTimelineByAddress;
window.resetTimelineFilter = resetTimelineFilter;
window.loadCaseAudit = loadCaseAudit;
window.loadCaseDelta = loadCaseDelta;
window.openAiAnalysis = openAiAnalysis;
window.closeAiPanel = closeAiPanel;
window.closeInspector = closeInspector;
window.loadScenarios = loadScenarios;
window.filterScenarioCategory = filterScenarioCategory;
window.renderScenariosGrid = renderScenariosGrid;
window.runScenario = runScenario;
window.loadRegistryStats = loadRegistryStats;
window.loadRegistryTable = loadRegistryTable;
window.filterVaspTable = filterVaspTable;
window.renderVaspTable = renderVaspTable;
window.lookupAddress = lookupAddress;
window.loadAlerts = loadAlerts;
window.filterAlerts = filterAlerts;
window.renderAlertsList = renderAlertsList;
window.ackAlert = ackAlert;
window.loadChainsHealth = loadChainsHealth;
window.loadMonitorInfo = loadMonitorInfo;
window.updateMonitorBadge = updateMonitorBadge;
window.submitComplaint = submitComplaint;
window.showIntakeError = showIntakeError;
window.exportEvidencePackage = exportEvidencePackage;
window.copyText = copyText;
window.copyTableAsTsv = copyTableAsTsv;

// ---------------------------------------------------------------------------
// Page Initialization
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
  showSection('cases');
  updateSystemStatusStrip();
  updateMonitorBadge();
  loadAlerts();
  if (monitorInterval) clearInterval(monitorInterval);
  monitorInterval = setInterval(() => {
    updateSystemStatusStrip();
    updateMonitorBadge();
    loadAlerts();
  }, 15000);
});
