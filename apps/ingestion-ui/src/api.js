const API = '/api';
const LIGHTRAG = '/lightrag';

async function request(url, options = {}) {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

// Workspaces
export const listWorkspaces = () => request(`${API}/v1/workspaces`);

export const deleteWorkspace = (workspace) =>
  request(`${API}/v1/workspaces/${encodeURIComponent(workspace)}`, { method: 'DELETE' });

// Jobs
export const listJobs = (workspace, status, limit = 50) => {
  const p = new URLSearchParams();
  if (workspace) p.set('workspace', workspace);
  if (status) p.set('status', status);
  p.set('limit', String(limit));
  return request(`${API}/v1/jobs?${p}`);
};

export const getJob = (jobId) => request(`${API}/v1/jobs/${jobId}`);

// Documents
export const ingestDocument = (file, workspace) => {
  const form = new FormData();
  form.append('file', file);
  return fetch(`${API}/v1/documents/ingest`, {
    method: 'POST',
    headers: { 'X-Workspace': workspace },
    body: form,
  }).then((r) => r.json());
};

export const ingestCodebase = (file, workspace) => {
  const form = new FormData();
  form.append('file', file);
  return fetch(`${API}/v1/codebase/ingest`, {
    method: 'POST',
    headers: { 'X-Workspace': workspace },
    body: form,
  }).then((r) => r.json());
};

export const deleteDocument = (docId) =>
  request(`${API}/v1/documents/${docId}`, { method: 'DELETE' });

// Delete documents from LightRAG knowledge graph (entities, relations, embeddings)
export const deleteLightragDocs = (docIds, workspace) =>
  request(`${LIGHTRAG}/documents/delete_document`, {
    method: 'DELETE',
    headers: { 'LIGHTRAG-WORKSPACE': workspace, 'Content-Type': 'application/json' },
    body: JSON.stringify({ doc_ids: docIds }),
  });

// Clear entire workspace in LightRAG (all docs, entities, relations, embeddings)
export const clearWorkspace = (workspace) =>
  request(`${LIGHTRAG}/documents`, {
    method: 'DELETE',
    headers: { 'LIGHTRAG-WORKSPACE': workspace },
  });

export const downloadDocumentUrl = (docId) =>
  `${API}/v1/documents/${docId}/download`;

// LightRAG
export const listLightragDocs = (workspace) =>
  request(`${LIGHTRAG}/documents`, {
    headers: { 'LIGHTRAG-WORKSPACE': workspace },
  });

export const queryGraph = (query, workspace, mode = 'naive', opts = {}) => {
  const payload = { query, mode, ...opts };
  // For graph-aware modes, supply keywords from query to skip LLM extraction
  if (mode !== 'naive' && !opts.ll_keywords && !opts.hl_keywords) {
    payload.ll_keywords = [query];
    payload.hl_keywords = [query];
  }
  return request(`${LIGHTRAG}/query/data`, {
    method: 'POST',
    headers: { 'LIGHTRAG-WORKSPACE': workspace, 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
};

export const queryExplain = (query, workspace, mode = 'mix') =>
  request(`${LIGHTRAG}/query`, {
    method: 'POST',
    headers: { 'LIGHTRAG-WORKSPACE': workspace, 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, mode, stream: false }),
  });

// Graph
export const getGraphLabels = (workspace) =>
  request(`${LIGHTRAG}/graph/label/list`, {
    headers: { 'LIGHTRAG-WORKSPACE': workspace },
  });

export const getGraphByLabel = (label, workspace) =>
  request(`${LIGHTRAG}/graphs?label=${encodeURIComponent(label)}`, {
    headers: { 'LIGHTRAG-WORKSPACE': workspace },
  });

// Health
export const healthCheck = () => request(`${API}/health`);
