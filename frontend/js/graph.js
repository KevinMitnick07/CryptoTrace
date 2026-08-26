/* ============================================================
   CryptoTrace — Cytoscape.js Fund Flow Graph Engine
   Node roles drive shape, border, and color — forensic semantics.
   Includes Graph Dimming Mode, Focus Path from Anchor, and Dust Filtering.
   ============================================================ */

let cy = null;
let currentRawGraphData = null;
let isDustHidden = false;
let selectedNodeId = null;

const NODE_STYLES = {
  victim_anchor:          { bg: '#0f233a', shape: 'star',      size: 38 },
  suspect_wallet:         { bg: '#dc2626', shape: 'ellipse',   size: 30 },
  deposit_infrastructure: { bg: '#15803d', shape: 'rectangle', size: 34 },
  vasp:                   { bg: '#15803d', shape: 'rectangle', size: 34 },
  mixer:                  { bg: '#7c3aed', shape: 'octagon',   size: 30 },
  dex_router:             { bg: '#0891b2', shape: 'diamond',   size: 30 },
  bridge_contract:        { bg: '#d97706', shape: 'hexagon',   size: 30 },
  intermediary:           { bg: '#64748b', shape: 'ellipse',   size: 24 },
  unknown:                { bg: '#94a3b8', shape: 'ellipse',   size: 22 },
};

function getNodeStyle(role) {
  return NODE_STYLES[role] || NODE_STYLES['unknown'];
}

function initGraph(containerId) {
  const container = document.getElementById(containerId);
  if (!container) return;

  cy = cytoscape({
    container: container,
    style: [
      {
        selector: 'node',
        style: {
          'width': 'data(size)',
          'height': 'data(size)',
          'shape': 'data(shape)',
          'background-color': 'data(bg)',
          'label': 'data(displayLabel)',
          'color': '#0f172a',
          'font-size': '10px',
          'font-weight': 600,
          'font-family': 'Inter, system-ui, sans-serif',
          'text-valign': 'bottom',
          'text-margin-y': '6px',
          'text-outline-width': 0,
          'border-width': 1.5,
          'border-color': 'rgba(15, 23, 42, 0.2)',
          'overlay-padding': '4px',
          'transition-property': 'opacity, border-color, border-width',
          'transition-duration': '0.15s',
        },
      },
      {
        selector: 'node:selected',
        style: {
          'border-color': '#1d4ed8',
          'border-width': 3,
          'shadow-blur': 6,
          'shadow-color': '#93c5fd',
          'shadow-opacity': 0.8,
        },
      },
      {
        selector: 'edge',
        style: {
          'width': 1.6,
          'line-color': '#94a3b8',
          'target-arrow-color': '#64748b',
          'target-arrow-shape': 'triangle',
          'curve-style': 'bezier',
          'label': 'data(edgeLabel)',
          'font-size': '9px',
          'font-weight': 500,
          'color': '#334155',
          'font-family': 'IBM Plex Mono, monospace',
          'text-background-color': '#ffffff',
          'text-background-opacity': 0.92,
          'text-background-padding': '2px',
          'text-border-width': 1,
          'text-border-color': '#e2e8f0',
          'edge-text-rotation': 'autorotate',
          'overlay-padding': '4px',
          'transition-property': 'opacity, line-color, width',
          'transition-duration': '0.15s',
        },
      },
      {
        selector: 'edge:selected',
        style: {
          'line-color': '#1d4ed8',
          'target-arrow-color': '#1d4ed8',
          'width': 2.5,
        },
      },
      {
        selector: '.dimmed',
        style: {
          'opacity': 0.18,
        },
      },
      {
        selector: '.path-highlighted',
        style: {
          'opacity': 1.0,
          'line-color': '#1d4ed8',
          'target-arrow-color': '#1d4ed8',
          'width': 2.8,
          'border-color': '#1d4ed8',
          'border-width': 3,
        },
      },
      {
        selector: '.vasp-boundary',
        style: {
          'border-width': 2.5,
          'border-color': '#15803d',
          'border-style': 'solid',
        },
      },
      {
        selector: '.mixer-boundary',
        style: {
          'border-width': 2.5,
          'border-color': '#7c3aed',
          'border-style': 'dashed',
        },
      },
    ],
    layout: { name: 'breadthfirst', directed: true, padding: 24, spacingFactor: 1.4 },
    minZoom: 0.2,
    maxZoom: 4,
    wheelSensitivity: 0.3,
  });

  cy.on('tap', 'node', (evt) => {
    const node = evt.target;
    selectedNodeId = node.id();
    applyNodeDimming(node);
    showNodeInspector(node.data());
  });

  cy.on('tap', 'edge', (evt) => {
    const edge = evt.target;
    showEdgeInspector(edge.data());
  });

  cy.on('tap', (evt) => {
    if (evt.target === cy) {
      resetGraphDimming();
      closeInspector();
    }
  });
}

function renderGraph(graphData) {
  if (!cy) initGraph('cy');
  if (!cy) return;

  currentRawGraphData = graphData;
  cy.elements().remove();

  const nodes = graphData.nodes || [];
  const edges = graphData.edges || [];

  // Determine max edge amount for dust calculation
  let maxAmount = 0;
  for (const e of edges) {
    const a = parseFloat(e.amount || 0);
    if (a > maxAmount) maxAmount = a;
  }
  const dustThreshold = maxAmount * 0.005; // 0.5% dust threshold

  const elements = [];

  for (const node of nodes) {
    const style = getNodeStyle(node.role);
    const labelParts = [];
    if (node.label) labelParts.push(node.label);
    else if (node.address) labelParts.push(node.address.slice(0, 8) + '…');

    elements.push({
      data: {
        id: node.id,
        displayLabel: labelParts.join('\n'),
        fullLabel: node.label || '',
        address: node.address || '',
        chain: node.chain || '',
        role: node.role || 'unknown',
        bg: style.bg,
        shape: style.shape,
        size: style.size,
      },
      classes: node.role === 'vasp' || node.role === 'deposit_infrastructure' ? 'vasp-boundary' :
               node.role === 'mixer' ? 'mixer-boundary' : '',
    });
  }

  for (const edge of edges) {
    const amtNum = parseFloat(edge.amount || '0');
    if (isDustHidden && amtNum < dustThreshold) {
      continue;
    }

    const edgeLabel = amtNum > 0 ? formatAmount(amtNum) + ' ' + assetShort(edge.asset) : '';
    elements.push({
      data: {
        id: edge.id,
        source: edge.from,
        target: edge.to,
        chain: edge.chain,
        asset: edge.asset,
        amount: edge.amount,
        tx_hash: edge.tx_hash,
        evidence_class: edge.evidence_class,
        victim_attributed: edge.victim_attributed_approx,
        timestamp: edge.timestamp,
        edgeLabel: edgeLabel,
      },
    });
  }

  cy.add(elements);
  reRunGraphLayout('breadthfirst');
}

function reRunGraphLayout(layoutName) {
  if (!cy) return;
  let layoutOptions = { padding: 24 };

  if (layoutName === 'breadthfirst') {
    layoutOptions = { ...layoutOptions, name: 'breadthfirst', directed: true, spacingFactor: 1.4 };
  } else if (layoutName === 'concentric') {
    layoutOptions = { ...layoutOptions, name: 'concentric', minNodeSpacing: 40 };
  } else if (layoutName === 'cose') {
    layoutOptions = { ...layoutOptions, name: 'cose', animate: false, nodeRepulsion: 4000 };
  } else {
    layoutOptions = { ...layoutOptions, name: 'breadthfirst', directed: true };
  }

  cy.layout(layoutOptions).run();
  cy.fit(undefined, 24);
}

function toggleDustFilter(hideDust) {
  isDustHidden = hideDust;
  if (currentRawGraphData) {
    renderGraph(currentRawGraphData);
  }
}

function applyNodeDimming(node) {
  if (!cy) return;
  cy.elements().removeClass('dimmed path-highlighted');

  const neighborhood = node.neighborhood().add(node);
  cy.elements().difference(neighborhood).addClass('dimmed');
  node.addClass('path-highlighted');
}

function focusPathToNode(targetId) {
  if (!cy) return;
  cy.elements().removeClass('dimmed path-highlighted');

  // Find root/victim node
  const roots = cy.nodes().filter(n => n.indegree() === 0 || n.data('role') === 'victim_anchor' || n.data('role') === 'suspect_wallet');
  const target = cy.getElementById(targetId);

  if (!roots.length || !target.length) return;

  const root = roots[0];
  const aStar = cy.elements().aStar({ root: root, goal: target, directed: true });

  if (aStar.found) {
    cy.elements().difference(aStar.path).addClass('dimmed');
    aStar.path.addClass('path-highlighted');
  } else {
    applyNodeDimming(target);
  }
}

function resetGraphDimming() {
  if (!cy) return;
  cy.elements().removeClass('dimmed path-highlighted');
  selectedNodeId = null;
}

function formatAmount(n) {
  if (n >= 1000000) return (n / 1000000).toFixed(2) + 'M';
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
  return n.toFixed(2);
}

function assetShort(asset) {
  const map = {
    'USDT_TRC20': 'USDT', 'USDT_ERC20': 'USDT', 'USDC_ERC20': 'USDC',
    'ETH': 'ETH', 'BTC': 'BTC', 'TRX': 'TRX', 'DAI_ERC20': 'DAI',
  };
  return map[asset] || asset || '';
}

function showNodeInspector(data) {
  const panel = document.getElementById('evidence-inspector');
  const content = document.getElementById('inspector-content');
  const filterBtn = document.getElementById('btn-filter-inspector-timeline');
  const focusBtn = document.getElementById('btn-focus-path');
  if (!panel || !content) return;
  panel.classList.remove('hidden');

  if (filterBtn && data.address) {
    filterBtn.onclick = () => {
      if (window.filterTimelineByAddress) {
        window.filterTimelineByAddress(data.address);
      }
    };
  }

  if (focusBtn && data.id) {
    focusBtn.onclick = () => {
      focusPathToNode(data.id);
    };
  }

  content.innerHTML = `
    <!-- SECTION 1: IDENTITY -->
    <div style="margin-bottom:8px;">
      <div style="font-size:10px; font-weight:700; color:var(--text-muted); text-transform:uppercase; margin-bottom:4px;">1. Entity & Address Identity</div>
      <div style="display:grid; grid-template-columns: 1fr 1fr; gap:6px; background:var(--surface-alt); padding:6px 8px; border-radius:4px; border:1px solid var(--border-soft); font-size:11.5px;">
        <div><span style="color:var(--text-muted); font-size:10px; text-transform:uppercase;">Role:</span><br><b>${escapeHtml(data.role)}</b></div>
        <div><span style="color:var(--text-muted); font-size:10px; text-transform:uppercase;">Network:</span><br><b>${escapeHtml(data.chain || '—')}</b></div>
      </div>
      <div style="margin-top:6px;">
        <span style="color:var(--text-muted); font-size:10px; text-transform:uppercase; font-weight:600;">Address:</span><br>
        <span class="mono" style="font-size:11px; word-break:break-all;">${escapeHtml(data.address || '—')}</span>
        <button class="btn-copy" onclick="copyText('${escapeHtml(data.address)}', this)">Copy</button>
      </div>
      ${data.fullLabel ? `
        <div style="margin-top:4px;">
          <span style="color:var(--text-muted); font-size:10px; text-transform:uppercase; font-weight:600;">Entity Label:</span><br>
          <b style="color:var(--navy); font-size:12px;">${escapeHtml(data.fullLabel)}</b>
        </div>
      ` : ''}
    </div>

    <!-- SECTION 2: ATTRIBUTION BOUNDARY -->
    ${data.role === 'vasp' || data.role === 'deposit_infrastructure' ? `
      <div style="margin-top:8px; padding:6px 8px; background:var(--green-bg); border:1px solid var(--green-border); border-radius:4px; font-size:11px; color:var(--green);">
        <b>CUSTODIAL BOUNDARY:</b> On-chain graph tracing stops at this deposit cluster. Lawful production of internal ledger records required.
      </div>
    ` : ''}
    ${data.role === 'mixer' ? `
      <div style="margin-top:8px; padding:6px 8px; background:var(--purple-bg); border:1px solid var(--purple-border); border-radius:4px; font-size:11px; color:var(--purple);">
        <b>MIXER BOUNDARY:</b> Traceability state is OBFUSCATED. Deterministic downstream attribution is unavailable.
      </div>
    ` : ''}
  `;
}

function showEdgeInspector(data) {
  const panel = document.getElementById('evidence-inspector');
  const content = document.getElementById('inspector-content');
  const filterBtn = document.getElementById('btn-filter-inspector-timeline');
  const focusBtn = document.getElementById('btn-focus-path');
  if (!panel || !content) return;
  panel.classList.remove('hidden');

  if (filterBtn) {
    filterBtn.onclick = () => {
      if (window.filterTimelineByAddress && data.source) {
        window.filterTimelineByAddress(data.source);
      }
    };
  }

  if (focusBtn && data.target) {
    focusBtn.onclick = () => {
      focusPathToNode(data.target);
    };
  }

  content.innerHTML = `
    <div style="font-size:10px; font-weight:700; color:var(--text-muted); text-transform:uppercase; margin-bottom:4px;">Observed Transfer Hop</div>
    <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(100px, 1fr)); gap:6px; background:var(--surface-alt); padding:6px 8px; border-radius:4px; border:1px solid var(--border-soft); font-size:11.5px;">
      <div><span style="color:var(--text-muted); font-size:10px; text-transform:uppercase;">Network:</span><br><b>${escapeHtml(data.chain || '—')}</b></div>
      <div><span style="color:var(--text-muted); font-size:10px; text-transform:uppercase;">Asset:</span><br><b>${assetShort(data.asset)}</b></div>
      <div><span style="color:var(--text-muted); font-size:10px; text-transform:uppercase;">Amount:</span><br><b class="mono">${parseFloat(data.amount || 0).toFixed(4)}</b></div>
      <div><span style="color:var(--text-muted); font-size:10px; text-transform:uppercase;">Evidence:</span><br><span class="status-badge badge-verified" style="font-size:9.5px;">${escapeHtml(data.evidence_class || 'OBSERVED')}</span></div>
    </div>
    ${data.tx_hash ? `
      <div style="margin-top:6px;">
        <span style="color:var(--text-muted); font-size:10px; text-transform:uppercase; font-weight:600;">Transaction Hash:</span><br>
        <span class="mono" style="font-size:11px; word-break:break-all;">${escapeHtml(data.tx_hash)}</span>
        <button class="btn-copy" onclick="copyText('${escapeHtml(data.tx_hash)}', this)">Copy</button>
      </div>
    ` : ''}
    ${data.timestamp ? `
      <div style="margin-top:6px; font-size:10.5px; color:var(--text-muted);">
        Timestamp: ${new Date(data.timestamp).toUTCString()}
      </div>
    ` : ''}
  `;
}

function closeInspector() {
  const panel = document.getElementById('evidence-inspector');
  if (panel) panel.classList.add('hidden');
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

window.initGraph = initGraph;
window.renderGraph = renderGraph;
window.reRunGraphLayout = reRunGraphLayout;
window.toggleDustFilter = toggleDustFilter;
window.applyNodeDimming = applyNodeDimming;
window.focusPathToNode = focusPathToNode;
window.resetGraphDimming = resetGraphDimming;
window.closeInspector = closeInspector;
window.cy = cy;
