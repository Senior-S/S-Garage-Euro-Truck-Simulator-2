const queue = []
const modelCache = new Map()
let activeJobs = 0
let thumbnails

export async function cachedThumbnail(key) {
  thumbnails ||= caches.open('yard-catalog-thumbnails-v1')
  const cached = await (await thumbnails).match(key)
  return cached ? cached.text() : null
}

export async function storeThumbnail(key, preview) {
  thumbnails ||= caches.open('yard-catalog-thumbnails-v1')
  const cache = await thumbnails
  await cache.put(key, new Response(preview))
  const keys = await cache.keys()
  for (const entry of keys.slice(0, Math.max(0, keys.length - 512))) await cache.delete(entry)
}

function pumpQueue() {
  while (activeJobs < 2 && queue.length) {
    const job = queue.shift()
    job.signal?.removeEventListener('abort', job.cancel)
    if (job.signal?.aborted) { job.reject(new DOMException('Preview cancelled', 'AbortError')); continue }
    activeJobs++
    Promise.resolve().then(() => job.task(job.signal)).then(job.resolve, job.reject).finally(() => { activeJobs--; pumpQueue() })
  }
}

export function queuePreview(task, signal, priority = false) {
  return new Promise((resolve, reject) => {
    const job = { task, signal, resolve, reject }
    job.cancel = () => {
      const index = queue.indexOf(job)
      if (index >= 0) queue.splice(index, 1)
      reject(new DOMException('Preview cancelled', 'AbortError'))
    }
    signal?.addEventListener('abort', job.cancel, { once: true })
    if (priority) queue.unshift(job)
    else queue.push(job)
    pumpQueue()
  })
}

export function cachedModel(path) {
  const model = modelCache.get(path)
  if (model) { modelCache.delete(path); modelCache.set(path, model) }
  return model
}

export function cacheModel(path, model) {
  modelCache.delete(path); modelCache.set(path, model)
  while (modelCache.size > 12) modelCache.delete(modelCache.keys().next().value)
}

export function clearModelCache(includeThumbnails = false) {
  modelCache.clear()
  if (includeThumbnails) {
    thumbnails = undefined
    return caches.delete('yard-catalog-thumbnails-v1')
  }
}
