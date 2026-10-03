import React from 'react'
import * as THREE from 'three'
import { configureGarageMaterial } from './garage-material.js'

const queue = []
const modelCache = new Map()
let activeJobs = 0
let thumbnails
let thumbnailRenderer

export async function cachedThumbnail(key) {
  thumbnails ||= caches.open('yard-catalog-thumbnails-v1')
  const cached = await (await thumbnails).match(key)
  return cached ? cached.text() : null
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

export function clearModelCache() { modelCache.clear() }

async function buildModelScene(model, signal) {
  if (!model.pieces?.length) throw new Error('This definition has no renderable geometry.')
  const loader = new THREE.TextureLoader(), textures = new Map()
  const paths = [...new Set(model.pieces.flatMap(piece => [piece.material?.texture, piece.material?.lightMask, piece.material?.lightAlpha]).filter(Boolean))]
  const scene = new THREE.Scene(), group = new THREE.Group()
  try {
    const loaded = await Promise.allSettled(paths.map(async path => {
      const response = await fetch(path, { signal })
      if (!response.ok) throw new Error(`Texture request failed (${response.status}): ${path}`)
      const url = URL.createObjectURL(await response.blob())
      try {
        const texture = await loader.loadAsync(url)
        texture.colorSpace = THREE.SRGBColorSpace; texture.flipY = false; texture.wrapS = texture.wrapT = THREE.RepeatWrapping; textures.set(path, texture)
      } catch (error) {
        throw new Error(`Unable to decode texture ${path}: ${error.message || 'image loading failed'}`, { cause: error })
      } finally { URL.revokeObjectURL(url) }
    }))
    const failed = loaded.find(result => result.status === 'rejected')
    if (failed) throw failed.reason
    if (signal?.aborted) throw new DOMException('Preview cancelled', 'AbortError')
    scene.add(new THREE.HemisphereLight(0xe1e5eb, 0x30343a, 2.25))
    const key = new THREE.DirectionalLight(0xf0eee6, 3.1); key.position.set(-3, 6, 5); scene.add(key)
    const fill = new THREE.DirectionalLight(0xaebdd1, 1.15); fill.position.set(5, 2, -5); scene.add(fill)
    for (const piece of model.pieces) {
      const geometry = new THREE.BufferGeometry()
      geometry.setAttribute('position', new THREE.Float32BufferAttribute(piece.positions || [], 3))
      if (piece.normals?.length) geometry.setAttribute('normal', new THREE.Float32BufferAttribute(piece.normals, 3))
      if (piece.uvs?.length) geometry.setAttribute('uv', new THREE.Float32BufferAttribute(piece.uvs, 2))
      if (piece.uvs1?.length || piece.uvs?.length) geometry.setAttribute('garageUv', new THREE.Float32BufferAttribute(piece.uvs1 || piece.uvs, 2))
      if (piece.indices?.length) geometry.setIndex(piece.indices)
      if (!piece.normals?.length) geometry.computeVertexNormals()
      const source = piece.material || {}, color = source.color || [.48, .55, .54], transparent = source.transparent || (source.opacity ?? 1) < 1
      const material = new THREE.MeshStandardMaterial({ color: new THREE.Color(color[0], color[1], color[2]), map: textures.get(source.texture) || null, metalness: source.metalness ?? .48, roughness: source.roughness ?? .52, transparent, depthWrite: source.depthWrite ?? !transparent, alphaTest: source.alphaTest ?? 0, opacity: source.opacity ?? 1, side: THREE.DoubleSide })
      configureGarageMaterial(material, source, textures)
      group.add(new THREE.Mesh(geometry, material))
    }
    scene.add(group)
    const bounds = new THREE.Box3().setFromObject(group), center = bounds.getCenter(new THREE.Vector3()), sphere = bounds.getBoundingSphere(new THREE.Sphere())
    group.children.forEach(mesh => mesh.geometry.translate(-center.x, -center.y, -center.z))
    return { scene, group, radius: Math.max(sphere.radius, .01), textures }
  } catch (error) {
    scene.traverse(object => {
      object.geometry?.dispose()
      const materials = Array.isArray(object.material) ? object.material : object.material ? [object.material] : []
      materials.forEach(material => material.dispose())
    })
    textures.forEach(texture => texture.dispose())
    throw error
  }
}

function disposeModelScene(renderer, scene, textures) {
  scene.traverse(object => {
    object.geometry?.dispose()
    const materials = Array.isArray(object.material) ? object.material : object.material ? [object.material] : []
    materials.forEach(material => material.dispose())
  })
  textures.forEach(texture => texture.dispose())
  renderer?.dispose(); renderer?.forceContextLoss()
}

function frameModel(camera, radius) {
  const vertical = THREE.MathUtils.degToRad(camera.fov / 2), horizontal = Math.atan(Math.tan(vertical) * camera.aspect)
  const distance = radius / Math.sin(Math.min(vertical, horizontal)) * 1.08
  camera.position.copy(new THREE.Vector3(.62, .24, -.75).normalize().multiplyScalar(distance)); camera.lookAt(0, 0, 0)
}

export async function renderModelThumbnail(model, signal, width = 240, height = 200, cacheKey) {
  let built
  try {
    built = await buildModelScene(model, signal)
    // Rendering and capture are synchronous, so queued imports share one context.
    thumbnailRenderer ||= new THREE.WebGLRenderer({ alpha: true, antialias: true, preserveDrawingBuffer: true })
    const renderer = thumbnailRenderer
    renderer.setPixelRatio(1); renderer.setSize(width, height, false); renderer.outputColorSpace = THREE.SRGBColorSpace; renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.05
    const camera = new THREE.PerspectiveCamera(31, width / height, .01, 10000)
    frameModel(camera, built.radius)
    renderer.render(built.scene, camera)
    if (signal?.aborted) throw new DOMException('Preview cancelled', 'AbortError')
    const preview = renderer.domElement.toDataURL('image/png')
    if (cacheKey) {
      const cache = await thumbnails
      await cache.put(cacheKey, new Response(preview))
      const keys = await cache.keys()
      for (const key of keys.slice(0, Math.max(0, keys.length - 512))) await cache.delete(key)
    }
    return preview
  } finally {
    if (built) disposeModelScene(null, built.scene, built.textures)
  }
}

export function AnimatedPartPreview({ model, label, onFailure }) {
  const canvasRef = React.useRef(null)
  React.useEffect(() => {
    if (!canvasRef.current) return
    const canvas = canvasRef.current
    const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true }); renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5)); renderer.outputColorSpace = THREE.SRGBColorSpace; renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.05
    let built, observer, frame = 0, previous = 0, disposed = false
    const camera = new THREE.PerspectiveCamera(31, 1, .01, 10000)
    const controller = new AbortController()
    const resize = () => {
      const width = canvas.clientWidth || 240, height = canvas.clientHeight || 144
      renderer.setSize(width, height, false); camera.aspect = width / height; camera.updateProjectionMatrix()
      if (built) {
        frameModel(camera, built.radius)
      }
    }
    buildModelScene(model, controller.signal).then(result => { if (disposed) { disposeModelScene(renderer, result.scene, result.textures); return } built = result; resize() }).catch(error => { if (!disposed) onFailure?.(error.message) })
    observer = new ResizeObserver(resize); observer.observe(canvas)
    const draw = time => {
      frame = requestAnimationFrame(draw)
      if (!built) return
      if (previous) built.group.rotation.y += Math.min((time - previous) / 1000, .05) * Math.PI * .8
      previous = time; renderer.render(built.scene, camera)
    }
    frame = requestAnimationFrame(draw)
    return () => { disposed = true; controller.abort(); cancelAnimationFrame(frame); observer?.disconnect(); if (built) disposeModelScene(renderer, built.scene, built.textures); else { renderer.dispose(); renderer.forceContextLoss() } }
  }, [model])
  return <canvas ref={canvasRef} className="catalog-preview-3d" aria-label={`${label} rotating model preview`} />
}
