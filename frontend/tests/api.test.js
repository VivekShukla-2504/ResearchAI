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
