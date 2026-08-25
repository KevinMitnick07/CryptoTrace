/* app.js — Case management, synthetic benchmarks, evidence exports, AI analytics UI. */

let currentCaseId = null;
let caseRefreshInterval = null;
let monitorInterval = null;

// ---------------------------------------------------------------------------
// Section routing
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
  if (name === 'registry') loadRegistryStats();
  if (name === 'health') {
    loadChainsHealth();
    loadMonitorInfo();
  }
}

// ---------------------------------------------------------------------------
// Cases list
// ---------------------------------------------------------------------------

async function loadCases() {
  const container = document.getElementById('cases-list');
  try {
    const cases = await API.getCases();
    if (!cases || !cases.length) {
      container.innerHTML = '<div class="empty-state">No cases recorded. Enter a complaint or run a benchmark scenario to begin.</div>';
      return;
    }
    container.innerHTML = `
      <div class="cases-header">
        <span class="col-header">Case ID</span>
        <span class="col-header">Complaint Reference</span>
        <span class="col-header">Investigation State</span>
        <span class="col-header">Traceability</span>
        <span class="col-header">Actionability</span>
        <span class="col-header">Updated</span>
      </div>
      ${cases.map(c => `
        <div class="case-row" onclick="openCase('${c.case_id}')">
          <span class="case-id truncate">${c.case_id}</span>
          <span class="case-ref truncate">${escapeHtml(c.complaint_ref)}</span>
          <span>${formatStateBadge(c.state)}</span>
          <span>${formatTraceBadge(c.traceability)}</span>
          <span>${formatActionBadge(c.actionability)}</span>
          <span class="case-updated">${formatTime(c.updated_at)}</span>
        </div>
      `).join('')}
    `;
  } catch (err) {
    container.innerHTML = `<div class="empty-state" style="color:#991b1b;">Failed to load cases: ${escapeHtml(err.message)}</div>`;
  }
}

// ---------------------------------------------------------------------------
// Synthetic Benchmark Scenarios
// ---------------------------------------------------------------------------

function getScenarioCategory(id) {
  if (id.includes('DIRECT')) return 'Direct Flow';
  if (id.includes('COMMINGLING')) return 'Commingled Pool';
  if (id.includes('STABLE') || id.includes('UNSTABLE')) return 'Stability Analysis';
  if (id.includes('FANOUT') || id.includes('FRAGMENTED')) return 'Adversarial Fan-Out';
  if (id.includes('PEELING')) return 'Peeling Chain';
  if (id.includes('DEX')) return 'DEX Transformation';
  if (id.includes('BRIDGE')) return 'Cross-Chain Bridge';
  if (id.includes('MIXER')) return 'Privacy Boundary';
  if (id.includes('STALE')) return 'Label Staleness';
  if (id.includes('CONFLICTING')) return 'Disputed Intelligence';
  if (id.includes('AMBIGUOUS')) return 'Anchor Ambiguity';
  if (id.includes('BUDGET')) return 'Hop Cap Exhaustion';
  if (id.includes('CONVERGENCE')) return 'Popularity Discount';
  return 'Synthetic Benchmark';
}

async function loadScenarios() {
  const container = document.getElementById('scenarios-list');
  try {
    const data = await API.getScenarios();
    const scenarios = data.scenarios || [];
    if (!scenarios.length) {
      container.innerHTML = '<div class="empty-state">No benchmark scenarios found in dataset.</div>';
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
      if (gt.match_strength) {
        expectedSummary += `Match: <b>${gt.match_strength}</b> · `;
      }
      if (gt.traceability_state) {
        expectedSummary += `Trace: <b>${gt.traceability_state}</b> · `;
      }
      if (!expectedSummary) {
        expectedSummary = `Expected Actionability: <b>${gt.expected_actionability || 'SUPPORTED_VASP'}</b>`;
      } else {
        expectedSummary = expectedSummary.replace(/ · $/, '');
      }

      return `
        <div class="scenario-card">
          <div>
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <span style="font-size:10px; font-weight:700; color:#1d4ed8; font-family:'IBM Plex Mono', monospace; text-transform:uppercase;">${escapeHtml(scenarioId)}</span>
              <span class="status-badge" style="background:#f1f5f9; color:#475569; font-size:9px;">SYNTHETIC TEST DATA</span>
            </div>
            <div style="font-size:11px; font-weight:600; color:#64748b; margin-top:2px;">Category: ${escapeHtml(category)}</div>
            <div style="font-size:14px; font-weight:600; color:#111318; margin-top:6px;">${escapeHtml(name)}</div>
            <div style="font-size:12px; color:#4b5563; margin-top:6px; line-height:1.4;">${escapeHtml(desc)}</div>
            <div style="margin-top:12px; padding:8px 10px; background:#f8fafc; border:1px solid #e2e8f0; border-radius:4px; font-size:11px; color:#334155;">
              <span style="color:#64748b; font-weight:500;">Ground Truth:</span> ${expectedSummary}
            </div>
          </div>
          <button id="btn-run-${escapeHtml(scenarioId)}" class="btn-primary" style="margin-top:14px; width:100%; font-size:12px;" onclick="runScenario('${escapeHtml(scenarioId)}')">Run Benchmark</button>
        </div>
      `;
    }).join('');
  } catch (err) {
    container.innerHTML = `<div class="empty-state" style="color:#991b1b;">Failed to load scenarios: ${escapeHtml(err.message)}</div>`;
  }
}

async function runScenario(scenarioId) {
  const btn = document.getElementById(`btn-run-${scenarioId}`);
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="loading"></span> Running...';
  }

  const resultBox = document.getElementById('scenario-result-box');
  try {
    const res = await API.runScenario(scenarioId);
    const exec = res.execution_results || {};
    const isPass = res.validation_status === 'PASS';
    const caseId = res.case_id || (res.investigation_intake && res.investigation_intake.case_id);

    resultBox.classList.remove('hidden');
    resultBox.style.borderColor = isPass ? '#10b981' : '#ef4444';
    resultBox.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:10px;">
        <div>
          <div style="display:flex; align-items:center; gap:8px;">
            <span class="status-badge" style="background:${isPass ? '#f0fdf4' : '#fef2f2'}; color:${isPass ? '#166534' : '#991b1b'}; border:1px solid ${isPass ? '#bbf7d0' : '#fecaca'}; font-size:12px; padding:4px 10px;">
              ${isPass ? '✓ BENCHMARK VALIDATION PASSED' : '✕ VALIDATION FAILED'}
            </span>
            <span style="font-size:13px; font-weight:600; color:#1a3a5c;">${escapeHtml(res.scenario_name || scenarioId)}</span>
          </div>
          <div style="font-size:12px; color:#4b5563; margin-top:4px;">
            Classification: <b>SYNTHETIC TEST DATA</b> · Case Created: <span class="mono">${escapeHtml(caseId || '—')}</span>
          </div>
        </div>
        ${caseId ? `<button class="btn-primary" style="font-size:12px;" onclick="openCase('${escapeHtml(caseId)}')">Open in Case Workspace →</button>` : ''}
      </div>

      <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap:10px; background:#f8fafc; padding:12px; border-radius:4px; border:1px solid #e2e8f0; font-size:12px;">
        <div><span style="color:#64748b;">Dominant Endpoint:</span><br><b>${escapeHtml(exec.dominant_vasp || 'None')}</b></div>
        <div><span style="color:#64748b;">Stability Tier:</span><br><b>${escapeHtml(exec.stability_tier || 'UNRESOLVED')}</b></div>
        <div><span style="color:#64748b;">Actionability:</span><br><b>${escapeHtml(exec.actionability || 'NO_ACTIONABLE_ENDPOINT')}</b></div>
        <div><span style="color:#64748b;">Completeness:</span><br><b>${escapeHtml(exec.trace_completeness_pct || '100.00')}%</b></div>
      </div>
      ${exec.stability_reason ? `<div style="font-size:11px; color:#64748b; margin-top:8px;">Reason: ${escapeHtml(exec.stability_reason)}</div>` : ''}
    `;

    // Scroll to result box smoothly
    resultBox.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (err) {
    alert(`Failed to execute scenario: ${err.message}`);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Run Benchmark';
    }
  }
}

// ---------------------------------------------------------------------------
// Case Detail Workspace
// ---------------------------------------------------------------------------

async function openCase(caseId) {
  currentCaseId = caseId;
  showSection('case-detail');
  document.getElementById('detail-case-id').textContent = caseId;

  // Tag classification based on case ID origin
  // CASE-{8 hex chars}  = real complaint intake
  // SCENARIO-{id}       = synthetic benchmark
  const tag = document.getElementById('detail-classification-tag');
  if (tag) {
    if (/^CASE-[0-9A-F]{8}$/i.test(caseId)) {
      // Real case from complaint intake
      tag.innerHTML = '🔴 LIVE BLOCKCHAIN DATA';
      tag.style.background = '#fef2f2';
      tag.style.color = '#991b1b';
      tag.style.border = '1px solid #fecaca';
    } else if (caseId.startsWith('SCENARIO-') || caseId.includes('-SYN-')) {
      tag.innerHTML = '⚗ SYNTHETIC TEST DATA';
      tag.style.background = '#eff6ff';
      tag.style.color = '#1d4ed8';
      tag.style.border = '1px solid #bfdbfe';
    } else {
      tag.innerHTML = '⚠ DATA SOURCE UNCLASSIFIED';
      tag.style.background = '#fffbeb';
      tag.style.color = '#92400e';
      tag.style.border = '1px solid #fde68a';
    }
  }

  if (window.initGraph && !window.cy) {
    initGraph('cy');
  }

  // Switch to graph tab by default
  switchCaseTab('graph');

  await refreshCaseDetail(caseId);

  if (caseRefreshInterval) clearInterval(caseRefreshInterval);
  caseRefreshInterval = setInterval(() => {
    if (currentCaseId === caseId) refreshCaseDetail(caseId);
  }, 12000);
}

function switchCaseTab(tabName) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.case-tab-pane').forEach(p => p.classList.add('hidden'));

  const btn = document.getElementById(`tab-btn-${tabName}`);
  const pane = document.getElementById(`tab-view-${tabName}`);
  if (btn) btn.classList.add('active');
  if (pane) pane.classList.remove('hidden');

  if (tabName === 'graph' && window.cy) {
    setTimeout(() => { cy.resize(); cy.fit(); }, 50);
  }
  if (tabName === 'action' && currentCaseId) {
    loadCaseActionPacket(currentCaseId);
  }
  if (tabName === 'attribution' && currentCaseId) {
    loadCaseAttributions(currentCaseId);
  }
  if (tabName === 'audit' && currentCaseId) {
    loadCaseAudit(currentCaseId);
  }
  if (tabName === 'delta' && currentCaseId) {
    loadCaseDelta(currentCaseId);
  }
}

async function refreshCaseDetail(caseId) {
  try {
    const [caseData, graphData] = await Promise.all([
      API.getCase(caseId),
      API.getGraph(caseId),
    ]);

    const c = caseData.case || {};
    const snap = caseData.snapshot || {};

    document.getElementById('d-ref').textContent = c.complaint_ref || '—';
    document.getElementById('d-anchor-level').textContent = c.anchor_level || 'D';
    document.getElementById('d-anchor-level').className = `level-badge ${c.anchor_level === 'D' ? 'level-d-badge' : ''}`;

    const anchorStatus = c.anchor_status || 'UNVERIFIED';
    document.getElementById('d-anchor-status').textContent = anchorStatus;
    document.getElementById('d-anchor-status').className = `status-badge ${anchorStatus === 'VERIFIED' ? 'badge-verified' : 'badge-ambiguous'}`;

    document.getElementById('d-anchor-evidence').textContent = c.reported_wallet || '—';
    document.getElementById('d-primary-vasp').textContent = snap.primary_stable_vasp || 'None identified';
    document.getElementById('d-stability-reason').textContent = snap.stability_reason || 'Stability: UNRESOLVED';
    document.getElementById('d-state').innerHTML = formatStateBadge(c.state);

    const completeness = parseFloat(snap.trace_completeness_pct || '100.0');
    const completenessElem = document.getElementById('d-completeness');
    if (completenessElem) {
      if (completeness < 99.9) {
        completenessElem.innerHTML = `
          <span style="color:#b45309; font-weight:700;">
            ⚠ INCOMPLETE — BUDGET EXHAUSTED (${completeness.toFixed(1)}% traced)
          </span>
          <span style="color:#92400e; font-size:11px; display:block; margin-top:2px;">
            Remaining value may be unexamined. This is a computation limit, not a forensic conclusion.
          </span>`;
      } else {
        completenessElem.textContent = `${completeness.toFixed(1)}% Complete`;
      }
    }

    const fragElem = document.getElementById('d-frag-flag');
    if (fragElem) {
      if (snap.high_fragmentation_detected) {
        fragElem.innerHTML =
          '<span style="color:#b45309; font-weight:600;">⚠ High Fragmentation Detected</span>' +
          '<span style="color:#92400e; font-size:11px; display:block;">' +
          'Suspected dust layering or adapter saturation (adapter returned maximum results). ' +
          'Some branches may not have been examined.</span>';
      } else {
        fragElem.textContent = '';
      }
    }

    const nodes = (graphData.nodes || []);
    const edges = (graphData.edges || []);
    const vaspCount = nodes.filter(n => n.role === 'vasp' || n.role === 'deposit_infrastructure').length;

    document.getElementById('stat-nodes').textContent = nodes.length;
    document.getElementById('stat-edges').textContent = edges.length;
    document.getElementById('stat-vasp').textContent = vaspCount;

    if (window.renderGraph) {
      renderGraph(graphData);
    }
  } catch (err) {
    console.error('Failed to refresh case:', err);
    const caseDetail = document.getElementById('case-detail');
    if (caseDetail) {
      caseDetail.innerHTML = `
        <div style="padding:24px; color:#991b1b; background:#fef2f2; border-radius:8px; border:1px solid #fecaca;">
          <strong>Failed to load case details.</strong><br>
          <span style="font-size:13px;">${escapeHtml(err.message || 'Unknown error')}</span>
        </div>`;
    }
  }
}

// ---------------------------------------------------------------------------
// Case Model Attributions Tab
// ---------------------------------------------------------------------------

async function loadCaseAttributions(caseId) {
  const container = document.getElementById('attribution-table-container');
  container.innerHTML = '<div class="empty-state"><span class="loading"></span> Calculating model attributions...</div>';
  try {
    const data = await API.getAttributions(caseId);
    const rows = data.attributions || [];
    if (!rows.length) {
      container.innerHTML = '<div class="empty-state">No outgoing destination attributions recorded yet.</div>';
      return;
    }

    container.innerHTML = `
      <table class="attribution-table">
        <thead>
          <tr>
            <th>Destination / Entity</th>
            <th>Chain</th>
            <th>Entity Role</th>
            <th>Conservative</th>
            <th>Proportional</th>
            <th>FIFO</th>
            <th>LIFO</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map(r => `
            <tr>
              <td>
                <div style="font-weight:600; color:#1a3a5c;">${escapeHtml(r.entity_name || 'Unlabeled Destination')}</div>
                <div class="mono" style="font-size:11px; color:#64748b;">${escapeHtml(r.address)}</div>
              </td>
              <td><span class="status-badge" style="background:#f1f5f9; color:#475569; font-size:10px;">${escapeHtml(r.chain)}</span></td>
              <td>${formatRoleBadge(r.role)}</td>
              <td class="mono">${formatDecimal(r.conservative)}</td>
              <td class="mono" style="font-weight:600; color:#1d4ed8;">${formatDecimal(r.proportional)}</td>
              <td class="mono">${formatDecimal(r.fifo)}</td>
              <td class="mono">${formatDecimal(r.lifo)}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  } catch (err) {
    container.innerHTML = `<div class="empty-state" style="color:#991b1b;">Failed to load attributions: ${escapeHtml(err.message)}</div>`;
  }
}

// ---------------------------------------------------------------------------
// Case Branch Audit Tab
// ---------------------------------------------------------------------------

async function loadCaseAudit(caseId) {
  const container = document.getElementById('case-audit-content');
  const countBadge = document.getElementById('audit-count-badge');
  container.innerHTML = '<div class="empty-state"><span class="loading"></span> Fetching branch decision audit records...</div>';
  try {
    const data = await API.getAudit(caseId);
    const records = data.audit_records || [];
    if (countBadge) countBadge.textContent = `${records.length} records`;

    if (!records.length) {
      container.innerHTML = '<div class="empty-state">No branch pruning decisions recorded for this case.</div>';
      return;
    }

    container.innerHTML = `
      <table class="audit-table">
        <thead>
          <tr>
            <th>Tier</th>
            <th>From Address</th>
            <th>To Address</th>
            <th>Amount</th>
            <th>Disposition</th>
            <th>Pruning Reason</th>
            <th>Timestamp</th>
          </tr>
        </thead>
        <tbody>
          ${records.map(r => `
            <tr class="audit-tier-${r.tier || 1}">
              <td><span class="status-badge" style="background:#f1f5f9; color:#334155; font-size:10px;">Tier ${r.tier || 1}</span></td>
              <td class="mono" style="font-size:11px;">${escapeHtml(r.from_address ? r.from_address.slice(0, 10) + '…' : '—')}</td>
              <td class="mono" style="font-size:11px; font-weight:600;">${escapeHtml(r.to_address ? r.to_address.slice(0, 10) + '…' : '—')}</td>
              <td class="mono">${formatDecimal(r.amount)} ${escapeHtml(r.asset || '')}</td>
              <td>${formatDispositionBadge(r.disposition)}</td>
              <td style="font-size:11px; color:#4b5563;">${escapeHtml(r.reason || '—')}</td>
              <td style="font-size:11px; color:#64748b;">${formatTime(r.recorded_at)}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  } catch (err) {
    container.innerHTML = `<div class="empty-state" style="color:#991b1b;">Failed to load audit log: ${escapeHtml(err.message)}</div>`;
  }
}

// ---------------------------------------------------------------------------
// Case Delta Tab
// ---------------------------------------------------------------------------

async function loadCaseDelta(caseId) {
  const container = document.getElementById('case-delta-content');
  container.innerHTML = '<div class="empty-state"><span class="loading"></span> Computing case delta...</div>';
  try {
    const data = await API.getDelta(caseId);
    container.innerHTML = `
      <div style="display:flex; flex-direction:column; gap:8px;">
        <div class="delta-row">
          <span class="delta-label">Review Timestamp</span>
          <span class="delta-value mono">${escapeHtml(data.review_timestamp)}</span>
        </div>
        <div class="delta-row">
          <span class="delta-label">New Transfers Observed</span>
          <span class="delta-value ${data.new_transfers > 0 ? 'positive' : ''}">${data.new_transfers}</span>
        </div>
        <div class="delta-row">
          <span class="delta-label">New Cross-Chain Bridge Events</span>
          <span class="delta-value ${data.new_bridge_events > 0 ? 'warning' : ''}">${data.new_bridge_events}</span>
        </div>
        <div class="delta-row">
          <span class="delta-label">New DEX Swaps</span>
          <span class="delta-value">${data.new_dex_events}</span>
        </div>
        <div class="delta-row">
          <span class="delta-label">Victim Value Moved</span>
          <span class="delta-value mono">${formatDecimal(data.victim_value_moved)}</span>
        </div>
        <div class="delta-row">
          <span class="delta-label">Primary VASP Change</span>
          <span class="delta-value ${data.primary_vasp_changed ? 'warning' : ''}">${data.primary_vasp_changed ? 'YES' : 'NO'}</span>
        </div>
        ${data.vasp_candidate_changes && data.vasp_candidate_changes.length ? `
          <div style="margin-top:8px; padding:10px; background:#fffbeb; border:1px solid #fde68a; border-radius:4px; font-size:12px; color:#92400e;">
            <b>VASP Changes:</b><br>${data.vasp_candidate_changes.map(c => `• ${escapeHtml(c)}`).join('<br>')}
          </div>
        ` : ''}
      </div>
    `;
  } catch (err) {
    container.innerHTML = `<div class="empty-state" style="color:#991b1b;">Failed to compute delta: ${escapeHtml(err.message)}</div>`;
  }
}

// ---------------------------------------------------------------------------
// Forensic Evidence Package Exports
// ---------------------------------------------------------------------------

async function exportEvidencePackage(format) {
  if (!currentCaseId) return;
  try {
    if (format === 'json') {
      const data = await API.getEvidencePackageJson(currentCaseId);
      const str = JSON.stringify(data, null, 2);
      downloadFile(`${currentCaseId}_evidence_package.json`, str, 'application/json');
    } else {
      const md = await API.getEvidencePackageMarkdown(currentCaseId);
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
// Pattern Analysis (Advisory AI)
// ---------------------------------------------------------------------------

async function openAiAnalysis() {
  if (!currentCaseId) return;
  const panel = document.getElementById('ai-panel');
  const content = document.getElementById('ai-content');
  panel.classList.remove('hidden');
  content.innerHTML = '<div style="padding:20px; text-align:center;"><span class="loading"></span> Extracting topological features and pattern signatures...</div>';

  try {
    const data = await API.getAiAnalysis(currentCaseId);
    const f = data.features || {};
    const patterns = data.patterns || [];
    const sim = data.case_similarity || {};

    content.innerHTML = `
      <div style="margin-bottom:16px;">
        <h4 style="font-size:13px; font-weight:600; color:#1a3a5c; margin-bottom:8px;">Observed Topological Graph Features</h4>
        <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap:8px; background:#f8fafc; padding:12px; border-radius:4px; border:1px solid #e2e8f0; font-size:12px;">
          <div><span style="color:#64748b;">Hop Count:</span> <b>${f.hop_count ?? 0}</b></div>
          <div><span style="color:#64748b;">Branching Factor:</span> <b>${formatDecimal(f.branching_factor, 2)}</b></div>
          <div><span style="color:#64748b;">Peeling Ratio:</span> <b>${formatDecimal(f.peeling_ratio, 2)}</b></div>
          <div><span style="color:#64748b;">Graph Entropy:</span> <b>${formatDecimal(f.entropy, 2)}</b></div>
          <div><span style="color:#64748b;">Bridge Count:</span> <b>${f.bridge_count ?? 0}</b></div>
          <div><span style="color:#64748b;">DEX Count:</span> <b>${f.dex_count ?? 0}</b></div>
        </div>
      </div>

      <div style="margin-bottom:16px;">
        <h4 style="font-size:13px; font-weight:600; color:#1a3a5c; margin-bottom:8px;">Suggested Pattern Classifications</h4>
        ${patterns.length ? patterns.map(p => `
          <div style="background:#f0fdf4; border:1px solid #bbf7d0; border-radius:4px; padding:10px 12px; margin-bottom:8px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <span style="font-weight:600; color:#166534;">${escapeHtml(p.pattern_name)}</span>
              <span class="status-badge" style="background:#dcfce7; color:#15803d; font-size:10px;">${escapeHtml(p.confidence)}</span>
            </div>
            <div style="font-size:12px; color:#334155; margin-top:4px;">${escapeHtml(p.investigative_advice)}</div>
          </div>
        `).join('') : '<div style="font-size:12px; color:#6b7280; padding:8px 0;">No complex laundering topologies triggered for this path.</div>'}
      </div>

      <div style="margin-bottom:16px;">
        <h4 style="font-size:13px; font-weight:600; color:#1a3a5c; margin-bottom:8px;">Similar Historical / Synthetic Case References</h4>
        ${sim.status === 'COMPUTED' && sim.matches && sim.matches.length ? sim.matches.map(m => `
          <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:4px; padding:10px 12px; margin-bottom:6px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <span style="font-weight:600; color:#1a3a5c;">${escapeHtml(m.scenario_name || m.case_id)}</span>
              <span style="font-size:12px; font-weight:600; color:#1d4ed8;">${(m.similarity_score * 100).toFixed(1)}% Match</span>
            </div>
            <div style="font-size:11px; color:#64748b; margin-top:2px;">Structural notes: ${escapeHtml(m.shared_structural_notes)}</div>
          </div>
        `).join('') : `<div style="font-size:12px; color:#6b7280; padding:8px 0;">${escapeHtml(sim.message || 'Insufficient historical cases for benchmark distance calculation.')}</div>`}
      </div>

      <div>
        <h4 style="font-size:13px; font-weight:600; color:#1a3a5c; margin-bottom:8px;">Investigator Briefing</h4>
        <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:4px; padding:12px; font-size:12px; line-height:1.5; color:#334155; white-space:pre-wrap;">${escapeHtml(data.investigator_narrative)}</div>
      </div>

      <div style="margin-top:14px; padding:8px 12px; background:#fffbeb; border:1px solid #fde68a; border-radius:4px; font-size:11px; color:#92400e;">
        <b>Forensic Notice:</b> Advisory analysis is generated locally from topological features. It does not alter or replace deterministic blockchain ledger evidence.
      </div>
    `;
  } catch (err) {
    content.innerHTML = `<div style="color:#991b1b; padding:12px;">Pattern analysis error: ${escapeHtml(err.message)}</div>`;
  }
}

function closeAiPanel() {
  document.getElementById('ai-panel').classList.add('hidden');
}

function closeInspector() {
  document.getElementById('evidence-inspector').classList.add('hidden');
}

// ---------------------------------------------------------------------------
// VASP Registry Lookup
// ---------------------------------------------------------------------------

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
    btn.innerHTML = '<span class="loading"></span> Looking up...';
  }

  try {
    const data = await API.lookupRegistry(chain, address);
    resBox.classList.remove('hidden');

    if (data.status === 'INSUFFICIENT_EVIDENCE' || !data.primary_claim) {
      resBox.innerHTML = `
        <div style="padding:12px 16px; background:#f9fafb; border:1px solid #e5e7eb; border-radius:4px;">
          <div style="font-weight:700; color:#4b5563; font-size:13px;">NO SUPPORTED ATTRIBUTION</div>
          <div style="font-size:12px; color:#6b7280; margin-top:4px;">Address <span class="mono">${escapeHtml(address)}</span> is not present in the verified intelligence repository. Identity cannot be fabricated.</div>
        </div>
      `;
      return;
    }

    const claim = data.primary_claim;
    const isStale = data.status === 'STALE';
    const isConflicted = data.status === 'CONFLICTED';

    resBox.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:12px;">
        <div>
          <h3 style="font-size:16px; font-weight:700; color:#1a3a5c;">${escapeHtml(claim.entity_name)}</h3>
          <div style="font-size:12px; color:#64748b; margin-top:2px;">Chain: ${escapeHtml(claim.chain)} · Address: <span class="mono">${escapeHtml(claim.address)}</span></div>
        </div>
        ${formatRoleBadge(data.entity_type || claim.entity_role)}
      </div>

      ${isStale ? `
        <div style="margin-bottom:12px; padding:8px 12px; background:#fef2f2; border:1px solid #fecaca; border-radius:4px; font-size:12px; color:#991b1b;">
          ⚠ <b>STALE RECORD:</b> Verified over 180 days ago (${escapeHtml(claim.last_verified)}). Attribution confidence degraded.
        </div>
      ` : ''}

      ${isConflicted ? `
        <div style="margin-bottom:12px; padding:8px 12px; background:#fffbeb; border:1px solid #fde68a; border-radius:4px; font-size:12px; color:#92400e;">
          ⚠ <b>DISPUTED / CONFLICTING INTELLIGENCE:</b> Multiple sources assert conflicting attributions for this address.
        </div>
      ` : ''}

      <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap:10px; background:#f8fafc; padding:12px; border-radius:4px; border:1px solid #e2e8f0; font-size:12px;">
        <div><span style="color:#64748b;">Source:</span><br><b>${escapeHtml(claim.source)}</b></div>
        <div><span style="color:#64748b;">Reliability:</span><br><b>${escapeHtml(claim.source_reliability || 'HIGH')}</b></div>
        <div><span style="color:#64748b;">Confidence:</span><br><b>${escapeHtml(claim.confidence)}</b></div>
        <div><span style="color:#64748b;">Last Verified:</span><br><b>${formatTime(claim.last_verified)}</b></div>
      </div>
    `;
  } catch (err) {
    resBox.classList.remove('hidden');
    resBox.innerHTML = `<div style="color:#991b1b; padding:12px;">Lookup error: ${escapeHtml(err.message)}</div>`;
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Look Up';
    }
  }
}

async function loadRegistryStats() {
  const container = document.getElementById('registry-stats');
  try {
    const stats = await API.getRegistryStats();
    container.innerHTML = `
      <div style="display:flex; gap:24px; font-size:12px; color:#4b5563;">
        <span>Total Verified Entries: <b>${stats.total_entries || 0}</b></span>
        <span>Unique Addresses: <b>${stats.unique_addresses || 0}</b></span>
        <span>Stale Entries (>180d): <b>${stats.stale_entries || 0}</b></span>
      </div>
    `;
  } catch (err) {
    container.innerHTML = `<span style="color:#991b1b;">Failed to fetch stats: ${escapeHtml(err.message)}</span>`;
  }
}

// ---------------------------------------------------------------------------
// Chain Health & Monitoring Daemon Info
// ---------------------------------------------------------------------------

async function loadChainsHealth() {
  const grid = document.getElementById('health-grid');
  const btn = document.getElementById('btn-refresh-health');

  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="loading"></span> Querying RPCs...';
  }

  try {
    const health = await API.getChainsHealth();
    const tron = health.tron || {};
    const eth = health.ethereum || {};

    grid.innerHTML = `
      <!-- TRON Provider Card -->
      <div class="health-card">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
          <div>
            <h3 style="font-size:16px; font-weight:700; color:#1a3a5c;">TRON Network Adapter</h3>
            <span style="font-size:11px; color:#64748b;">Protocol: TRC-20 (USDT / TRX)</span>
          </div>
          ${formatHealthBadge(tron.status)}
        </div>
        <table class="attribution-table" style="font-size:12px;">
          <tr><td>API Credential</td><td><b>${tron.api_key_configured ? 'Configured (TRONGRID_API_KEY)' : 'Not configured (Free Tier)'}</b></td></tr>
          <tr><td>Solidified Block</td><td class="mono">${tron.solidified_block ? tron.solidified_block.toLocaleString() : 'Unavailable'}</td></tr>
          <tr><td>Historical State</td><td><span style="color:#92400e;">Unavailable on Free Tier</span> (Archive Required)</td></tr>
          <tr><td>Last Checked</td><td>${formatTime(health.timestamp)}</td></tr>
        </table>
        ${tron.error_message ? `<div style="margin-top:10px; padding:8px 10px; background:#fef2f2; border:1px solid #fecaca; border-radius:4px; font-size:11px; color:#991b1b;">${escapeHtml(tron.error_message)}</div>` : ''}
      </div>

      <!-- Ethereum Provider Card -->
      <div class="health-card">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
          <div>
            <h3 style="font-size:16px; font-weight:700; color:#1a3a5c;">Ethereum Network Adapter</h3>
            <span style="font-size:11px; color:#64748b;">Protocol: ERC-20 (USDT / USDC / DAI / ETH)</span>
          </div>
          ${formatHealthBadge(eth.status)}
        </div>
        <table class="attribution-table" style="font-size:12px;">
          <tr><td>RPC Endpoint</td><td><b>${eth.rpc_configured ? 'Configured (ETH_RPC_URL)' : 'Default Public Gateway'}</b></td></tr>
          <tr><td>PoS Finalized Block</td><td class="mono">${eth.finalized_block ? eth.finalized_block.toLocaleString() : 'Unavailable'}</td></tr>
          <tr><td>Historical State Capability</td><td>${eth.archive_capability ? '<span style="color:#166534;">Archive Supported</span>' : '<span style="color:#92400e;">Full Node (Pruned History)</span>'}</td></tr>
          <tr><td>Last Checked</td><td>${formatTime(health.timestamp)}</td></tr>
        </table>
        ${eth.error_message ? `<div style="margin-top:10px; padding:8px 10px; background:#fef2f2; border:1px solid #fecaca; border-radius:4px; font-size:11px; color:#991b1b;">${escapeHtml(eth.error_message)}</div>` : ''}
      </div>
    `;
  } catch (err) {
    grid.innerHTML = `<div class="empty-state" style="grid-column:1 / -1; color:#991b1b;">Failed to query providers: ${escapeHtml(err.message)}</div>`;
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Refresh Health Checks';
    }
  }
}

async function loadMonitorInfo() {
  const container = document.getElementById('monitor-details-content');
  try {
    const data = await API.getMonitorStatus();
    const isRunning = data.running || false;
    container.innerHTML = `
      <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap:12px; margin-top:8px;">
        <div><span style="color:#64748b;">Daemon State:</span><br><b>${isRunning ? 'ACTIVE (Polling Enabled)' : 'IDLE / STANDBY'}</b></div>
        <div><span style="color:#64748b;">Active Watchers:</span><br><b>${data.active_watchers_count ?? 0} cases registered</b></div>
        <div><span style="color:#64748b;">Poll Interval:</span><br><b>${data.poll_interval_seconds ?? 30}s</b></div>
        <div><span style="color:#64748b;">Last Checkpoint Poll:</span><br><b>${data.last_poll_timestamp ? formatTime(data.last_poll_timestamp) : 'Pending first cycle'}</b></div>
      </div>
    `;
  } catch (err) {
    container.innerHTML = `<span style="color:#991b1b;">Failed to fetch monitor details: ${escapeHtml(err.message)}</span>`;
  }
}

async function updateMonitorBadge() {
  const badge = document.getElementById('monitor-badge');
  if (!badge) return;
  try {
    const data = await API.getMonitorStatus();
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

  errorBox.classList.add('hidden');

  // Validation
  if (!complaintRef) {
    showIntakeError('Please provide a Complaint Reference identifier (e.g. NCRP reference).');
    return;
  }
  if (!wallet) {
    showIntakeError('Please provide the reported suspect/destination wallet address.');
    return;
  }
  if (amount && (isNaN(parseFloat(amount)) || parseFloat(amount) <= 0)) {
    showIntakeError('Reported amount must be a positive numerical value.');
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
    btn.innerHTML = '<span class="loading"></span> Submitting & Tracing...';
  }

  try {
    const res = await API.createComplaint(payload);
    if (res.case_id) {
      openCase(res.case_id);
    } else {
      showSection('cases');
    }
  } catch (err) {
    showIntakeError(`Complaint submission rejected: ${err.message}`);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Submit & Initiate Deep Tracing';
    }
  }
}

function showIntakeError(msg) {
  const errorBox = document.getElementById('intake-error');
  errorBox.textContent = msg;
  errorBox.classList.remove('hidden');
}

// ---------------------------------------------------------------------------
// Human-Readable Enum Formatters & Utilities
// ---------------------------------------------------------------------------

function formatStateBadge(state) {
  const map = {
    'ACTIVE': { label: 'Active Tracing', cls: 'badge-supported' },
    'VASP_CANDIDATE': { label: 'Candidate VASP', cls: 'badge-ambiguous' },
    'SUPPORTED_VASP': { label: 'Supported VASP', cls: 'badge-verified' },
    'CUSTODIAL_BOUNDARY': { label: 'Custodial Boundary', cls: 'badge-custodial_boundary' },
    'FUNDS_STATIONARY': { label: 'Funds Stationary', cls: 'badge-unresolved' },
    'FAN_OUT': { label: 'Fan-Out Detected', cls: 'badge-ambiguous' },
    'CLOSED': { label: 'Closed', cls: 'badge-unresolved' },
  };
  const item = map[state] || { label: state || '—', cls: 'badge-unresolved' };
  return `<span class="status-badge ${item.cls}">${escapeHtml(item.label)}</span>`;
}

function formatTraceBadge(trace) {
  const map = {
    'DETERMINISTIC': { label: 'Deterministic', color: '#166534' },
    'SUPPORTED': { label: 'Supported', color: '#1d4ed8' },
    'DEGRADED': { label: 'Degraded', color: '#92400e' },
    'UNRESOLVED': { label: 'Unresolved', color: '#4b5563' },
    'OBFUSCATED': { label: 'Obfuscated', color: '#7c3aed' },
  };
  const item = map[trace] || { label: trace || '—', color: '#6b7280' };
  return `<span style="font-size:12px; font-weight:600; color:${item.color};">${escapeHtml(item.label)}</span>`;
}

function formatActionBadge(action) {
  const map = {
    'SUPPORTED_VASP': { label: 'Supported VASP', color: '#166534' },
    'VASP_CANDIDATE': { label: 'Candidate VASP', color: '#1d4ed8' },
    'NO_ACTIONABLE_ENDPOINT': { label: 'No actionable endpoint', color: '#6b7280' },
    'TRACEABILITY_LOST': { label: 'Traceability lost', color: '#991b1b' },
  };
  const item = map[action] || { label: action || 'None', color: '#6b7280' };
  return `<span style="font-size:12px; font-weight:500; color:${item.color};">${escapeHtml(item.label)}</span>`;
}

function formatRoleBadge(role) {
  const map = {
    'CUSTODIAL_VASP': { label: 'Custodial VASP', cls: 'badge-verified' },
    'deposit_infrastructure': { label: 'Deposit Infra', cls: 'badge-verified' },
    'vasp': { label: 'Custodial VASP', cls: 'badge-verified' },
    'DEX': { label: 'DEX Router', cls: 'badge-supported' },
    'dex': { label: 'DEX Router', cls: 'badge-supported' },
    'dex_router': { label: 'DEX Router', cls: 'badge-supported' },
    'MIXER': { label: 'Mixer Boundary', cls: 'badge-unstable' },
    'mixer': { label: 'Mixer Boundary', cls: 'badge-unstable' },
    'BRIDGE': { label: 'Bridge Contract', cls: 'badge-ambiguous' },
    'bridge_contract': { label: 'Bridge Contract', cls: 'badge-ambiguous' },
    'intermediary': { label: 'Intermediary', cls: 'badge-unresolved' },
    'suspect_wallet': { label: 'Suspect Wallet', cls: 'badge-stale' },
  };
  const item = map[role] || { label: role || 'Unknown', cls: 'badge-unresolved' };
  return `<span class="status-badge ${item.cls}">${escapeHtml(item.label)}</span>`;
}

function formatDispositionBadge(dispo) {
  const map = {
    'FULLY_TRACED': { label: 'Fully Traced', cls: 'badge-verified' },
    'DEPRIORITIZED_DUST': { label: 'Deprioritized Dust', cls: 'badge-unresolved' },
    'DEFERRED_BUDGET': { label: 'Deferred Mass', cls: 'badge-ambiguous' },
    'MIXER_BOUNDARY': { label: 'Mixer Boundary', cls: 'badge-unstable' },
    'VASP_BOUNDARY': { label: 'VASP Boundary', cls: 'badge-verified' },
    'BUDGET_EXHAUSTED': { label: 'Budget Exhausted', cls: 'badge-stale' },
  };
  const item = map[dispo] || { label: dispo || '—', cls: 'badge-unresolved' };
  return `<span class="status-badge ${item.cls}">${escapeHtml(item.label)}</span>`;
}

function formatHealthBadge(status) {
  if (status === 'OPERATIONAL' || status === 'CONFIGURED') {
    return '<span class="status-badge badge-verified">Configured</span>';
  }
  if (status === 'LIMITED' || status === 'PUBLIC_DEFAULT') {
    return '<span class="status-badge badge-ambiguous">Limited</span>';
  }
  return '<span class="status-badge badge-stale">Unavailable</span>';
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

// ---------------------------------------------------------------------------
// Investigator Action Packet & Alerts UI
// ---------------------------------------------------------------------------

async function loadCaseActionPacket(caseId) {
  const container = document.getElementById('action-packet-content');
  if (!container) return;
  try {
    container.innerHTML = '<div class="empty-state">Loading action packet...</div>';
    const pkg = await API.getEvidencePackageJson(caseId);
    const action = pkg.investigator_action_packet || {};

    const categoriesHtml = (action.suggested_record_categories || []).map(cat => `
      <li style="margin-bottom:6px; color:#374151; font-size:12px;">${escapeHtml(cat)}</li>
    `).join('');

    container.innerHTML = `
      <div style="display:grid; grid-template-columns: 1fr 1fr; gap:16px; margin-bottom:16px;">
        <div style="background:#f8fafc; padding:14px; border-radius:6px; border:1px solid #e2e8f0;">
          <div style="font-size:11px; font-weight:600; color:#64748b; text-transform:uppercase;">Primary Identified Endpoint</div>
          <div style="font-size:16px; font-weight:700; color:#1a3a5c; margin-top:4px;">
            ${escapeHtml(action.primary_supported_vasp || 'None identified')}
          </div>
          <div class="mono" style="font-size:12px; color:#475569; margin-top:4px; word-break:break-all;">
            ${escapeHtml(action.target_address || '—')}
          </div>
        </div>

        <div style="background:#f8fafc; padding:14px; border-radius:6px; border:1px solid #e2e8f0;">
          <div style="font-size:11px; font-weight:600; color:#64748b; text-transform:uppercase;">Actionability & Stability</div>
          <div style="display:flex; align-items:center; gap:8px; margin-top:6px;">
            <span class="status-badge ${action.endpoint_stability === 'HIGH' ? 'badge-verified' : 'badge-ambiguous'}">${escapeHtml(action.endpoint_stability || 'UNRESOLVED')} Stability</span>
            <span class="status-badge badge-active">${escapeHtml(action.actionability_state || 'NO_ACTIONABLE_ENDPOINT')}</span>
          </div>
          <div style="font-size:12px; color:#64748b; margin-top:6px;">
            Trace Completeness: <b>${escapeHtml(action.trace_completeness_pct || '100.00')}%</b>
          </div>
        </div>
      </div>

      <div style="background:#ffffff; border:1px solid #e5e7eb; border-radius:6px; padding:14px; margin-bottom:16px;">
        <h4 style="font-size:13px; font-weight:600; color:#1f2937; margin-bottom:8px;">Suggested Record Categories for Lawful Inquiry</h4>
        <ul style="padding-left:20px; margin-bottom:12px;">
          ${categoriesHtml}
        </ul>
      </div>

      <div style="padding:12px; background:#fffbeb; border:1px solid #fde68a; border-radius:6px; font-size:12px; color:#92400e; line-height:1.4;">
        <strong>Advisory & Legal Notice:</strong> ${escapeHtml(action.advisory_notice || 'Authorized human and legal review required.')}
      </div>

      <div style="margin-top:14px; display:flex; justify-content:flex-end; gap:8px;">
        <button class="btn-primary" style="font-size:12px;" onclick="downloadEvidenceMarkdown('${escapeHtml(caseId)}')">Download Evidence Package (.md)</button>
      </div>
    `;
  } catch (err) {
    container.innerHTML = `<div class="empty-state" style="color:#991b1b;">Failed to load action packet: ${escapeHtml(err.message)}</div>`;
  }
}

async function loadAlerts() {
  const container = document.getElementById('alerts-list-container');
  if (!container) return;
  try {
    const data = await API.getAlerts();
    const alerts = data.alerts || [];

    // Update badge
    const unackCount = alerts.filter(a => !a.acknowledged).length;
    const badge = document.getElementById('alerts-unread-badge');
    if (badge) {
      badge.textContent = unackCount;
      badge.classList.toggle('hidden', unackCount === 0);
    }

    if (!alerts.length) {
      container.innerHTML = '<div class="empty-state">No active investigation alerts. Continuous monitoring is running.</div>';
      return;
    }

    container.innerHTML = `
      <div style="display:flex; flex-direction:column; gap:12px;">
        ${alerts.map(a => `
          <div style="background:#ffffff; border:1px solid ${a.acknowledged ? '#e5e7eb' : (a.severity === 'WARNING' ? '#fde68a' : '#bfdbfe')}; border-left:4px solid ${a.acknowledged ? '#9ca3af' : (a.severity === 'WARNING' ? '#d97706' : '#2563eb')}; border-radius:6px; padding:14px; display:flex; justify-content:space-between; align-items:flex-start;">
            <div>
              <div style="display:flex; align-items:center; gap:8px; margin-bottom:4px;">
                <span class="status-badge ${a.severity === 'WARNING' ? 'badge-ambiguous' : 'badge-verified'}" style="font-size:10px;">${escapeHtml(a.event_type)}</span>
                <span class="status-badge" style="background:#f3f4f6; color:#4b5563; font-size:10px;">Case: <b class="mono" style="cursor:pointer;" onclick="openCase('${escapeHtml(a.case_id)}')">${escapeHtml(a.case_id)}</b></span>
                <span style="font-size:11px; color:#6b7280;">${formatTime(a.created_at)}</span>
              </div>
              <div style="font-size:13px; font-weight:600; color:#1f2937; margin-top:2px;">${escapeHtml(a.summary)}</div>
              ${a.evidence_reference ? `<div class="mono" style="font-size:11px; color:#64748b; margin-top:4px;">Evidence Ref: ${escapeHtml(a.evidence_reference)}</div>` : ''}
            </div>
            <div>
              ${!a.acknowledged ? `
                <button class="btn-ghost-sm" style="font-size:11px;" onclick="ackAlert('${escapeHtml(a.alert_id)}')">Acknowledge</button>
              ` : `
                <span style="font-size:11px; color:#9ca3af;">✓ Acknowledged</span>
              `}
            </div>
          </div>
        `).join('')}
      </div>
    `;
  } catch (err) {
    container.innerHTML = `<div class="empty-state" style="color:#991b1b;">Failed to load alerts: ${escapeHtml(err.message)}</div>`;
  }
}

async function ackAlert(alertId) {
  try {
    await API.acknowledgeAlert(alertId);
    loadAlerts();
  } catch (err) {
    alert(`Failed to acknowledge alert: ${err.message}`);
  }
}

// ---------------------------------------------------------------------------
// Page Initialization
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
  showSection('cases');
  updateMonitorBadge();
  loadAlerts();
  if (monitorInterval) clearInterval(monitorInterval);
  monitorInterval = setInterval(() => {
    updateMonitorBadge();
    loadAlerts();
  }, 15000);
});
