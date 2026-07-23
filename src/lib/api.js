async function request(path, options = {}) {
  const res = await fetch(path, {
    headers: options.body ? { 'Content-Type': 'application/json' } : undefined,
    ...options,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

export const api = {
  stats: () => request('/api/stats'),
  tags: () => request('/api/tags'),
  graph: () => request('/api/graph'),
  memories: (params = {}) => request(`/api/memories?${new URLSearchParams(params)}`),
  memory: (id) => request(`/api/memory/${encodeURIComponent(id)}`),
  memoryAction: (body) => request('/api/memory/action', { method: 'POST', body: JSON.stringify(body) }),
  persona: () => request('/api/persona'),
  todos: (params = {}) => request(`/api/todos?${new URLSearchParams(params)}`),
  todo: (id) => request(`/api/todo/${encodeURIComponent(id)}`),
  todoAction: (body) => request('/api/todo/action', { method: 'POST', body: JSON.stringify(body) }),
  spaces: (params = {}) => request(`/api/spaces?${new URLSearchParams(params)}`),
  space: (id) => request(`/api/space/${encodeURIComponent(id)}`),
  spaceClassificationQueue: (params = {}) => request(`/api/space/classification-queue?${new URLSearchParams(params)}`),
  spaceCandidates: (params = {}) => request(`/api/space/candidates?${new URLSearchParams(params)}`),
  spaceCandidate: (id) => request(`/api/space/candidate/${encodeURIComponent(id)}`),
  sourceSessions: (params = {}) => request(`/api/source-sessions?${new URLSearchParams(params)}`),
  sourceSession: (id) => request(`/api/source-session/${encodeURIComponent(id)}`),
  spaceCandidateAction: (body) => request('/api/space/candidate/action', { method: 'POST', body: JSON.stringify(body) }),
  spaceAction: (body) => request('/api/space/action', { method: 'POST', body: JSON.stringify(body) }),
  personaAction: (body) => request('/api/persona/action', { method: 'POST', body: JSON.stringify(body) }),
  governance: (params = {}) => request(`/api/governance?${new URLSearchParams(params)}`),
  episodeSessionCandidates: (params = {}) => request(`/api/episode/session-candidates?${new URLSearchParams(params)}`),
  episodeSessionCandidate: (id) => request(`/api/episode/session-candidate/${encodeURIComponent(id)}`),
  episodeCanonicalizationRuns: (params = {}) => request(`/api/episode/canonicalization-runs?${new URLSearchParams(params)}`),
  episodeCanonicalizationRun: (id) => request(`/api/episode/canonicalization-run/${encodeURIComponent(id)}`),
  episodeCanonicalizationAction: (body) => request('/api/episode/canonicalization-run/action', { method: 'POST', body: JSON.stringify(body) }),
  episodePreview: (body) => request('/api/episode/preview', { method: 'POST', body: JSON.stringify(body) }),
  episodeImportRuns: (params = {}) => request(`/api/episode/import-runs?${new URLSearchParams(params)}`),
  episodeImportRun: (id) => request(`/api/episode/import-run/${encodeURIComponent(id)}`),
  episodeImportRunAction: (body) => request('/api/episode/import-run/action', { method: 'POST', body: JSON.stringify(body) }),
  memoryLink: (body) => request('/api/memory/link', { method: 'POST', body: JSON.stringify(body) }),
};
