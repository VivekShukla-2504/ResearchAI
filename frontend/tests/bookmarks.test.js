import assert from 'node:assert/strict'
import { test } from 'node:test'
import { requestBookmarkChange } from '../src/lib/bookmarks.js'

const paper = { paper_id: 'paper_123', title: 'A paper' }

test('confirmed bookmark save returns saved state and success feedback', async () => {
  const bookmark = { paper_id: paper.paper_id, title: paper.title, created_at: '2026-10-13T00:00:00Z' }
  let calls = 0
  const result = await requestBookmarkChange({
    paper,
    isSaved: false,
    client: { addBookmark: async (paperId) => { calls += 1; assert.equal(paperId, paper.paper_id); return bookmark } },
  })

  assert.equal(calls, 1)
  assert.equal(result.status, 'success')
  assert.equal(result.action, 'save')
  assert.equal(result.message, 'Paper saved to bookmarks')
  assert.equal(result.bookmark, bookmark)
})

test('confirmed removal returns removal feedback', async () => {
  let calls = 0
  const result = await requestBookmarkChange({
    paper,
    isSaved: true,
    client: { removeBookmark: async () => { calls += 1; return { deleted: true } } },
  })

  assert.equal(calls, 1)
  assert.equal(result.status, 'success')
  assert.equal(result.action, 'remove')
  assert.equal(result.message, 'Bookmark removed')
})

test('failed save returns error feedback without a saved-state action', async () => {
  const result = await requestBookmarkChange({
    paper,
    isSaved: false,
    client: { addBookmark: async () => { throw new Error('MongoDB unavailable') } },
  })

  assert.equal(result.status, 'error')
  assert.equal(result.action, 'none')
  assert.equal(result.message, 'MongoDB unavailable')
})
