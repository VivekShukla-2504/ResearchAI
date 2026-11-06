const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')
const SESSION_STORAGE_KEY = 'researchpaper-ai.local-session'
const AUTH_TOKEN_KEY = 'researchpaper-ai.auth-token'
const USER_KEY = 'researchpaper-ai.auth-user'
let memorySessionId = null

function createSessionId() {
  return globalThis.crypto?.randomUUID?.() || `local-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function getStoredToken() {
  try {
    return window.localStorage.getItem(AUTH_TOKEN_KEY) || null
  } catch {
    return null
  }
}

export function getStoredUser() {
  try {
    const raw = window.localStorage.getItem(USER_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export function setAuth(token, user) {
  try {
    if (token) window.localStorage.setItem(AUTH_TOKEN_KEY, token)
    else window.localStorage.removeItem(AUTH_TOKEN_KEY)
    if (user) window.localStorage.setItem(USER_KEY, JSON.stringify(user))
    else window.localStorage.removeItem(USER_KEY)
  } catch {
    // Browser storage may be blocked
  }
}

export function clearAuth() {
  try {
    window.localStorage.removeItem(AUTH_TOKEN_KEY)
    window.localStorage.removeItem(USER_KEY)
  } catch {
    // Browser storage may be blocked
  }
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
  const token = getStoredToken()
  const headers = {
    'Content-Type': 'application/json',
    'X-Session-ID': localSessionId(),
    ...options.headers,
  }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers,
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
  suggest: (query, limit = 6) => apiRequest(`/papers/suggest?q=${encodeURIComponent(query)}&limit=${limit}`),
  search: (query, limit = 10, category = '') => {
    let url = `/papers/search?q=${encodeURIComponent(query)}&limit=${limit}`
    if (category) url += `&category=${encodeURIComponent(category)}`
    return apiRequest(url)
  },
  paper: (paperId) => apiRequest(`/papers/${encodeURIComponent(paperId)}`),
  recommendations: (paperId, k = 5, category = '') => {
    let url = `/papers/${encodeURIComponent(paperId)}/recommendations?k=${k}`
    if (category) url += `&category=${encodeURIComponent(category)}`
    return apiRequest(url)
  },
  personalizedRecommendations: (k = 10, category = '') => {
    let url = `/papers/recommendations/personalized?k=${k}`
    if (category) url += `&category=${encodeURIComponent(category)}`
    return apiRequest(url)
  },
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

  // Authentication & Profile
  getStoredToken,
  getStoredUser,
  setAuth,
  clearAuth,
  sendOtp: (email, purpose = 'signup') => apiRequest('/auth/send-otp', {
    method: 'POST',
    body: JSON.stringify({ email, purpose }),
  }),
  signup: ({ name, email, password, otp }) => apiRequest('/auth/signup', {
    method: 'POST',
    body: JSON.stringify({ name, email, password, otp }),
  }),
  login: (email, password) => apiRequest('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  }),
  loginOtp: (email, otp) => apiRequest('/auth/login-otp', {
    method: 'POST',
    body: JSON.stringify({ email, otp }),
  }),
  googleAuth: (credential) => apiRequest('/auth/google', {
    method: 'POST',
    body: JSON.stringify({ credential }),
  }),
  resetPassword: ({ email, otp, newPassword }) => apiRequest('/auth/reset-password', {
    method: 'POST',
    body: JSON.stringify({ email, otp, new_password: newPassword }),
  }),
  me: () => apiRequest('/auth/me'),
}
