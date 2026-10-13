const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')
const SESSION_STORAGE_KEY = 'researchpaper-ai.local-session'
let memorySessionId = null

function createSessionId() {
  return globalThis.crypto?.randomUUID?.() || `local-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function localSessionId() {
  if (memorySessionId) return memorySessionId
  try {
    let sessionId = window.sessionStorage.getItem(SESSION_STORAGE_KEY)
    if (!sessionId) {
      sessionId = createSessionId()
      window.sessionStorage.setItem(SESSION_STORAGE_KEY, sessionId)
    }
    memorySessionId = sessionId
  } catch {
    // Browser storage can be blocked. Keep one activity label for this page
    // lifetime; persistence across a refresh is unavailable in that case.
    memorySessionId = createSessionId()
  }
  return memorySessionId
}

export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export async function apiRequest(path, options = {}) {
  let response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        'X-Session-ID': localSessionId(),
        ...options.headers,
      },
    })
  } catch {
    throw new ApiError('The API could not be reached. Check that the FastAPI server is running.', 0)
  }

  let payload = null
  try {
    payload = await response.json()
  } catch {
    // Some error responses may not contain JSON.
  }
  if (!response.ok) {
    const detail = typeof payload?.detail === 'string' ? payload.detail : `Request failed (${response.status}).`
    throw new ApiError(detail, response.status)
  }
  return payload
}

export const api = {
  health: () => apiRequest('/health'),
  search: (query, limit = 10) => apiRequest(`/papers/search?q=${encodeURIComponent(query)}&limit=${limit}`),
  paper: (paperId) => apiRequest(`/papers/${encodeURIComponent(paperId)}`),
  recommendations: (paperId, k = 5) => apiRequest(`/papers/${encodeURIComponent(paperId)}/recommendations?k=${k}`),
  bookmarks: () => apiRequest('/session/bookmarks?limit=100'),
  addBookmark: (paperId) => apiRequest('/session/bookmarks', {
    method: 'POST',
    body: JSON.stringify({ paper_id: paperId }),
  }),
  removeBookmark: (paperId) => apiRequest(`/session/bookmarks/${encodeURIComponent(paperId)}`, { method: 'DELETE' }),
  history: () => apiRequest('/session/search-history?limit=50'),
  interests: () => apiRequest('/session/interests'),
  saveInterests: (terms) => apiRequest('/session/interests', {
    method: 'PUT',
    body: JSON.stringify({ terms }),
  }),
}
