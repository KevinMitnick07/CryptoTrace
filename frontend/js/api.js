/**
 * CryptoTrace Frontend API Client.
 * Connects UI directly to real backend endpoints.
 */

const API = {
  async getCases() {
    const res = await fetch('/api/cases');
    if (!res.ok) throw new Error(`HTTP ${res.status}: Failed to fetch cases`);
    return res.json();
  },

  async getCase(caseId) {
    const res = await fetch(`/api/cases/${encodeURIComponent(caseId)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}: Failed to fetch case ${caseId}`);
    return res.json();
  },

  async getGraph(caseId) {
    const res = await fetch(`/api/cases/${encodeURIComponent(caseId)}/graph`);
    if (!res.ok) throw new Error(`HTTP ${res.status}: Failed to fetch graph for ${caseId}`);
    return res.json();
  },

  async getAudit(caseId) {
    const res = await fetch(`/api/cases/${encodeURIComponent(caseId)}/audit`);
    if (!res.ok) throw new Error(`HTTP ${res.status}: Failed to fetch audit log for ${caseId}`);
    return res.json();
  },

  async getDelta(caseId) {
    const res = await fetch(`/api/cases/${encodeURIComponent(caseId)}/delta`);
    if (!res.ok) throw new Error(`HTTP ${res.status}: Failed to fetch delta for ${caseId}`);
    return res.json();
  },

  async getAttributions(caseId) {
    const res = await fetch(`/api/cases/${encodeURIComponent(caseId)}/attributions`);
    if (!res.ok) throw new Error(`HTTP ${res.status}: Failed to fetch model attributions for ${caseId}`);
    return res.json();
  },

  async createComplaint(data) {
    const res = await fetch('/api/intake', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
      throw new Error(err.detail || `Intake failed with status ${res.status}`);
    }
    return res.json();
  },

  async lookupRegistry(chain, address) {
    const res = await fetch(`/api/registry/lookup?chain=${encodeURIComponent(chain)}&address=${encodeURIComponent(address)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}: Lookup failed`);
    return res.json();
  },

  async getRegistryStats() {
    const res = await fetch('/api/registry/stats');
    if (!res.ok) throw new Error(`HTTP ${res.status}: Failed to fetch registry stats`);
    return res.json();
  },

  async getScenarios() {
    const res = await fetch('/api/scenarios');
    if (!res.ok) throw new Error(`HTTP ${res.status}: Failed to fetch benchmark scenarios`);
    return res.json();
  },

  async runScenario(scenarioId) {
    const res = await fetch(`/api/scenarios/${encodeURIComponent(scenarioId)}/run`, {
      method: 'POST',
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
      throw new Error(err.detail || `Failed to execute scenario ${scenarioId}`);
    }
    return res.json();
  },

  async getAiAnalysis(caseId) {
    const res = await fetch(`/api/cases/${encodeURIComponent(caseId)}/ai/analysis`, {
      method: 'POST',
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
      throw new Error(err.detail || `Pattern analysis failed for ${caseId}`);
    }
    return res.json();
  },

  async getEvidencePackageJson(caseId) {
    const res = await fetch(`/api/cases/${encodeURIComponent(caseId)}/evidence-package/json`);
    if (!res.ok) throw new Error(`HTTP ${res.status}: Failed to download evidence package`);
    return res.json();
  },

  async getEvidencePackageMarkdown(caseId) {
    const res = await fetch(`/api/cases/${encodeURIComponent(caseId)}/evidence-package/markdown`);
    if (!res.ok) throw new Error(`HTTP ${res.status}: Failed to download markdown report`);
    return res.text();
  },

  async getMonitorStatus() {
    const res = await fetch('/api/monitor/status');
    if (!res.ok) throw new Error(`HTTP ${res.status}: Failed to fetch monitor status`);
    return res.json();
  },

  async getChainsHealth() {
    const res = await fetch('/api/chains/health');
    if (!res.ok) throw new Error(`HTTP ${res.status}: Failed to fetch chains health`);
    return res.json();
  },
};
