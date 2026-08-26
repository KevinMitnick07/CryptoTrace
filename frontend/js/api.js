/**
 * CryptoTrace — Forensic API Client.
 * Connects UI directly to real backend endpoints.
 * Explicitly exposed on window.API for robust cross-script accessibility.
 */

window.API = {
  async _fetchJson(url, options = {}) {
    try {
      const res = await fetch(url, options);
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        const msg = errBody.detail || errBody.message || `Request failed with status ${res.status}`;
        throw new Error(msg);
      }
      return await res.json();
    } catch (err) {
      console.warn(`API Error [${url}]:`, err.message);
      throw err;
    }
  },

  async _fetchText(url, options = {}) {
    try {
      const res = await fetch(url, options);
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: Failed to fetch text from ${url}`);
      }
      return await res.text();
    } catch (err) {
      console.warn(`API Text Error [${url}]:`, err.message);
      throw err;
    }
  },

  // Cases Queue & Details
  async getCases() {
    return this._fetchJson('/api/cases');
  },

  async getCase(caseId) {
    return this._fetchJson(`/api/cases/${encodeURIComponent(caseId)}`);
  },

  async getGraph(caseId) {
    return this._fetchJson(`/api/cases/${encodeURIComponent(caseId)}/graph`);
  },

  async getAudit(caseId) {
    return this._fetchJson(`/api/cases/${encodeURIComponent(caseId)}/audit`);
  },

  async getDelta(caseId) {
    return this._fetchJson(`/api/cases/${encodeURIComponent(caseId)}/delta`);
  },

  async getAttributions(caseId) {
    return this._fetchJson(`/api/cases/${encodeURIComponent(caseId)}/attributions`);
  },

  async getCaseClustering(caseId) {
    return this._fetchJson(`/api/cases/${encodeURIComponent(caseId)}/clustering`);
  },

  async getCaseIntermediary(caseId) {
    return this._fetchJson(`/api/cases/${encodeURIComponent(caseId)}/intermediary`);
  },

  // Complaint Intake
  async createComplaint(data) {
    return this._fetchJson('/api/intake', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  },

  // VASP Intelligence Repository
  async lookupRegistry(chain, address) {
    return this._fetchJson(`/api/registry/lookup?chain=${encodeURIComponent(chain)}&address=${encodeURIComponent(address)}`);
  },

  async getRegistryStats() {
    return this._fetchJson('/api/registry/stats');
  },

  async getRegistryEntries() {
    return this._fetchJson('/api/registry/entries');
  },

  // Synthetic Benchmarks
  async getScenarios() {
    return this._fetchJson('/api/scenarios');
  },

  async runScenario(scenarioId) {
    return this._fetchJson(`/api/scenarios/${encodeURIComponent(scenarioId)}/run`, {
      method: 'POST',
    });
  },

  // Advisory AI & Pattern Analysis
  async getAiAnalysis(caseId) {
    return this._fetchJson(`/api/cases/${encodeURIComponent(caseId)}/ai/analysis`, {
      method: 'POST',
    });
  },

  // Evidence Package Exports
  async getEvidencePackageJson(caseId) {
    return this._fetchJson(`/api/cases/${encodeURIComponent(caseId)}/evidence-package/json`);
  },

  async getEvidencePackageMarkdown(caseId) {
    return this._fetchText(`/api/cases/${encodeURIComponent(caseId)}/evidence-package/markdown`);
  },

  // System Diagnostics & Monitoring
  async getMonitorStatus() {
    return this._fetchJson('/api/monitor/status');
  },

  async getChainsHealth() {
    return this._fetchJson('/api/chains/health');
  },

  // Investigation Alerts
  async getAlerts(unackOnly = false) {
    return this._fetchJson(`/api/alerts?unack_only=${unackOnly}`);
  },

  async getCaseAlerts(caseId, unackOnly = false) {
    return this._fetchJson(`/api/cases/${encodeURIComponent(caseId)}/alerts?unack_only=${unackOnly}`);
  },

  async acknowledgeAlert(alertId) {
    return this._fetchJson(`/api/alerts/${encodeURIComponent(alertId)}/acknowledge`, {
      method: 'POST',
    });
  },
};

var API = window.API;
