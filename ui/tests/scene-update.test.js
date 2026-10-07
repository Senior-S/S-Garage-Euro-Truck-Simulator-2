import test from 'node:test'
import assert from 'node:assert/strict'
import * as THREE from 'three'
import { updateTruckGroup, disposeObject } from '../src/scene-update.js'

const model = { pieces: [{ positions: [0, 0, 0, 1, 0, 0, 0, 1, 0], indices: [0, 1, 2], material: {} }] }
const part = (id, modelKey, position = [0, 0, 0]) => ({ id, category: 'accessory', modelKey, position, model })
const point = position => ({ accessoryId: 'cab', kind: 'hookup', name: 'slot_0', position })

test('a failed texture request retries once using the same shared texture', async () => {
  const originalTexture = THREE.TextureLoader.prototype.load, originalImage = THREE.ImageLoader.prototype.load
  const group = new THREE.Group(), markers = new THREE.Group(), failures = []
  let fail, retries = 0, renders = 0
  const image = { width: 256, height: 256 }
  THREE.TextureLoader.prototype.load = (path, loaded, progress, error) => { fail = error; return new THREE.Texture() }
  THREE.ImageLoader.prototype.load = (path, loaded) => { retries++; loaded(image) }
  try {
    const textured = { ...part('disc', 'disc'), model: { pieces: [{ ...model.pieces[0], material: { texture: '/disc.png' } }] } }
    updateTruckGroup(group, markers, { parts: [textured], points: [] }, error => failures.push(error), { value: 0 }, () => renders++)
    const texture = group.children[0].children[0].material.map
    fail()
    await new Promise(resolve => setTimeout(resolve, 300))
    assert.equal(retries, 1)
    assert.equal(group.children[0].children[0].material.map, texture)
    assert.equal(texture.image, image)
    assert.equal(renders, 1)
    assert.deepEqual(failures, [])
    // Pending errors belonging to a removed truck must not start new requests.
    fail(); updateTruckGroup(group, markers, { parts: [], points: [] })
    await new Promise(resolve => setTimeout(resolve, 300))
    assert.equal(retries, 1)
    THREE.ImageLoader.prototype.load = (path, loaded, progress, error) => { retries++; error() }
    updateTruckGroup(group, markers, { parts: [textured], points: [] }, error => failures.push(error))
    fail()
    await new Promise(resolve => setTimeout(resolve, 300))
    assert.equal(retries, 2)
    assert.deepEqual(failures, ['Unable to load truck texture after retry: /disc.png'])
  } finally {
    disposeObject(group); disposeObject(markers)
    THREE.TextureLoader.prototype.load = originalTexture; THREE.ImageLoader.prototype.load = originalImage
  }
})

test('plate text edits retain geometry and isolate duplicate instances and back materials', () => {
  const original = THREE.TextureLoader.prototype.load, disposed = []
  THREE.TextureLoader.prototype.load = path => {
    const texture = new THREE.Texture(); texture.name = path
    texture.addEventListener('dispose', () => disposed.push(path)); return texture
  }
  const group = new THREE.Group(), markers = new THREE.Group()
  const plate = { pieces: [
    { ...model.pieces[0], material: { driverPlate: true, texture: '/blank' } },
    { ...model.pieces[0], material: { texture: '/back' } },
  ] }
  const first = { ...part('driver', 'plate'), model: plate, textTexture: '/senior' }
  const second = { ...part('passenger', 'plate'), model: plate, textTexture: '/senior' }
  try {
    updateTruckGroup(group, markers, { parts: [first, second], points: [] })
    const mesh = group.children[0].children[0], geometry = mesh.geometry, back = group.children[0].children[1].material
    assert.equal(mesh.material.map.name, '/senior')
    first.textTexture = '/new-name'
    updateTruckGroup(group, markers, { parts: [first, second], points: [] })
    assert.equal(mesh.geometry, geometry)
    assert.equal(mesh.material.map.name, '/new-name')
    assert.equal(group.children[1].children[0].material.map.name, '/senior')
    assert.equal(group.children[0].children[1].material, back)
    assert.deepEqual(disposed, [])
    first.textTexture = '/senior' // Undo reuses the surviving texture.
    updateTruckGroup(group, markers, { parts: [first, second], points: [] })
    assert.deepEqual(disposed, ['/new-name'])
    first.textTexture = '/empty'
    updateTruckGroup(group, markers, { parts: [first, second], points: [] })
    assert.equal(mesh.material.map.name, '/empty')
  } finally { disposeObject(group); disposeObject(markers); THREE.TextureLoader.prototype.load = original }
})

test('TruckersMP underbody glow uses unlit additive blending without an opaque depth plane', () => {
  const group = new THREE.Group(), markers = new THREE.Group()
  const glow = { ...part('glow', 'glow'), model: { pieces: [{ ...model.pieces[0], material: { effect: 'eut2.unlit.tex.add', depthWrite: true } }] } }
  updateTruckGroup(group, markers, { parts: [glow], points: [] })
  const material = group.children[0].children[0].material
  assert.equal(material.isMeshBasicMaterial, true)
  assert.equal(material.blending, THREE.AdditiveBlending)
  assert.equal(material.transparent, true)
  assert.equal(material.depthWrite, false)
  disposeObject(group); disposeObject(markers)
})

test('tire decals use their accessory tint without importing the truck paint atlas or finish', () => {
  const original = THREE.TextureLoader.prototype.load, loaded = []
  THREE.TextureLoader.prototype.load = path => { loaded.push(path); return new THREE.Texture() }
  const group = new THREE.Group(), markers = new THREE.Group()
  const tire = { ...part('tire', 'tire'), model: { pieces: [{ ...model.pieces[0], material: { effect: 'eut2.dif.spec.paint.decal.over', paintable: true, texture: '/lettering', roughness: .64, metalness: 0, transparent: true } }] },
    paint: { color: [.1, .2, .3], accessoryColor: [.8, .1, .2], paintTexture: '/body-atlas', metalness: .18, roughness: .42, flipColor: [1, 1, 1] } }
  try {
    updateTruckGroup(group, markers, { parts: [tire], points: [] })
    const mesh = group.children[0].children[0], geometry = mesh.geometry
    assert.deepEqual(loaded, ['/lettering'])
    assert.deepEqual(mesh.material.color.toArray(), [.8, .1, .2])
    assert.equal(mesh.material.roughness, .64); assert.equal(mesh.material.metalness, 0)
    tire.paint = { ...tire.paint, accessoryColor: [.1, .8, .2] }
    updateTruckGroup(group, markers, { parts: [tire], points: [] })
    assert.equal(mesh.geometry, geometry)
    assert.deepEqual(mesh.material.color.toArray(), [.1, .8, .2])
    assert.deepEqual(loaded, ['/lettering'])
  } finally { disposeObject(group); disposeObject(markers); THREE.TextureLoader.prototype.load = original }
})

test('texture completion requests a frame for the idle garage', () => {
  const original = THREE.TextureLoader.prototype.load, callbacks = []
  THREE.TextureLoader.prototype.load = function (path, onLoad) { callbacks.push(onLoad); return new THREE.Texture() }
  const group = new THREE.Group(), markers = new THREE.Group()
  let renders = 0
  try {
    const textured = { ...part('cab', 'cab'), model: { pieces: [{ ...model.pieces[0], material: { texture: '/base' } }] } }
    updateTruckGroup(group, markers, { parts: [textured], points: [] }, null, { value: 0 }, () => renders++)
    callbacks[0]()
    assert.equal(renders, 1)
    const material = [...group.userData.instances.values()][0].children[0].material
    assert.equal(material.metalness, 0)
    assert.equal(material.roughness, .65)
  } finally { disposeObject(group); THREE.TextureLoader.prototype.load = original }
})

test('paint changes replace materials while retaining truck geometry and markers', () => {
  const group = new THREE.Group(), markers = new THREE.Group()
  const painted = { ...part('cab', 'cab'), model: { pieces: [{ ...model.pieces[0], material: { paintable: true } }] }, paint: { color: [1, 0, 0] } }
  updateTruckGroup(group, markers, { parts: [painted], points: [point([0, 0, 0])] })
  const mesh = [...group.userData.instances.values()][0].children[0], geometry = mesh.geometry, material = mesh.material, marker = markers.children[0]
  updateTruckGroup(group, markers, { parts: [{ ...painted, paint: { color: [0, 1, 0] } }], points: [point([0, 0, 0])] })
  assert.equal(mesh.geometry, geometry)
  assert.notEqual(mesh.material, material)
  assert.deepEqual(mesh.material.color.toArray(), [0, 1, 0])
  assert.equal(markers.children[0], marker)
  disposeObject(group); disposeObject(markers)
})

test('paint textures are shared between instances and released only after the last user is removed', () => {
  const original = THREE.TextureLoader.prototype.load, loaded = [], disposed = []
  THREE.TextureLoader.prototype.load = path => {
    const texture = new THREE.Texture(); loaded.push(path); texture.addEventListener('dispose', () => disposed.push(path)); return texture
  }
  const group = new THREE.Group(), markers = new THREE.Group(); group.add(markers)
  const painted = { pieces: [{ ...model.pieces[0], uvs: [0, 0, 1, 0, 0, 1], material: { texture: '/base', paintTexture: '/mask', color: [1, 1, 1], paintColors: [[1, 0, 0], [0, 1, 0], [0, 0, 1]] } }] }
  const first = { ...part('cab', 'painted'), model: painted }, second = { ...part('panel', 'painted'), model: painted }
  try {
    updateTruckGroup(group, markers, { parts: [first, second], points: [] })
    assert.deepEqual(loaded, ['/base', '/mask'])
    assert.equal(group.userData.textureCache.get('/mask').users, 2)
    updateTruckGroup(group, markers, { parts: [first], points: [] })
    assert.deepEqual(disposed, [])
    updateTruckGroup(group, markers, { parts: [], points: [] })
    assert.equal(group.userData.textureCache.size, 0)
    assert.deepEqual(disposed, ['/base', '/mask'])
  } finally { disposeObject(group); THREE.TextureLoader.prototype.load = original }
})

test('replaces only changed geometry, preserves moved meshes and markers, and disposes removed objects', () => {
  const group = new THREE.Group(), markers = new THREE.Group(); group.add(markers)
  updateTruckGroup(group, markers, { parts: [part('cab', 'cab-a'), part('toy', 'toy-a')], points: [point([0, 0, 0])] })
  const [cab, toy] = [...group.userData.instances.values()], marker = markers.children[0]
  const cabGeometry = cab.children[0].geometry, toyGeometry = toy.children[0].geometry
  let disposed = 0; toyGeometry.addEventListener('dispose', () => disposed++)
  updateTruckGroup(group, markers, { parts: [part('cab', 'cab-a', [2, 0, 0]), part('toy', 'toy-b')], points: [point([2, 0, 0])] })
  assert.equal([...group.userData.instances.values()][0], cab)
  assert.equal(cab.children[0].geometry, cabGeometry)
  assert.deepEqual(cab.position.toArray(), [2, 0, 0])
  assert.notEqual([...group.userData.instances.values()][1], toy)
  assert.equal(disposed, 1)
  assert.equal(markers.children[0], marker)
  assert.deepEqual(marker.position.toArray(), [2, 0, 0])
  // Undo the model replacement without touching the cab's buffers.
  updateTruckGroup(group, markers, { parts: [part('cab', 'cab-a'), part('toy', 'toy-a')], points: [point([0, 0, 0])] })
  assert.equal([...group.userData.instances.values()][0].children[0].geometry, cabGeometry)
  updateTruckGroup(group, markers, { parts: [part('cab', 'cab-a')], points: [] })
  assert.equal(group.userData.instances.size, 1)
  assert.equal(markers.children.length, 0)
  assert.equal(markers.userData.instances.size, 0)
  disposeObject(group)
})

test('duplicate and wheel instances keep separate transforms and remain selectable', () => {
  const group = new THREE.Group(), markers = new THREE.Group(); group.add(markers)
  updateTruckGroup(group, markers, { parts: [part('wheel', 'tire', [-1, 0, 0]), part('wheel', 'tire', [1, 0, 0])], points: [point([-1, 0, 0]), point([1, 0, 0])] })
  const instances = [...group.userData.instances.values()]
  assert.equal(instances[0].children[0].geometry, instances[1].children[0].geometry)
  assert.notEqual(instances[0].children[0].material, instances[1].children[0].material)
  assert.equal(instances.length, 2)
  assert.deepEqual(instances.map(instance => instance.position.x), [-1, 1])
  assert.ok(instances.every(instance => instance.children[0].userData.accessoryId === 'wheel'))
  assert.equal(markers.children.length, 2)
  assert.equal(markers.children[0].children[0].geometry, markers.children[1].children[0].geometry)
  updateTruckGroup(group, markers, { parts: [part('wheel', 'tire', [-2, 0, 0]), part('wheel', 'tire', [2, 0, 0])], points: [] })
  assert.deepEqual([...group.userData.instances.values()], instances)
  assert.deepEqual(instances.map(instance => instance.position.x), [-2, 2])
  const geometry = instances[0].children[0].geometry
  let released = 0
  geometry.addEventListener('dispose', () => released++)
  updateTruckGroup(group, markers, { parts: [part('wheel', 'tire', [-2, 0, 0])], points: [] })
  assert.equal(released, 0)
  disposeObject(group)
  assert.equal(released, 1)
  assert.equal(group.userData.geometryCache.size, 0)
})

test('removing one hookup preserves different hookups on the same owner', () => {
  const group = new THREE.Group(), markers = new THREE.Group(); group.add(markers)
  const horn = { ...part('bar', 'horn'), category: 'hookup', definition: '/horn' }
  const lamp = { ...part('bar', 'lamp'), category: 'hookup', definition: '/lamp' }
  updateTruckGroup(group, markers, { parts: [horn, lamp], points: [] })
  const retained = [...group.userData.instances.values()][1]
  updateTruckGroup(group, markers, { parts: [lamp], points: [] })
  assert.equal([...group.userData.instances.values()][0], retained)
  disposeObject(group)
})


test('shared accessory IDs in trailer sections retain independent meshes and markers', () => {
  const group = new THREE.Group(), markers = new THREE.Group(); group.add(markers)
  const first = { ...part('shared-body', 'body', [0, 0, 0]), vehicleId: 'front', section: 1 }
  const second = { ...first, vehicleId: 'rear', section: 2, position: [0, 0, 8] }
  const frontPoint = { ...point([0, 0, 0]), accessoryId: first.id, vehicleId: first.vehicleId, section: 1 }
  const rearPoint = { ...frontPoint, vehicleId: second.vehicleId, section: 2, position: [0, 0, 8] }
  updateTruckGroup(group, markers, { parts: [first, second], points: [frontPoint, rearPoint] })
  const [frontMesh, rearMesh] = [...group.userData.instances.values()]
  const [frontMarker, rearMarker] = markers.children
  assert.equal(frontMesh.children[0].userData.vehicleId, 'front')
  assert.equal(rearMesh.children[0].userData.vehicleId, 'rear')
  assert.equal(rearMesh.children[0].userData.section, 2)
  assert.equal(rearMarker.userData.pick.vehicleId, 'rear')
  assert.equal(rearMarker.children[0].userData.pick.section, 2)
  // Reordering a chain update must never swap ownership of retained objects.
  updateTruckGroup(group, markers, { parts: [second, first], points: [rearPoint, frontPoint] })
  assert.deepEqual([...group.userData.instances.values()], [frontMesh, rearMesh])
  assert.deepEqual(markers.children, [frontMarker, rearMarker])
  updateTruckGroup(group, markers, { parts: [second], points: [rearPoint] })
  assert.deepEqual([...group.userData.instances.values()], [rearMesh])
  assert.deepEqual(markers.children, [rearMarker])
  assert.deepEqual(rearMesh.position.toArray(), [0, 0, 8])
  disposeObject(group)
})
