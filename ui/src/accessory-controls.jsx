import React from 'react'
import { paintHex, paintRgb } from './paint-color.js'

export default function AccessoryControls({ part, definition, busy, edit }) {
  const options = definition?.options || {}
  const supportsText = options.text || part.type === 'vehicle_drv_plate_accessory'
  let savedText = part.fields.text || ''
  try { savedText = JSON.parse(savedText) } catch { /* Preserve unquoted legacy text. */ }
  const savedColor = paintHex(part.fields.paint_color || options.defaultColor)
  const [text, setText] = React.useState(savedText), [color, setColor] = React.useState(savedColor)
  React.useEffect(() => { setText(savedText); setColor(savedColor) }, [part.id, part.dataPath, savedText, savedColor])
  if (!supportsText && !options.paintColor) return null
  const changes = {}
  if (supportsText && text !== savedText) changes.text = text
  if (options.paintColor && color !== savedColor) changes.paint_color = paintRgb(color)
  return <div className="paint-controls accessory-controls">
    <h3>Customize part</h3>
    {supportsText && <>
      <label className="accessory-text"><span>Plate text</span><input type="text" value={text} maxLength={1024} disabled={busy} onChange={event => setText(event.target.value)} /></label>
      {!options.text && <p className="paint-note">This saved part has a text field, but its current model may not display lettering.</p>}
    </>}
    {options.paintColor && <label><span>Part color</span><input type="color" aria-label="Part color" value={color} disabled={busy} onChange={event => setColor(event.target.value)} /><small>{color.toUpperCase()}</small></label>}
    <div className="paint-actions"><button className="save-button" disabled={busy || !Object.keys(changes).length} onClick={() => edit({ op: 'options', accessoryId: part.id, options: changes })}>Apply options</button></div>
  </div>
}
