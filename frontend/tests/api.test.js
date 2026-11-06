import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { createServer } from 'vite'

const originalFetch = globalThis.fetch
const originalWindow = globalThis.window

after(() => {
  globalThis.fetch = originalFetch
  if (originalWindow === undefined) delete globalThis.window
  else globalThis.window = originalWindow
})

async function loadApi(t) {
  const server = await createServer({
    configFile: false,
    appType: 'custom',
    logLevel: 'silent',
    server: { middlewareMode: true },
  })
  t.after(() => server.close())
  return server.ssrLoadModule('/src/lib/api.js')
}

function jsonResponse(payload = {}) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

test('reuses one stored session ID for interest GET and PUT', async (t) => {
  const values = new Map()
  globalThis.window = {
    sessionStorage: {
      getItem: (key) => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, value),
    },
  }
  const requests = []
  globalThis.fetch = async (_url, options) => {
    requests.push(options)
    return jsonResponse({ terms: [] })
  }

  const { api } = await loadApi(t)
  await api.interests()
  await api.saveInterests(['machine learning'])

  assert.equal(requests.length, 2)
  assert.ok(requests[0].headers['X-Session-ID'])
  assert.equal(requests[0].headers['X-Session-ID'], requests[1].headers['X-Session-ID'])
  assert.equal(values.get('researchpaper-ai.local-session'), requests[0].headers['X-Session-ID'])
})

test('continues requests with a stable page session when browser storage is blocked', async (t) => {
  globalThis.window = {
    sessionStorage: {
      getItem: () => { throw new Error('storage blocked') },
      setItem: () => { throw new Error('storage blocked') },
    },
  }
  const requests = []
  globalThis.fetch = async (_url, options) => {
    requests.push(options)
    return jsonResponse()
  }

  const { api } = await loadApi(t)
  await api.health()
  await api.interests()

  assert.equal(requests.length, 2)
  assert.ok(requests[0].headers['X-Session-ID'])
  assert.equal(requests[0].headers['X-Session-ID'], requests[1].headers['X-Session-ID'])
})

test('clears revoked credentials and notifies the app on protected 401 responses', async (t) => {
  const values = new Map()
  const authEvents = []
  globalThis.window = {
    localStorage: {
      getItem: (key) => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, value),
      removeItem: (key) => values.delete(key),
    },
    sessionStorage: {
      getItem: () => null,
      setItem: () => {},
    },
    dispatchEvent: (event) => authEvents.push(event),
  }
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Invalid or revoked token.' }), {
    status: 401,
    headers: { 'Content-Type': 'application/json' },
  })

  const { api } = await loadApi(t)
  api.setAuth('revoked-token', { user_id: 'user-1' })
  await assert.rejects(api.search('graph'), { status: 401 })

  assert.equal(api.getStoredToken(), null)
  assert.equal(authEvents.length, 1)
  assert.equal(authEvents[0].type, 'researchpaper-auth-expired')
  assert.equal(authEvents[0].detail.token, 'revoked-token')

  api.setAuth('still-valid-token', { user_id: 'user-1' })
  await assert.rejects(api.login('researcher@example.edu', 'wrong-password'), { status: 401 })
  assert.equal(api.getStoredToken(), 'still-valid-token')
  assert.equal(authEvents.length, 1)
})

test('keeps the signed-in session usable when local storage is blocked', async (t) => {
  globalThis.window = {
    localStorage: {
      getItem: () => { throw new Error('storage blocked') },
      setItem: () => { throw new Error('storage blocked') },
      removeItem: () => { throw new Error('storage blocked') },
    },
    sessionStorage: {
      getItem: () => null,
      setItem: () => {},
    },
  }
  const requests = []
  globalThis.fetch = async (_url, options) => {
    requests.push(options)
    return jsonResponse()
  }

  const { api } = await loadApi(t)
  api.setAuth('page-token', { user_id: 'user-1' })
  await api.search('graph')

  assert.equal(requests[0].headers.Authorization, 'Bearer page-token')
  assert.equal(api.getStoredToken(), 'page-token')
  assert.equal(api.getStoredUser().user_id, 'user-1')
})
