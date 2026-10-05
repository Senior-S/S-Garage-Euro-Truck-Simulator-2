import React from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js'
import { disposeObject, updateTruckGroup } from './scene-update.js'

function frameTruck(camera, controls, size, center) {
  const longestSide = Math.max(size.x, size.z, 1)
  const horizontalFov = 2 * Math.atan(Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * camera.aspect)
  const distance = longestSide / (2 * Math.tan(horizontalFov / 2) * .88)
  controls.target.copy(center)
  camera.position.copy(center).add(new THREE.Vector3(distance * .56, size.y * .5 + distance * .31, -distance * .76))
}

export default function GarageScene({ onPick, onFailure, onIssues, onLoading, markerLabel, selectedAccessoryId, selectedVehicleId, selectedMarker, truckKey, sceneRevision, sessionId, truckId, cancelRef, lightMode = 'off', markerVisibility = 'all' }) {
  const host = React.useRef(null)
  const modelGroup = React.useRef(null)
  const runtime = React.useRef(null)
  const callbacks = React.useRef({ onPick, onFailure, onIssues, onLoading }); callbacks.current = { onPick, onFailure, onIssues, onLoading }
  const selectedRef = React.useRef(null); selectedRef.current = { id: selectedAccessoryId, vehicleId: selectedVehicleId, marker: selectedMarker }
  const previewRef = React.useRef(null); previewRef.current = { lightMode, markerVisibility }
  const highlight = ({ id, vehicleId, marker }) => modelGroup.current?.traverse(object => {
    if (object.userData.lightModeMinimum) {
      object.visible = ['off', 'low', 'high'].indexOf(previewRef.current.lightMode) >= object.userData.lightModeMinimum
      return
    }
    if (!object.isMesh) return
    if (object.userData.pick) {
      const point = object.userData.pick
      const selected = marker && point.vehicleId === marker.vehicleId && point.accessoryId === marker.accessoryId && point.name === marker.name && point.kind === marker.kind
      object.parent.visible = previewRef.current.markerVisibility === 'all' || previewRef.current.markerVisibility === 'selected' && Boolean(selected)
      object.material.color.setHex(selected ? 0xffc46b : 0xc7ddff)
      object.material.opacity = selected ? 1 : object.geometry.type === 'TorusGeometry' ? .76 : .96
      object.scale.setScalar(selected ? 1.35 : 1)
      return
    }
    if (!object.userData.accessoryId) return
    const materials = Array.isArray(object.material) ? object.material : [object.material]
    const selected = !marker && object.userData.vehicleId === vehicleId && object.userData.accessoryId === id
    materials.forEach(material => { if (material.emissive) { material.emissive.setHex(selected ? 0x526c95 : 0x000000); material.emissiveIntensity = selected ? .3 : 0 } })
  })
  const [loading, setLoading] = React.useState(true)
  const [markerChoices, setMarkerChoices] = React.useState(null)
  React.useEffect(() => {
    let scene, camera, renderer, controls, group, observer
    scene = new THREE.Scene(); scene.background = new THREE.Color('#141820'); scene.fog = new THREE.Fog('#141820', 22, 72)
    camera = new THREE.PerspectiveCamera(35, host.current.clientWidth / Math.max(host.current.clientHeight, 1), .02, 10000); camera.position.set(9.4, 5.7, -9.4)
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false }); renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2)); renderer.outputColorSpace = THREE.SRGBColorSpace; renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.05
    host.current.appendChild(renderer.domElement)
    const environment = new RoomEnvironment(), pmrem = new THREE.PMREMGenerator(renderer), reflection = pmrem.fromScene(environment)
    scene.environment = reflection.texture; scene.environmentIntensity = .55
    environment.dispose(); pmrem.dispose()
    controls = new OrbitControls(camera, renderer.domElement); controls.enableDamping = true; controls.dampingFactor = .065; controls.minDistance = 0; controls.maxDistance = 50; controls.target.set(0, 1, 0); controls.maxPolarAngle = Math.PI * .49
    scene.add(new THREE.HemisphereLight(0xd5deeb, 0x242830, 1.85))
    const key = new THREE.DirectionalLight(0xfff4e2, 2.8); key.position.set(-5, 12, -7); scene.add(key)
    const fill = new THREE.DirectionalLight(0xe1e8f2, 1.4); fill.position.set(5, 4, 8); scene.add(fill)
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(180, 180), new THREE.MeshStandardMaterial({ color: '#202630', roughness: .92, metalness: .14 })); floor.rotation.x = -Math.PI / 2; floor.position.y = -.03; scene.add(floor)
    const grid = new THREE.GridHelper(64, 64, 0x444e60, 0x2d3542); grid.position.y = -.017; grid.material.transparent = true; grid.material.opacity = .2; scene.add(grid)
    group = new THREE.Group(); modelGroup.current = group; scene.add(group)
    const pointsGroup = new THREE.Group(); group.add(pointsGroup)
    const current = { scene, camera, renderer, controls, group, pointsGroup, lightMode: { value: ['off', 'low', 'high'].indexOf(previewRef.current.lightMode) }, models: new Map(), revision: -1, initialized: false, box: new THREE.Box3() }
    runtime.current = current
    const resize = () => { if (!host.current || !renderer) return; const width = host.current.clientWidth, height = host.current.clientHeight; renderer.setSize(width, height, false); camera.aspect = width / Math.max(height, 1); camera.updateProjectionMatrix() }
    observer = new ResizeObserver(resize); observer.observe(host.current); resize()
    const raycaster = new THREE.Raycaster(), pointer = new THREE.Vector2(), projected = new THREE.Vector3()
    let press = null, dragged = false
    const pointerDown = event => { setMarkerChoices(null); if (!event.isPrimary) { dragged = true; return } press = { x: event.clientX, y: event.clientY, button: event.button }; dragged = false }
    const pointerMove = event => { if (press && Math.hypot(event.clientX - press.x, event.clientY - press.y) > 4) dragged = true }
    const pointerUp = event => { pointerMove(event); if (press?.button > 0) dragged = true; press = null }
    const pointerCancel = () => { press = null; dragged = true }
    const click = event => {
      if (dragged || press?.button > 0) { press = null; return }
      press = null
      const rect = renderer.domElement.getBoundingClientRect(); pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1; pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1
      scene.updateMatrixWorld(true); camera.updateMatrixWorld(true)
      raycaster.setFromCamera(pointer, camera)
      const visiblePoints = pointsGroup.children.filter(holder => holder.visible)
      const hits = new Set(raycaster.intersectObjects(visiblePoints, true).map(hit => hit.object.parent))
      const candidates = []
      for (const holder of visiblePoints) {
        holder.getWorldPosition(projected).project(camera)
        if (projected.z < -1 || projected.z > 1) continue
        const dx = (projected.x + 1) * rect.width / 2 + rect.left - event.clientX, dy = (1 - projected.y) * rect.height / 2 + rect.top - event.clientY
        const distance = dx * dx + dy * dy
        if (distance < 100 || hits.has(holder)) candidates.push({ holder, distance })
      }
      candidates.sort((a, b) => a.distance - b.distance)
      if (candidates.length > 1) setMarkerChoices({ x: Math.max(0, Math.min(event.clientX - rect.left, rect.width - 230)), y: Math.max(0, Math.min(event.clientY - rect.top, rect.height - 220)), points: candidates.map(candidate => candidate.holder.userData.pick) })
      else if (candidates.length) callbacks.current.onPick?.(candidates[0].holder.userData.pick)
      else { const partHit = raycaster.intersectObjects(group.children, true).find(item => item.object.userData.accessoryId); if (partHit) callbacks.current.onPick?.({ vehicleId: partHit.object.userData.vehicleId, section: partHit.object.userData.section, accessoryId: partHit.object.userData.accessoryId, category: partHit.object.userData.category }) }
    }
    renderer.domElement.addEventListener('pointerdown', pointerDown)
    renderer.domElement.addEventListener('pointermove', pointerMove)
    renderer.domElement.addEventListener('pointerup', pointerUp)
    renderer.domElement.addEventListener('pointercancel', pointerCancel)
    renderer.domElement.addEventListener('click', click)
    const reset = () => {
      if (current.box.isEmpty()) { controls.target.set(0, 1, 0); camera.position.set(9.4, 5.7, -9.4) }
      else frameTruck(camera, controls, current.box.getSize(new THREE.Vector3()), current.box.getCenter(new THREE.Vector3()))
      controls.update()
    }
    window.addEventListener('yard-reset-view', reset)
    renderer.setAnimationLoop(() => { controls.update(); renderer.render(scene, camera) })
    return () => {
      runtime.current = null; modelGroup.current = null
      window.removeEventListener('yard-reset-view', reset)
      renderer.domElement.removeEventListener('click', click)
      renderer.domElement.removeEventListener('pointerdown', pointerDown)
      renderer.domElement.removeEventListener('pointermove', pointerMove)
      renderer.domElement.removeEventListener('pointerup', pointerUp)
      renderer.domElement.removeEventListener('pointercancel', pointerCancel)
      observer.disconnect(); controls.dispose(); renderer.setAnimationLoop(null)
      disposeObject(scene); reflection.dispose(); renderer.dispose(); renderer.forceContextLoss(); renderer.domElement.remove()
    }
  }, [truckKey])
  React.useEffect(() => {
    const current = runtime.current
    if (!current) return
    let live = true
    const controller = new AbortController(), requestId = crypto.randomUUID()
    const cancel = () => {
      if (!live) return
      live = false; controller.abort()
      callbacks.current.onLoading?.(requestId, false)
      fetch('/api/cancel-scene', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ requestId }), keepalive: true }).catch(error => callbacks.current.onFailure?.(`Scene cancellation failed: ${error.message}`))
    }
    if (cancelRef) cancelRef.current = cancel
    callbacks.current.onLoading?.(requestId, true)
    setLoading(!current.initialized); setMarkerChoices(null)
    const update = async () => {
      const query = new URLSearchParams({ requestId, sessionId, truckId, revision: String(sceneRevision), sinceRevision: String(current.revision) })
      const response = await fetch(`/api/scene?${query}`, { signal: controller.signal })
      const data = await response.json()
      if (!response.ok) throw new Error(data.error || (data.cancelled ? 'This truck update was cancelled.' : `Scene request failed (${response.status})`))
      if (!live) return
      for (const [key, model] of Object.entries(data.models)) current.models.set(key, model)
      const parts = data.parts.map(part => {
        const model = current.models.get(part.modelKey)
        if (!model) throw new Error(`Scene update is missing model ${part.definition}. Reload the truck.`)
        return { ...part, model }
      })
      updateTruckGroup(current.group, current.pointsGroup, { parts, points: data.points }, callbacks.current.onFailure, current.lightMode)
      const used = new Set(parts.map(part => part.modelKey))
      for (const key of current.models.keys()) if (!used.has(key)) current.models.delete(key)
      current.box.setFromObject(current.group)
      if (!current.box.isEmpty()) {
        const size = current.box.getSize(new THREE.Vector3())
        current.controls.maxDistance = Math.max(20, Math.max(size.x, size.z) * 6)
        if (!current.initialized) frameTruck(current.camera, current.controls, size, current.box.getCenter(new THREE.Vector3()))
      }
      current.renderer.domElement.dataset.minZoomDistance = String(current.controls.minDistance)
      current.renderer.domElement.dataset.maxZoomDistance = String(current.controls.maxDistance)
      current.revision = data.revision; current.initialized = true
      highlight(selectedRef.current); current.controls.update()
      callbacks.current.onIssues?.(data.issues || []); setLoading(false)
    }
    update().catch(error => { if (live && error.name !== 'AbortError') { setLoading(false); callbacks.current.onFailure?.(error.message) } }).finally(() => callbacks.current.onLoading?.(requestId, false))
    return () => { cancel(); if (cancelRef?.current === cancel) cancelRef.current = null }
  }, [truckKey, sceneRevision, sessionId, truckId])
  React.useEffect(() => {
    if (runtime.current) runtime.current.lightMode.value = ['off', 'low', 'high'].indexOf(lightMode)
    highlight(selectedRef.current)
    setMarkerChoices(null)
  }, [selectedAccessoryId, selectedVehicleId, selectedMarker, markerVisibility, lightMode, truckKey])
  return <><div ref={host} className="three-host" aria-label="Interactive truck model. Drag to orbit and scroll to zoom."/>{markerChoices && <div className="marker-picker" role="dialog" aria-label="Choose attachment point" style={{ left: markerChoices.x, top: markerChoices.y }}><div className="marker-picker-heading"><span>Choose attachment point</span><button aria-label="Close attachment chooser" onClick={() => setMarkerChoices(null)}>×</button></div><div className="marker-picker-options">{markerChoices.points.map((point, index) => <button key={index} onClick={() => { setMarkerChoices(null); callbacks.current.onPick?.(point) }}>{markerLabel(point)}</button>)}</div></div>}{loading && !onLoading && <div className="scene-wait"><span className="loading-pulse"/>ASSEMBLING SAVE GEOMETRY</div>}</>
}
