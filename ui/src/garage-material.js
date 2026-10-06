import * as THREE from 'three'

// Shared by the garage and catalog so game shader inputs have one interpretation.
export function configureGarageMaterial(material, source, textures, lightMode = { value: 0 }) {
  const paint = textures.get(source.paintTexture), lamps = textures.get(source.lightMask), alpha = textures.get(source.lightAlpha)
  if (!paint && !lamps && !source.flipColor) return
  if (paint) paint.colorSpace = source.airbrush ? THREE.SRGBColorSpace : THREE.NoColorSpace
  for (const texture of [lamps, alpha]) if (texture) { texture.colorSpace = THREE.NoColorSpace; texture.wrapS = texture.wrapT = THREE.RepeatWrapping }
  material.userData.shaderTextures = [paint, lamps, alpha].filter(Boolean)
  material.customProgramCacheKey = () => JSON.stringify([Boolean(paint), Boolean(lamps), Boolean(alpha), Boolean(source.flipColor), source.airbrush, source.paintUv, Boolean(source.lampAuxiliary)])
  material.onBeforeCompile = shader => {
    shader.uniforms.garageLights = lightMode
    shader.vertexShader = shader.vertexShader.replace('#include <common>', '#include <common>\nattribute vec2 garageUv; varying vec2 vGarageUv;')
      .replace('#include <begin_vertex>', '#include <begin_vertex>\nvGarageUv = garageUv;')
    let declarations = 'varying vec2 vGarageUv; uniform float garageLights;\n'
    if (source.flipColor) {
      Object.assign(shader.uniforms, { garageFlip: { value: new THREE.Color(...source.flipColor) }, garageFlake: { value: new THREE.Color(...source.flakeColor) }, garageFlipStrength: { value: source.flipStrength } })
      declarations += 'uniform vec3 garageFlip, garageFlake; uniform float garageFlipStrength;\n'
      shader.fragmentShader = shader.fragmentShader.replace('#include <normal_fragment_maps>', '#include <normal_fragment_maps>\nfloat garageAngle = pow(1.0 - abs(dot(normal, normalize(vViewPosition))), 3.0); diffuseColor.rgb = mix(diffuseColor.rgb, garageFlip, clamp(garageAngle * garageFlipStrength, 0.0, .8)); diffuseColor.rgb = mix(diffuseColor.rgb, garageFlake, .06);')
    }
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
        float positional = ${alpha ? 'pow(texture2D(garageLampAlpha, vGarageUv).r, 2.2)' : '0.0'};
        float front = step(-1.0, vGarageUv.x) * (1.0 - step(2.0, vGarageUv.x));
        float rear = step(2.0, vGarageUv.x) * (1.0 - step(4.0, vGarageUv.x));
        float middle = step(4.0, vGarageUv.x) * (1.0 - step(5.0, vGarageUv.x));
        float lit = ${source.lampAuxiliary ? 'front * (lamp.r * .2 + lamp.g * step(1.5, garageLights))' : 'positional + lamp.b * (front + middle) + lamp.g * front * step(1.5, garageLights)'};
        // Rear position lights illuminate the lens texture at tail-light brightness.
        vec3 lampColor = ${source.lampAuxiliary ? 'mix(vec3(1.0, .93, .78), vec3(1.0, .24, .015), step(1.0, vGarageUv.x))' : 'mix(vec3(1.0, .93, .78), vec3(1.0, .015, .005), rear)'};
        vec3 lampEmission = ${source.lampAuxiliary ? 'lampColor * lit * 3.0' : 'mix(lampColor * lit * 3.0, diffuseColor.rgb * positional * 4.0, rear)'};
        totalEmissiveRadiance += lampEmission * step(.5, garageLights);`)
    }
    shader.fragmentShader = shader.fragmentShader.replace('#include <common>', `#include <common>\n${declarations}`)
  }
}
