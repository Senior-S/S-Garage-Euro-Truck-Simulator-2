import test from 'node:test'
import assert from 'node:assert/strict'
import * as THREE from 'three'
import { updateTruckGroup, disposeObject } from '../src/scene-update.js'

const model = { pieces: [{ positions: [0, 0, 0, 1, 0, 0, 0, 1, 0], indices: [0, 1, 2], material: {} }] }
const part = (id, modelKey, position = [0, 0, 0]) => ({ id, category: 'accessory', modelKey, position, model })
const point = position => ({ accessoryId: 'cab', kind: 'hookup', name: 'slot_0', position })

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
  assert.equal(instances.length, 2)
  assert.deepEqual(instances.map(instance => instance.position.x), [-1, 1])
  assert.ok(instances.every(instance => instance.children[0].userData.accessoryId === 'wheel'))
  assert.equal(markers.children.length, 2)
  updateTruckGroup(group, markers, { parts: [part('wheel', 'tire', [-2, 0, 0]), part('wheel', 'tire', [2, 0, 0])], points: [] })
  assert.deepEqual([...group.userData.instances.values()], instances)
  assert.deepEqual(instances.map(instance => instance.position.x), [-2, 2])
  disposeObject(group)
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
