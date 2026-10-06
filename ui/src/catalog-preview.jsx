import React from 'react'
import * as THREE from 'three'
import { configureGarageMaterial } from './garage-material.js'

import { queuePreview, cachedThumbnail, storeThumbnail, cacheModel, cachedModel, clearModelCache } from './preview-cache.js'
export { queuePreview, cachedThumbnail, cacheModel, cachedModel, clearModelCache }

let thumbnailRenderer

async function buildModelScene(model, signal) {
  if (!model.pieces?.length) throw new Error('This definition has no renderable geometry.')
  const loader = new THREE.TextureLoader(), textures = new Map()
  const paths = [...new Set(model.pieces.flatMap(piece => [piece.material?.texture, piece.material?.paintTexture, piece.material?.lightMask, piece.material?.lightAlpha]).filter(Boolean))]
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
      const source = piece.material || {}, effect = (source.effect || '').split('.'), unlit = effect.includes('unlit'), additive = unlit && effect.includes('add')
      const color = source.color || [.48, .55, .54], transparent = additive || source.transparent || (source.opacity ?? 1) < 1
      const parameters = { color: new THREE.Color(...color), map: textures.get(source.texture) || null, transparent, depthWrite: additive ? false : source.depthWrite ?? !transparent, alphaTest: source.alphaTest ?? 0, opacity: source.opacity ?? 1, side: THREE.DoubleSide, blending: additive ? THREE.AdditiveBlending : THREE.NormalBlending }
      const material = unlit ? new THREE.MeshBasicMaterial(parameters) : new THREE.MeshStandardMaterial({ ...parameters, metalness: source.metalness ?? 0, roughness: source.roughness ?? .65 })
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

function frameModel(camera, radius, paintPreview = false) {
  const vertical = THREE.MathUtils.degToRad(camera.fov / 2), horizontal = Math.atan(Math.tan(vertical) * camera.aspect)
  const distance = radius / Math.sin(Math.min(vertical, horizontal)) * 1.08
  camera.position.copy(new THREE.Vector3(paintPreview ? 1 : .62, .24, paintPreview ? -.35 : -.75).normalize().multiplyScalar(distance)); camera.lookAt(0, 0, 0)
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
    frameModel(camera, built.radius, model.paintPreview)
    renderer.render(built.scene, camera)
    if (signal?.aborted) throw new DOMException('Preview cancelled', 'AbortError')
    const preview = renderer.domElement.toDataURL('image/png')
    if (cacheKey) await storeThumbnail(cacheKey, preview)
    return preview
  } finally {
    if (built) disposeModelScene(null, built.scene, built.textures)
  }
}

export function AnimatedPartPreview({ model, label, onFailure, onLeave }) {
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
        frameModel(camera, built.radius, model.paintPreview)
      }
    }
    buildModelScene(model, controller.signal).then(result => { if (disposed) { disposeModelScene(renderer, result.scene, result.textures); return } built = result; resize() }).catch(error => { if (!disposed) onFailure?.(error.message) })
    observer = new ResizeObserver(resize); observer.observe(canvas)
    window.addEventListener('blur', onLeave)
    document.addEventListener('visibilitychange', onLeave)
    document.documentElement.addEventListener('pointerleave', onLeave)
    const draw = time => {
      if (document.hidden || !document.hasFocus() || !canvas.parentElement?.matches(':hover')) { onLeave(); return }
      frame = requestAnimationFrame(draw)
      if (!built) return
      if (previous) built.group.rotation.y += Math.min((time - previous) / 1000, .05) * Math.PI * .8
      previous = time; renderer.render(built.scene, camera)
    }
    frame = requestAnimationFrame(draw)
    return () => { disposed = true; controller.abort(); cancelAnimationFrame(frame); observer?.disconnect(); window.removeEventListener('blur', onLeave); document.removeEventListener('visibilitychange', onLeave); document.documentElement.removeEventListener('pointerleave', onLeave); if (built) disposeModelScene(renderer, built.scene, built.textures); else { renderer.dispose(); renderer.forceContextLoss() } }
  }, [model, onLeave])
  return <canvas ref={canvasRef} className="catalog-preview-3d" aria-label={`${label} rotating model preview`} />
}
