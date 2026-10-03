import * as THREE from 'three'

// Shared by the garage and catalog so game shader inputs have one interpretation.
export function configureGarageMaterial(material, source, textures, lightMode = { value: 0 }) {
  const paint = textures.get(source.paintTexture), lamps = textures.get(source.lightMask), alpha = textures.get(source.lightAlpha)
  if (!paint && !lamps) return
  if (paint) paint.colorSpace = source.airbrush ? THREE.SRGBColorSpace : THREE.NoColorSpace
  for (const texture of [lamps, alpha]) if (texture) { texture.colorSpace = THREE.NoColorSpace; texture.wrapS = texture.wrapT = THREE.RepeatWrapping }
  material.userData.shaderTextures = [paint, lamps, alpha].filter(Boolean)
  material.customProgramCacheKey = () => JSON.stringify([Boolean(paint), Boolean(lamps), source.airbrush, source.paintUv])
  material.onBeforeCompile = shader => {
    shader.uniforms.garageLights = lightMode
    shader.vertexShader = shader.vertexShader.replace('#include <common>', '#include <common>\nattribute vec2 garageUv; varying vec2 vGarageUv;')
      .replace('#include <begin_vertex>', '#include <begin_vertex>\nvGarageUv = garageUv;')
    let declarations = 'varying vec2 vGarageUv; uniform float garageLights;\n'
    if (paint) {
      Object.assign(shader.uniforms, { garagePaint: { value: paint }, garageBase: { value: new THREE.Color(...source.color) }, garageRed: { value: new THREE.Color(...source.paintColors[0]) }, garageGreen: { value: new THREE.Color(...source.paintColors[1]) }, garageBlue: { value: new THREE.Color(...source.paintColors[2]) } })
      declarations += 'uniform sampler2D garagePaint; uniform vec3 garageBase, garageRed, garageGreen, garageBlue;\n'
      const blend = source.airbrush ? 'mix(garageBase, p.rgb, p.a)' : 'mix(mix(mix(garageBase, garageBlue, p.b), garageGreen, p.g), garageRed, p.r)'
      shader.fragmentShader = shader.fragmentShader.replace('#include <map_fragment>', `vec4 p = texture2D(garagePaint, vGarageUv); diffuseColor.rgb = ${blend};\n#include <map_fragment>`)
    }
    if (lamps) {
      Object.assign(shader.uniforms, { garageLampMask: { value: lamps }, garageLampAlpha: { value: alpha || lamps } })
      declarations += 'uniform sampler2D garageLampMask, garageLampAlpha;\n'
      shader.fragmentShader = shader.fragmentShader.replace('#include <emissivemap_fragment>', `#include <emissivemap_fragment>
        vec3 lamp = pow(texture2D(garageLampMask, vGarageUv).rgb, vec3(2.2));
        float positional = pow(texture2D(garageLampAlpha, vGarageUv).r, 2.2);
        float front = step(-1.0, vGarageUv.x) * (1.0 - step(2.0, vGarageUv.x));
        float middle = step(4.0, vGarageUv.x) * (1.0 - step(5.0, vGarageUv.x));
        float lit = positional + lamp.b * (front + middle) + lamp.g * (front + middle) * step(1.5, garageLights);
        totalEmissiveRadiance += vec3(1.0, .93, .78) * lit * step(.5, garageLights) * 3.0;`)
    }
    shader.fragmentShader = shader.fragmentShader.replace('#include <common>', `#include <common>\n${declarations}`)
  }
}
