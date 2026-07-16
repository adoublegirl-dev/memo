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
  memory: (id) => request(`/api/memory/${id}`),
  persona: () => request('/api/persona'),
  todos: (params = {}) => request(`/api/todos?${new URLSearchParams(params)}`),
  todoAction: (body) => request('/api/todo/action', { method: 'POST', body: JSON.stringify(body) }),
  spaces: (params = {}) => request(`/api/spaces?${new URLSearchParams(params)}`),
  space: (id) => request(`/api/space/${encodeURIComponent(id)}`),
  spaceAction: (body) => request('/api/space/action', { method: 'POST', body: JSON.stringify(body) }),
};
