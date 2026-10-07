import * as THREE from 'three'
import { configureGarageMaterial } from './garage-material.js'
import { addHeadLights } from './garage-lights.js'

export function disposeObject(object) {
  object.traverse(child => {
    if (child.isLight) { child.dispose?.(); child.userData.ownedTexture?.dispose() }
    if (child.geometry?.userData.garageRecord) {
      const record = child.geometry.userData.garageRecord
      if (--record.users === 0) { child.geometry.dispose(); record.cache.delete(record.key) }
    } else child.geometry?.dispose()
    const materials = Array.isArray(child.material) ? child.material : child.material ? [child.material] : []
    materials.forEach(material => {
      if (material.userData.textureRecords) {
        for (const [cache, path] of material.userData.textureRecords) {
          const record = cache.get(path)
          if (--record.users === 0) { record.texture.dispose(); cache.delete(path) }
        }
      } else { material.map?.dispose(); material.userData.shaderTextures?.forEach(texture => texture.dispose()) }
      material.dispose()
    })
  })
  object.removeFromParent()
}

function buildMaterial(source, textureCache, onFailure, lightMode, onRender, paint, textTexture) {
  if (source.driverPlate && textTexture) source = { ...source, texture: textTexture }
  if (source.paintable && paint) {
    const effect = (source.effect || '').split('.')
    const tintOnly = effect.includes('paint') && !effect.includes('truckpaint')
    source = { ...source, ...(tintOnly ? { color: paint.accessoryColor || paint.color } : paint) }
  }
  const effect = (source.effect || '').split('.'), unlit = effect.includes('unlit'), additive = unlit && effect.includes('add')
  const color = source.color || [.48, .52, .49], transparent = additive || source.transparent || (source.opacity ?? 1) < 1
  const parameters = { color: new THREE.Color(...color), transparent, depthWrite: additive ? false : source.depthWrite ?? !transparent, alphaTest: source.alphaTest ?? 0, opacity: source.opacity ?? 1, side: THREE.DoubleSide, blending: additive ? THREE.AdditiveBlending : THREE.NormalBlending }
  const material = unlit ? new THREE.MeshBasicMaterial(parameters) : new THREE.MeshStandardMaterial({ ...parameters, metalness: source.metalness ?? 0, roughness: source.roughness ?? .65 })
  const textures = new Map()
  material.userData.textureRecords = []
  for (const path of new Set([source.texture, source.paintTexture, source.lightMask, source.lightAlpha].filter(Boolean))) {
    let record = textureCache.get(path)
    if (!record) {
      const texture = new THREE.TextureLoader().load(path, onRender, undefined, () => {
        // Recover a transient image request without replacing the shared texture.
        setTimeout(() => {
          if (textureCache.get(path) !== record) return
          new THREE.ImageLoader().load(path, image => {
            if (textureCache.get(path) !== record) return
            texture.image = image; texture.needsUpdate = true; onRender?.()
          }, undefined, () => {
            if (textureCache.get(path) !== record) return
            onFailure?.(`Unable to load truck texture after retry: ${path}`); onRender?.()
          })
        }, 250)
      })
      texture.flipY = false; texture.wrapS = texture.wrapT = THREE.RepeatWrapping; texture.colorSpace = THREE.SRGBColorSpace
      record = { texture, users: 0 }; textureCache.set(path, record)
    }
    record.users++; material.userData.textureRecords.push([textureCache, path]); textures.set(path, record.texture)
  }
  material.map = textures.get(source.texture) || null
  configureGarageMaterial(material, source, textures, lightMode)
  return material
}

export function updateTruckGroup(group, pointsGroup, data, onFailure, lightMode, onRender) {
  const instances = group.userData.instances ||= new Map(), counts = new Map(), retained = new Set()
  const textureCache = group.userData.textureCache ||= new Map()
  const geometryCache = group.userData.geometryCache ||= new Map()
  for (const part of data.parts) {
    const prefix = JSON.stringify([part.vehicleId, part.id, part.category, part.definition]), index = counts.get(prefix) || 0
    counts.set(prefix, index + 1)
    const key = `${prefix}:${index}`
    retained.add(key)
    let instance = instances.get(key)
    if (instance && instance.userData.modelKey !== part.modelKey) { disposeObject(instance); instances.delete(key); instance = null }
    if (!instance) {
      instance = new THREE.Group(); instance.userData.modelKey = part.modelKey; instance.userData.paintKey = JSON.stringify([part.paint, part.textTexture])
      for (const [pieceIndex, piece] of (part.model.pieces || []).entries()) {
        const geometryKey = JSON.stringify([part.modelKey, pieceIndex])
        let record = part.modelKey && geometryCache.get(geometryKey)
        if (!record) {
          const geometry = new THREE.BufferGeometry()
          geometry.setAttribute('position', new THREE.Float32BufferAttribute(piece.positions || [], 3))
          if (piece.normals?.length) geometry.setAttribute('normal', new THREE.Float32BufferAttribute(piece.normals, 3))
          if (piece.uvs?.length) geometry.setAttribute('uv', new THREE.Float32BufferAttribute(piece.uvs, 2))
          const shaderUvs = piece.material?.paintUv === 0 ? piece.uvs : piece.uvs1 || piece.uvs
          if (shaderUvs?.length) geometry.setAttribute('garageUv', new THREE.Float32BufferAttribute(shaderUvs, 2))
          if (piece.indices?.length) geometry.setIndex(piece.indices)
          if (!piece.normals?.length) geometry.computeVertexNormals()
          record = { geometry, users: 0, key: geometryKey, cache: geometryCache }
          if (part.modelKey) { geometryCache.set(geometryKey, record); geometry.userData.garageRecord = record }
        }
        record.users++
        const source = { ...piece.material, lampAuxiliary: (part.model.locators || []).some(locator => /flare\.vehicle\.aux_light/.test(locator.hookup || '')) }
        const material = buildMaterial(source, textureCache, onFailure, lightMode, onRender, part.paint, part.textTexture)
        const mesh = new THREE.Mesh(record.geometry, material); mesh.userData.vehicleId = part.vehicleId; mesh.userData.section = part.section; mesh.userData.accessoryId = part.id; mesh.userData.category = part.category; instance.add(mesh)
      }
      if (part.model.headLights) addHeadLights(instance, part.model.headLights, lightMode, onRender, onFailure)
      instances.set(key, instance); group.add(instance)
    }
    const paintKey = JSON.stringify([part.paint, part.textTexture])
    if (instance.userData.paintKey !== paintKey) {
      part.model.pieces.forEach((piece, index) => {
        if (!piece.material?.paintable && !piece.material?.driverPlate) return
        const mesh = instance.children[index], old = mesh.material
        mesh.material = buildMaterial(piece.material, textureCache, onFailure, lightMode, onRender, part.paint, part.textTexture)
        // Acquire replacement textures before releasing the old references.
        for (const [cache, path] of old.userData.textureRecords) {
          const record = cache.get(path)
          if (--record.users === 0) { record.texture.dispose(); cache.delete(path) }
        }
        old.dispose()
      })
      instance.userData.paintKey = paintKey
    }
    instance.position.fromArray(part.position || [0, 0, 0]); instance.quaternion.fromArray(part.rotation || [0, 0, 0, 1]); instance.scale.fromArray(part.scale || [1, 1, 1])
  }
  for (const [key, instance] of instances) if (!retained.has(key)) { disposeObject(instance); instances.delete(key) }

  const markers = pointsGroup.userData.instances ||= new Map()
  counts.clear(); retained.clear()
  for (const point of data.points) {
    const prefix = JSON.stringify([point.vehicleId, point.accessoryId, point.kind, point.name]), index = counts.get(prefix) || 0
    counts.set(prefix, index + 1)
    const key = `${prefix}:${index}`
    retained.add(key)
    let holder = markers.get(key)
    if (!holder) {
      holder = new THREE.Group()
      for (const [shape, opacity] of [['sphere', .96], ['ring', .76]]) {
        const geometryKey = `marker-${shape}`
        let record = geometryCache.get(geometryKey)
        if (!record) {
          const geometry = shape === 'sphere' ? new THREE.SphereGeometry(.057, 14, 10) : new THREE.TorusGeometry(.095, .007, 5, 24)
          record = { geometry, users: 0, key: geometryKey, cache: geometryCache }
          geometryCache.set(geometryKey, record); geometry.userData.garageRecord = record
        }
        record.users++
        holder.add(new THREE.Mesh(record.geometry, new THREE.MeshBasicMaterial({ color: '#c7ddff', transparent: true, opacity })))
      }
      markers.set(key, holder); pointsGroup.add(holder)
    }
    holder.position.fromArray(point.position || [0, 0, 0]); holder.quaternion.fromArray(point.rotation || [0, 0, 0, 1]); holder.scale.fromArray(point.scale || [1, 1, 1])
    holder.userData.pick = { vehicleId: point.vehicleId, section: point.section, accessoryId: point.accessoryId, name: point.name, hookup: point.hookup, kind: point.kind, category: point.category }
    holder.children.forEach(mesh => { mesh.userData.pick = holder.userData.pick })
  }
  for (const [key, holder] of markers) if (!retained.has(key)) { disposeObject(holder); markers.delete(key) }
}
