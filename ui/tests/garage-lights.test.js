import test from 'node:test'
import assert from 'node:assert/strict'
import * as THREE from 'three'
import { addHeadLights } from '../src/garage-lights.js'
import { configureGarageMaterial } from '../src/garage-material.js'
import { disposeObject } from '../src/scene-update.js'

test('game reflector placement, beam range, tint and cookies survive import', () => {
  const original = THREE.TextureLoader.prototype.load, disposed = []
  THREE.TextureLoader.prototype.load = path => { const texture = new THREE.Texture(); texture.addEventListener('dispose', () => disposed.push(path)); return texture }
  const rig = new THREE.Group()
  try {
    addHeadLights(rig, { fields: { reflectors_offset: '(0, .82, -2.98)', reflectors_distance: '2.09', low_beam_color: '(6, 5.4, 3.2)', low_beam_range: '80', hi_beam_range: '180', low_beam_aspect: '2' }, masks: { low_beam: '/low', hi_beam: '/high' } }, { value: 1 })
    const lights = rig.children.filter(child => child.isLight)
    assert.equal(lights.length, 4)
    assert.equal(lights.filter(light => light.visible).length, 4)
    assert.equal(lights.filter(light => light.intensity > 0).length, 2)
    assert.equal(lights[0].intensity, lights[0].userData.beamIntensity)
    assert.deepEqual(lights[0].position.toArray(), [1.045, .82, -2.98])
    assert.equal(lights[0].distance, 80); assert.equal(lights[2].distance, 180)
    assert.equal(lights[0].map, lights[1].map)
    assert.equal(lights[0].shadow.mapSize.x / lights[0].shadow.mapSize.y, 2)
    assert.ok(lights[0].target.position.y < lights[0].position.y)
    assert.equal(lights[0].color.r, 1)
    disposeObject(rig); assert.deepEqual(disposed, ['/low', '/high'])
  } finally { THREE.TextureLoader.prototype.load = original }
})

test('vehicle and auxiliary lamps use distinct programs and mask channels', () => {
  const texture = new THREE.Texture(), programs = []
  for (const lampAuxiliary of [false, true]) {
    const material = new THREE.MeshStandardMaterial()
    configureGarageMaterial(material, { lightMask: '/mask', lampAuxiliary }, new Map([['/mask', texture]]))
    const shader = { uniforms: {}, vertexShader: THREE.ShaderLib.standard.vertexShader, fragmentShader: THREE.ShaderLib.standard.fragmentShader }
    material.onBeforeCompile(shader); programs.push([material.customProgramCacheKey(), shader.fragmentShader])
  }
  assert.notEqual(programs[0][0], programs[1][0])
  assert.ok(programs[0][1].includes('lamp.g * front *'))
  assert.ok(programs[1][1].includes('lamp.r * .2'))
})

test('large auxiliary arrays keep a bounded number of beam lights', () => {
  const rig = new THREE.Group()
  addHeadLights(rig, { auxiliary: Array.from({ length: 40 }, () => ({ mode: 'roof_beam', position: [0, 3, -2] })) }, { value: 2 })
  assert.equal(rig.children.filter(child => child.isSpotLight && child.intensity > 0).length, 4)
  assert.equal(rig.children.filter(child => child.isSpotLight && child.visible).length, 6)
  disposeObject(rig)
})
