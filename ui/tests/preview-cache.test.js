import test from 'node:test'
import assert from 'node:assert/strict'
import { cachedThumbnail, storeThumbnail, clearModelCache, cacheModel, cachedModel } from '../src/preview-cache.js'

test('thumbnail storage works on its first use and retains the newest 512 previews', async () => {
  const entries = new Map(Array.from({ length: 512 }, (_, index) => [`old-${index}`, `preview-${index}`]))
  globalThis.caches = {
    open: async () => ({
      put: async (key, response) => entries.set(key, await response.text()),
      match: async key => entries.has(key) ? new Response(entries.get(key)) : undefined,
      keys: async () => [...entries.keys()],
      delete: async key => entries.delete(key),
    }),
  }
  try {
    await storeThumbnail('new', 'data:image/png;base64,preview')
    assert.equal(entries.size, 512)
    assert.equal(await cachedThumbnail('old-0'), null)
    assert.equal(await cachedThumbnail('new'), 'data:image/png;base64,preview')
    cacheModel('old', { cached: true })
    let deleted
    globalThis.caches.delete = async name => { deleted = name; entries.clear(); return true }
    await clearModelCache(true)
    assert.equal(deleted, 'yard-catalog-thumbnails-v2')
    assert.equal(cachedModel('old'), undefined)
    assert.equal(await cachedThumbnail('new'), null)
  } finally { delete globalThis.caches }
})
