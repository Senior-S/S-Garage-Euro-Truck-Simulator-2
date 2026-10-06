import * as THREE from 'three'

// SCS reflector rotations are degrees; their forward direction is local -Z.
export function addHeadLights(instance, lighting, lightMode, onRender, onFailure) {
  const { fields = {}, masks = {} } = lighting
  const numbers = (name, fallback) => (String(fields[name] ?? '').match(/[-+]?\d*\.?\d+(?:e[-+]?\d+)?/gi) || []).map(Number).concat(fallback).slice(0, fallback.length)
  const offset = numbers('reflectors_offset', [0, .8, -3]), distance = numbers('reflectors_distance', [2])[0]
  const fixtures = [
    { mode: 'low_beam', minimum: 1, maximum: 1, positions: [[offset[0] + distance / 2, offset[1], offset[2]], [offset[0] - distance / 2, offset[1], offset[2]]] },
    { mode: 'hi_beam', minimum: 2, maximum: 2, positions: [[offset[0] + distance / 2, offset[1], offset[2]], [offset[0] - distance / 2, offset[1], offset[2]]] },
    ...(lighting.auxiliary || []).slice(0, 2).map(auxiliary => ({ ...auxiliary, minimum: 2, maximum: 2, positions: [auxiliary.position] })),
  ]
  for (const { mode, minimum, maximum, positions } of fixtures) {
    let texture
    if (masks[mode]) {
      texture = new THREE.TextureLoader().load(masks[mode], onRender, undefined, () => { onFailure?.(`Unable to load headlight projection: ${masks[mode]}`); onRender?.() })
      texture.colorSpace = THREE.NoColorSpace
      texture.wrapS = texture.wrapT = THREE.ClampToEdgeWrapping
    }
    for (const [index, position] of positions.entries()) {
      const side = index === 0 ? 'left' : 'right'
      const color = numbers(mode + '_color', [6, 5.4, 3.2]), strength = Math.max(...color, .01)
      // Browser photometry differs from SCS. Keep relative game colors/intensity.
      const light = new THREE.SpotLight(new THREE.Color(...color.map(value => value / strength)), strength * 12, numbers(mode + '_range', [80])[0], THREE.MathUtils.degToRad(numbers(mode + '_angle', [65])[0] / 2), .15, 2)
      light.position.fromArray(position)
      const rotation = numbers(mode + '_' + side + '_rot', [-3, 0, 0]).map(THREE.MathUtils.degToRad)
      const base = numbers(side + '_rot', [0, 0, 0]).map(THREE.MathUtils.degToRad)
      const direction = new THREE.Vector3(0, 0, -1).applyEuler(new THREE.Euler(...rotation, 'YXZ')).applyEuler(new THREE.Euler(...base, 'YXZ'))
      light.target.position.copy(light.position).add(direction)
      light.map = texture || null
      const aspect = Math.max(.1, numbers(mode + '_aspect', [2])[0])
      light.shadow.mapSize.set(512 * aspect, 512)
      light.userData.lightModeMinimum = minimum; light.userData.lightModeMaximum = maximum
      light.userData.beamIntensity = light.intensity
      light.intensity = (lightMode?.value || 0) >= minimum && (lightMode?.value || 0) <= maximum ? light.userData.beamIntensity : 0
      // One owner per shared cookie, released with the light rig.
      if (side === 'left' && texture) light.userData.ownedTexture = texture
      instance.add(light, light.target)
    }
  }
}
