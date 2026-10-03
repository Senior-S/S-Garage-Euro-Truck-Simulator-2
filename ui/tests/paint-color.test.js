import test from 'node:test'
import assert from 'node:assert/strict'
import { paintHex, paintRgb } from '../src/paint-color.js'

test('game hexadecimal floats and decimal linear RGB decode to the same picker color', () => {
  assert.equal(paintHex('(&3e800000, &3f000000, &3f800000)'), paintHex('(0.25, 0.5, 1)'))
  assert.equal(paintHex('(1, 0, 0)'), '#ff0000')
})

test('picker colors round trip through linear RGB without changing their appearance', () => {
  for (const hex of ['#ffffff', '#000000', '#3f8aca', '#abcdef']) {
    const rgb = paintRgb(hex)
    assert.equal(paintHex(`(${rgb.join(',')})`), hex)
  }
  assert.ok(paintRgb('#808080')[0] < 0.22)
})
