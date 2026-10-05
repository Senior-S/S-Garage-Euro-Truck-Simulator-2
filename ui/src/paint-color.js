// Keep color conversion available before the full 3D viewer is loaded.
import { Color } from 'three/src/math/Color.js'

// SII colors are linear RGB; browser color pickers use sRGB.
export function paintHex(value = '(1, 1, 1)') {
  const components = (value.match(/&[\da-fA-F]{8}|[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?/g) || []).map(token => {
    if (!token.startsWith('&')) return Number(token)
    const bytes = new DataView(new ArrayBuffer(4))
    bytes.setUint32(0, parseInt(token.slice(1), 16))
    return bytes.getFloat32(0)
  })
  return '#' + new Color(...(components.length >= 3 ? components.slice(0, 3) : [1, 1, 1])).getHexString()
}

export function paintRgb(hex) { return new Color(hex).toArray() }
