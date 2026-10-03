import * as THREE from 'three'
import { configureGarageMaterial } from './garage-material.js'

export function disposeObject(object) {
  object.traverse(child => {
    child.geometry?.dispose()
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

export function updateTruckGroup(group, pointsGroup, data, onFailure, lightMode) {
  const instances = group.userData.instances ||= new Map(), counts = new Map(), retained = new Set()
  const textureCache = group.userData.textureCache ||= new Map()
  for (const part of data.parts) {
    const prefix = JSON.stringify([part.id, part.category, part.definition]), index = counts.get(prefix) || 0
    counts.set(prefix, index + 1)
    const key = `${prefix}:${index}`
    retained.add(key)
    let instance = instances.get(key)
    if (instance && instance.userData.modelKey !== part.modelKey) { disposeObject(instance); instances.delete(key); instance = null }
    if (!instance) {
      instance = new THREE.Group(); instance.userData.modelKey = part.modelKey
      for (const piece of part.model.pieces || []) {
        const geometry = new THREE.BufferGeometry()
        geometry.setAttribute('position', new THREE.Float32BufferAttribute(piece.positions || [], 3))
        if (piece.normals?.length) geometry.setAttribute('normal', new THREE.Float32BufferAttribute(piece.normals, 3))
        if (piece.uvs?.length) geometry.setAttribute('uv', new THREE.Float32BufferAttribute(piece.uvs, 2))
        const shaderUvs = piece.material?.paintUv === 0 ? piece.uvs : piece.uvs1 || piece.uvs
        if (shaderUvs?.length) geometry.setAttribute('garageUv', new THREE.Float32BufferAttribute(shaderUvs, 2))
        if (piece.indices?.length) geometry.setIndex(piece.indices)
        if (!piece.normals?.length) geometry.computeVertexNormals()
        const source = piece.material || {}, color = source.color || [.48, .52, .49], transparent = source.transparent || (source.opacity ?? 1) < 1
        const material = new THREE.MeshStandardMaterial({ color: new THREE.Color(...color), metalness: source.metalness ?? .54, roughness: source.roughness ?? .5, transparent, depthWrite: source.depthWrite ?? !transparent, alphaTest: source.alphaTest ?? 0, opacity: source.opacity ?? 1, side: THREE.DoubleSide })
        const textures = new Map()
        material.userData.textureRecords = []
        for (const path of new Set([source.texture, source.paintTexture, source.lightMask, source.lightAlpha].filter(Boolean))) {
          let record = textureCache.get(path)
          if (!record) {
            const texture = new THREE.TextureLoader().load(path, undefined, undefined, () => onFailure?.(`Unable to load truck texture: ${path}`))
            texture.flipY = false; texture.wrapS = texture.wrapT = THREE.RepeatWrapping; texture.colorSpace = THREE.SRGBColorSpace
            record = { texture, users: 0 }; textureCache.set(path, record)
          }
          record.users++; material.userData.textureRecords.push([textureCache, path]); textures.set(path, record.texture)
        }
        material.map = textures.get(source.texture) || null
        configureGarageMaterial(material, source, textures, lightMode)
        const mesh = new THREE.Mesh(geometry, material); mesh.userData.accessoryId = part.id; mesh.userData.category = part.category; instance.add(mesh)
      }
      for (const locator of part.model.locators || []) {
        const hookup = locator.hookup || ''
        if (!/flare\.vehicle\.(headl|high_beam|aux_lightb)/.test(hookup)) continue
        const pixels = new Uint8Array(32 * 32 * 4)
        for (let y = 0; y < 32; y++) for (let x = 0; x < 32; x++) {
          const index = (y * 32 + x) * 4, radius = Math.hypot((x - 15.5) / 15.5, (y - 15.5) / 15.5)
          pixels.set([255, 246, 222, Math.round(Math.max(0, 1 - radius) ** 3 * 255)], index)
        }
        const texture = new THREE.DataTexture(pixels, 32, 32); texture.needsUpdate = true
        const flare = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, toneMapped: false }))
        flare.position.fromArray(locator.position || [0, 0, 0]); flare.scale.set(.32, .32, 1)
        flare.userData.lightModeMinimum = /headl/.test(hookup) ? 1 : 2
        flare.visible = (lightMode?.value || 0) >= flare.userData.lightModeMinimum
        instance.add(flare)
      }
      instances.set(key, instance); group.add(instance)
    }
    instance.position.fromArray(part.position || [0, 0, 0]); instance.quaternion.fromArray(part.rotation || [0, 0, 0, 1]); instance.scale.fromArray(part.scale || [1, 1, 1])
  }
  for (const [key, instance] of instances) if (!retained.has(key)) { disposeObject(instance); instances.delete(key) }

  const markers = pointsGroup.userData.instances ||= new Map()
  counts.clear(); retained.clear()
  for (const point of data.points) {
    const prefix = JSON.stringify([point.accessoryId, point.kind, point.name]), index = counts.get(prefix) || 0
    counts.set(prefix, index + 1)
    const key = `${prefix}:${index}`
    retained.add(key)
    let holder = markers.get(key)
    if (!holder) {
      holder = new THREE.Group()
      holder.add(new THREE.Mesh(new THREE.SphereGeometry(.057, 14, 10), new THREE.MeshBasicMaterial({ color: '#c7ddff', transparent: true, opacity: .96 })))
      holder.add(new THREE.Mesh(new THREE.TorusGeometry(.095, .007, 5, 24), new THREE.MeshBasicMaterial({ color: '#c7ddff', transparent: true, opacity: .76 })))
      markers.set(key, holder); pointsGroup.add(holder)
    }
    holder.position.fromArray(point.position || [0, 0, 0]); holder.quaternion.fromArray(point.rotation || [0, 0, 0, 1]); holder.scale.fromArray(point.scale || [1, 1, 1])
    holder.userData.pick = { accessoryId: point.accessoryId, name: point.name, hookup: point.hookup, kind: point.kind, category: point.category }
    holder.children.forEach(mesh => { mesh.userData.pick = holder.userData.pick })
  }
  for (const [key, holder] of markers) if (!retained.has(key)) { disposeObject(holder); markers.delete(key) }
}
