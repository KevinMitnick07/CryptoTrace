/* graph.js — Cytoscape.js fund-flow graph workspace.
   Node roles drive shape and color — not decoration.
   Edge annotations carry evidence class and value.
*/

let cy = null;

const NODE_STYLES = {
  victim_anchor:      { bg: '#1a3a5c', shape: 'star',     size: 36 },
  suspect_wallet:     { bg: '#dc2626', shape: 'ellipse',  size: 28 },
  deposit_infrastructure: { bg: '#166534', shape: 'rectangle', size: 32 },
  vasp:               { bg: '#166534', shape: 'rectangle', size: 32 },
  mixer:              { bg: '#7c3aed', shape: 'octagon',  size: 28 },
  dex_router:         { bg: '#0891b2', shape: 'diamond',  size: 28 },
  bridge_contract:    { bg: '#d97706', shape: 'hexagon',  size: 28 },
  intermediary:       { bg: '#64748b', shape: 'ellipse',  size: 22 },
  unknown:            { bg: '#94a3b8', shape: 'ellipse',  size: 20 },
};

function getNodeStyle(role) {
  return NODE_STYLES[role] || NODE_STYLES['unknown'];
}

function initGraph(containerId) {
  cy = cytoscape({
    container: document.getElementById(containerId),
    style: [
      {
        selector: 'node',
        style: {
          'width': 'data(size)',
          'height': 'data(size)',
          'shape': 'data(shape)',
          'background-color': 'data(bg)',
          'label': 'data(displayLabel)',
          'color': '#111318',
          'font-size': '10px',
          'font-family': 'Inter, system-ui, sans-serif',
          'text-valign': 'bottom',
          'text-margin-y': '6px',
          'text-outline-width': 0,
          'border-width': 1.5,
          'border-color': 'rgba(0,0,0,0.12)',
          'overlay-padding': '4px',
        },
      },
      {
        selector: 'node:selected',
        style: {
          'border-color': '#1d4ed8',
          'border-width': 2.5,
        },
      },
      {
        selector: 'edge',
        style: {
          'width': 1.5,
          'line-color': '#cbd5e1',
          'target-arrow-color': '#94a3b8',
          'target-arrow-shape': 'triangle',
          'curve-style': 'bezier',
          'label': 'data(edgeLabel)',
          'font-size': '9px',
          'color': '#64748b',
          'font-family': 'IBM Plex Mono, monospace',
          'text-background-color': '#ffffff',
          'text-background-opacity': 0.85,
          'text-background-padding': '2px',
          'edge-text-rotation': 'autorotate',
          'overlay-padding': '4px',
        },
      },
      {
        selector: 'edge:selected',
        style: {
          'line-color': '#1d4ed8',
          'target-arrow-color': '#1d4ed8',
          'width': 2,
        },
      },
      {
        selector: '.vasp-boundary',
        style: {
          'border-width': 2.5,
          'border-color': '#166534',
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
    layout: { name: 'breadthfirst', directed: true, padding: 20, spacingFactor: 1.3 },
    minZoom: 0.2,
    maxZoom: 4,
    wheelSensitivity: 0.3,
  });

  cy.on('tap', 'node', (evt) => {
    const data = evt.target.data();
    showNodeInspector(data);
  });

  cy.on('tap', 'edge', (evt) => {
    const data = evt.target.data();
    showEdgeInspector(data);
  });

  cy.on('tap', (evt) => {
    if (evt.target === cy) closeInspector();
  });
}

function renderGraph(graphData) {
  if (!cy) return;
  cy.elements().remove();

  const elements = [];

  for (const node of (graphData.nodes || [])) {
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

  for (const edge of (graphData.edges || [])) {
    const amtNum = parseFloat(edge.amount || '0');
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
  cy.layout({ name: 'breadthfirst', directed: true, padding: 24, spacingFactor: 1.4 }).run();
  cy.fit(undefined, 24);
}

function formatAmount(n) {
  if (n >= 1000000) return (n / 1000000).toFixed(2) + 'M';
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
  return n.toFixed(2);
}

function assetShort(asset) {
  const map = {
    'USDT_TRC20': 'USDT', 'USDT_ERC20': 'USDT', 'USDC_ERC20': 'USDC',
    'ETH': 'ETH', 'BTC': 'BTC', 'TRX': 'TRX',
  };
  return map[asset] || asset || '';
}

function showNodeInspector(data) {
  const panel = document.getElementById('evidence-inspector');
  const content = document.getElementById('inspector-content');
  panel.classList.remove('hidden');

  const attributed = data.victim_attributed
    ? `<div class="registry-field"><span class="label">Victim-attributed (approx):</span> <span class="mono">${parseFloat(data.victim_attributed).toFixed(4)}</span></div>`
    : '';

  content.innerHTML = `
    <div class="registry-field"><span class="label">Role:</span> ${data.role}</div>
    <div class="registry-field"><span class="label">Chain:</span> ${data.chain}</div>
    <div class="registry-field"><span class="label">Address:</span> <span class="mono">${data.address || '—'}</span></div>
    ${data.fullLabel ? `<div class="registry-field"><span class="label">Entity:</span> <b>${data.fullLabel}</b></div>` : ''}
    ${attributed}
    ${data.role === 'vasp' || data.role === 'deposit_infrastructure' ? `
      <div style="margin-top:10px;padding:8px 10px;background:#f0fdf4;border:1px solid #bbf7d0;border-radius:4px;font-size:12px;color:#166534;">
        CUSTODIAL BOUNDARY — On-chain tracing stops here. Further evidence requires authorized VASP records.
      </div>` : ''}
    ${data.role === 'mixer' ? `
      <div style="margin-top:10px;padding:8px 10px;background:#faf5ff;border:1px solid #ddd6fe;border-radius:4px;font-size:12px;color:#7c3aed;">
        MIXER BOUNDARY — Traceability: OBFUSCATED. Deterministic downstream attribution unavailable.
      </div>` : ''}
  `;
}

function showEdgeInspector(data) {
  const panel = document.getElementById('evidence-inspector');
  const content = document.getElementById('inspector-content');
  panel.classList.remove('hidden');

  content.innerHTML = `
    <div class="registry-field"><span class="label">Chain:</span> ${data.chain}</div>
    <div class="registry-field"><span class="label">Asset:</span> ${assetShort(data.asset)}</div>
    <div class="registry-field"><span class="label">Amount:</span> <span class="mono">${parseFloat(data.amount || 0).toFixed(6)}</span></div>
    ${data.victim_attributed ? `<div class="registry-field"><span class="label">Victim-attributed (proportional):</span> <span class="mono">${parseFloat(data.victim_attributed).toFixed(4)}</span></div>` : ''}
    ${data.tx_hash ? `<div class="registry-field"><span class="label">Transaction:</span> <span class="mono" style="word-break:break-all;font-size:11px;">${data.tx_hash}</span></div>` : ''}
    ${data.timestamp ? `<div class="registry-field"><span class="label">Timestamp:</span> ${new Date(data.timestamp).toLocaleString()}</div>` : ''}
    <div class="registry-field"><span class="label">Evidence class:</span> ${data.evidence_class || 'OBSERVED'}</div>
  `;
}

function closeInspector() {
  document.getElementById('evidence-inspector').classList.add('hidden');
}
