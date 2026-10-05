import React from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource/barlow-condensed/latin-500.css'
import '@fontsource/barlow-condensed/latin-600.css'
import '@fontsource/barlow-condensed/latin-700.css'
import '@fontsource/barlow-condensed/latin-800.css'
import '@fontsource/ibm-plex-sans/latin-400.css'
import '@fontsource/ibm-plex-sans/latin-500.css'
import '@fontsource/ibm-plex-sans/latin-600.css'
import '@fontsource/ibm-plex-sans/latin-700.css'
import '@fontsource/ibm-plex-mono/latin-400.css'
import '@fontsource/ibm-plex-mono/latin-500.css'
import '@fontsource/ibm-plex-mono/latin-600.css'
import { AlertTriangle, ArrowLeftRight, Check, ChevronDown, ChevronRight, CircleHelp, Clock3, Cloud, Cpu, Disc3, Eye, Filter, History, Layers3, Move3D, PanelLeftClose, Plus, RotateCcw, Save, Search, Settings2, SlidersHorizontal, Truck, Undo2, Redo2, RefreshCw, Container, X } from 'lucide-react'
import LoadingProgress from './loading-progress.jsx'
import { paintHex, paintRgb } from './paint-color.js'
import { cachedThumbnail, cacheModel, cachedModel, clearModelCache, queuePreview } from './preview-cache.js'
import './style.css'

const GarageScene = React.lazy(() => import('./scene.jsx'))
const AnimatedPartPreview = React.lazy(() => import('./catalog-preview.jsx').then(module => ({ default: module.AnimatedPartPreview })))

async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...options.headers } })
  const raw = await response.text()
  let data
  try { data = raw ? JSON.parse(raw) : {} } catch { throw new Error(`Request returned invalid JSON (${response.status})`) }
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`)
  return data
}
const send = (path, body = {}, options = {}) => api(path, { ...options, method: 'POST', body: JSON.stringify(body) })
const pretty = (s = '') => s.replaceAll('_', ' ').replace(/\b\w/g, c => c.toUpperCase())
const brandLabel = value => pretty(String(value || '').replace(/[./\\_-]+/g, ' '))
const friendlyCategories = { toyseat: 'Seat accessories', codrv_seat: 'Passenger seat', cabin: 'Cabin', f_tire: 'Front tires', front_tire: 'Front tires', front_tires: 'Front tires', head_light: 'Headlights', headlights: 'Headlights', r_grill: 'Roof lightbars', f_grill: 'Front grille', front_grill: 'Front grille', f_bumper: 'Front bumper', front_bumper: 'Front bumper', roof_lightbar: 'Roof lightbar', roof_lights: 'Roof lights', mirror: 'Mirrors', mirrors: 'Mirrors', engine: 'Engine', transmission: 'Transmission', chassis: 'Chassis', wheel: 'Wheels', wheels: 'Wheels' }
const friendlyCategory = value => friendlyCategories[String(value || '').toLowerCase()] || pretty(value || 'Accessory')
const friendlySlot = value => { const name = String(value || '').replace(/^slot_/i, ''); return /^\d+$/.test(name) ? `Mount point ${Number(name) + 1}` : friendlyCategory(name) }
const profileId = save => save.profileId || String(save.id || '').split('/').slice(0, 2).join('/') || save.profile
const dateLabel = value => value ? new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : 'Date unavailable'

const accessoryKey = part => part ? JSON.stringify([part.vehicleId, part.id ?? part.accessoryId]) : ''

function App() {
  const [status, setStatus] = React.useState(null), [saves, setSaves] = React.useState([]), [state, setState] = React.useState(null), [catalog, setCatalog] = React.useState([]), [catalogLoading, setCatalogLoading] = React.useState(true)
  const [guideOpen, setGuideOpen] = React.useState(() => localStorage.getItem('yard.guideSeen') !== 'true')
  const vehiclePicker = React.useRef(null)
  const [selectedProfile, setSelectedProfile] = React.useState(''), [selectedSaveId, setSelectedSaveId] = React.useState('')
  const [error, setError] = React.useState(''), [notice, setNotice] = React.useState(''), [busy, setBusy] = React.useState(''), [mode, setMode] = React.useState('replace'), [sceneIssues, setSceneIssues] = React.useState([])
  const [category, setCategory] = React.useState('all'), [query, setQuery] = React.useState(''), [brand, setBrand] = React.useState('all'), [selected, setSelected] = React.useState(''), [chosenSlot, setChosenSlot] = React.useState('')
  const [mountPoint, setMountPoint] = React.useState(null), [selectedMarker, setSelectedMarker] = React.useState(null)
  const [settings, setSettings] = React.useState(false), [gamePath, setGamePath] = React.useState(''), [profilesPath, setProfilesPath] = React.useState(''), [decryptorPath, setDecryptorPath] = React.useState(''), [toolPath, setToolPath] = React.useState(''), [cachePath, setCachePath] = React.useState('')
  const [catalogOpen, setCatalogOpen] = React.useState(true), [historyOpen, setHistoryOpen] = React.useState(false), [paints, setPaints] = React.useState([]), [paintsLoading, setPaintsLoading] = React.useState(false)
  const [lightMode, setLightMode] = React.useState('off'), [markerVisibility, setMarkerVisibility] = React.useState('all')
  const [showDuplicates, setShowDuplicates] = React.useState(() => localStorage.getItem('yard.showDuplicates') === 'true')
  const [catalogLimit, setCatalogLimit] = React.useState(180)
  const [assetVersion, setAssetVersion] = React.useState(0)
  const [loadingJobs, setLoadingJobs] = React.useState([]), [sceneLoading, setSceneLoading] = React.useState(null)
  const [advanced, setAdvanced] = React.useState(() => localStorage.getItem('yard.advanced') === 'true')
  const sceneCancel = React.useRef(null), truckSelectRequest = React.useRef(null), truckSelectSequence = React.useRef(0)
  const reportError = React.useCallback(message => setError(message), [])
  const activePart = state?.truck?.accessories?.find(a => accessoryKey(a) === selected && (!selectedMarker?.vehicleId || a.vehicleId === selectedMarker.vehicleId)) || state?.truck?.accessories?.find(a => !selectedMarker?.vehicleId || a.vehicleId === selectedMarker.vehicleId)
  const categories = React.useMemo(() => [...new Set([...catalog, ...(state?.truck?.accessories || [])].map(item => item.category).filter(Boolean))].sort(), [catalog, state?.truck?.accessories])
  const brands = React.useMemo(() => [...new Set(catalog.map(item => item.brand).filter(Boolean))].sort(), [catalog])
  const profiles = [...new Map(saves.map(save => [profileId(save), { id: profileId(save), name: save.profile || 'Profile' }])).values()]
  const profileSaves = saves.filter(save => profileId(save) === selectedProfile).sort((a, b) => new Date(b.modified || b.created || 0) - new Date(a.modified || a.created || 0))
  const activeSave = saves.find(save => save.id === state?.saveId)
  const selectedVehicleId = selectedMarker?.vehicleId || mountPoint?.vehicleId || activePart?.vehicleId || state?.truck?.id
  const activeSection = state?.truck?.sections?.find(section => section.id === selectedVehicleId) || state?.truck
  const sectionAccessories = state?.truck?.accessories?.filter(part => (part.vehicleId || state.truck.id) === selectedVehicleId) || []
  const paintPart = sectionAccessories.find(part => part.category === 'paint_job')
  const previewCab = sectionAccessories.find(part => part.category === (state.truck.kind === 'trailer' ? 'body' : 'cabin'))
  const partLabel = part => paints.find(item => item.path === part.dataPath)?.name || catalog.find(item => item.path === part.dataPath)?.name || friendlyCategory(part.category || part.type)

  const applyState = React.useCallback(data => {
    setState(data)
    setSelected(current => {
      const parts = data?.truck?.accessories || [], owner = (current ? JSON.parse(current)[0] : null) || data?.truck?.id
      const edited = parts.find(part => part.id === data.editedAccessoryId && (part.vehicleId || data.truck.id) === (data.editedVehicleId || owner))
      return accessoryKey(edited || parts.find(part => accessoryKey(part) === current) || parts[0])
    })
  }, [])
  const withProgress = React.useCallback(async (label, task) => {
    const id = crypto.randomUUID()
    setLoadingJobs(current => [...current, { id, label, startedAt: Date.now() }])
    try { return await task(id) }
    finally { setLoadingJobs(current => current.filter(job => job.id !== id)) }
  }, [])
  const onSceneLoading = React.useCallback((id, loading) => {
    setSceneLoading(current => loading ? { id, label: 'Preparing vehicle preview', startedAt: Date.now() } : current?.id === id ? null : current)
  }, [])
  const refresh = React.useCallback(async () => {
    const [next, list] = await withProgress('Finding game folders and saves', () => Promise.all([api('/api/status'), api('/api/saves')])); setStatus(next); setSaves(list)
    if (next.gamePath) setGamePath(next.gamePath)
    if (next.profilesPath) setProfilesPath(next.profilesPath)
    if (next.decryptorPath) setDecryptorPath(next.decryptorPath)
    if (next.toolPath) setToolPath(next.toolPath)
    if (next.cachePath) setCachePath(next.cachePath)
    if (next.cacheMigrationRequired) {
      applyState(null); setCatalog([]); setCatalogLoading(false)
      return
    }
    if (next.session) applyState(next.session)
    else applyState(null)
    setCatalogLoading(true)
    // Resolve the selected save's mod sources before importing its catalog.
    try { setCatalog(next.ready && next.session ? await withProgress('Loading parts catalog', id => api(`/api/catalog?requestId=${id}`)) : []) } finally { setCatalogLoading(false) }
  }, [applyState, withProgress])
  React.useEffect(() => { refresh().catch(e => setError(e.message)) }, [refresh])
  React.useEffect(() => { if (!notice) return; const id = setTimeout(() => setNotice(''), 3600); return () => clearTimeout(id) }, [notice])
  React.useEffect(() => setCatalogLimit(180), [query, category, brand, Boolean(chosenSlot), showDuplicates])
  React.useEffect(() => { setSelectedMarker(null); setChosenSlot(''); setMountPoint(null) }, [state?.sessionId, state?.truck?.id])
  React.useEffect(() => {
    if (!state?.truck) return
    if (chosenSlot) {
      const markerKey = selectedMarker ? accessoryKey(selectedMarker) : selected
      const edited = state.editedVehicleId === selectedMarker?.vehicleId
        ? state.truck.accessories.find(part => part.vehicleId === state.editedVehicleId && part.id === state.editedAccessoryId && part.fields?.slot_name !== undefined && part.fields?.slot_hookup !== undefined)
        : null
      const owner = state.truck.accessories.find(part => accessoryKey(part) === markerKey) || edited
      const slot = owner?.slots?.find(slot => slot.name === chosenSlot)
      if (owner?.fields?.slot_name === undefined || owner?.fields?.slot_hookup === undefined) {
        // Undo can remove a copied owner. Require a fresh pick instead of guessing another addon.
        setSelectedMarker(null); setChosenSlot(''); setMountPoint(null); setMode('replace')
        setCategory(activePart?.category || 'all')
        return
      }
      if (selectedMarker && selectedMarker.accessoryId !== owner.id) setSelectedMarker({ ...selectedMarker, accessoryId: owner.id })
      if (selected !== accessoryKey(owner)) setSelected(accessoryKey(owner))
      setMode(slot?.hookup ? 'replace' : 'add')
    } else if (selectedMarker?.kind === 'part') {
      const parts = state.truck.accessories.filter(part => part.category === selectedMarker.category && part.vehicleId === selectedMarker.vehicleId)
      const fitted = parts.find(part => part.id === state.editedAccessoryId) || parts.find(part => part.id === selectedMarker.accessoryId) || parts[0]
      if (fitted) {
        if (selectedMarker.accessoryId !== fitted.id) setSelectedMarker({ ...selectedMarker, accessoryId: fitted.id })
        setSelected(accessoryKey(fitted)); setMountPoint(null); setMode('replace')
      } else {
        const empty = selectedMarker.accessoryId ? { ...selectedMarker, accessoryId: null } : selectedMarker
        if (empty !== selectedMarker) setSelectedMarker(empty)
        setMountPoint(empty); setMode('add')
      }
    }
  }, [state?.revision, chosenSlot, selected, selectedMarker?.vehicleId, selectedMarker?.accessoryId, selectedMarker?.kind, selectedMarker?.category])
  React.useEffect(() => { localStorage.setItem('yard.advanced', String(advanced)) }, [advanced])
  React.useEffect(() => { localStorage.setItem('yard.showDuplicates', String(showDuplicates)) }, [showDuplicates])
  React.useEffect(() => {
    if (state?.saveId) setSelectedSaveId(state.saveId)
    const save = saves.find(item => item.id === state?.saveId)
    if (save) setSelectedProfile(profileId(save))
  }, [state?.saveId, saves])
  React.useEffect(() => {
    if (profiles.length && !profiles.some(profile => profile.id === selectedProfile)) setSelectedProfile(profileId(activeSave || saves[0]))
  }, [profiles.length, selectedProfile, activeSave?.id, saves])
  const run = async (label, task) => {
    setBusy(label); setError('')
    try { const result = await task(); if (result?.trucks) applyState(result); return result }
    catch (e) { if (e.name !== 'AbortError') setError(e.message); return null }
    finally { setBusy('') }
  }
  const revisionGuard = () => state ? { sessionId: state.sessionId, revision: state.revision } : {}
  const rebuildCache = () => run('Rebuilding asset cache', async () => {
    sceneCancel.current?.()
    await clearModelCache(true)
    await withProgress('Rebuilding asset cache', id => send(`/api/rebuild-cache?requestId=${id}`, { accepted: true }))
    setAssetVersion(value => value + 1)
    await refresh()
    setNotice('Asset cache rebuilt')
  })
  const requestModel = React.useCallback(async (path, signal) => {
    signal.throwIfAborted()
    if (path.startsWith('[')) {
      // Paint previews share the selected part's cached geometry.
      const [cabPath, look, variant, paintPath] = JSON.parse(path)
      const cabKey = JSON.stringify([cabPath, look, variant])
      let cab = cachedModel(cabKey)
      if (!cab) {
        cab = await requestModel(`${cabPath}?${new URLSearchParams({ ...(look ? { look } : {}), ...(variant ? { variant } : {}) })}`, signal)
        cacheModel(cabKey, cab)
      }
      const paint = await requestModel(`${paintPath}?${new URLSearchParams({ preview: '1', accessoryPath: cabPath })}`, signal)
      return { ...cab, paintPreview: true, pieces: cab.pieces.map(piece => piece.material?.paintable ? { ...piece, material: { ...piece.material, ...paint.material } } : piece) }
    }
    const [definitionPath, parameters = ''] = path.split('?')
    const requestId = crypto.randomUUID()
    const cancel = () => { send('/api/cancel-model', { requestId }).catch(error => reportError(error.message)) }
    signal.addEventListener('abort', cancel, { once: true })
    try { return await api(`/api/${new URLSearchParams(parameters).get('preview') === '1' ? 'paint' : 'model'}?path=${encodeURIComponent(definitionPath)}&requestId=${requestId}&${parameters}`, { signal }) }
    finally { signal.removeEventListener('abort', cancel) }
  }, [reportError])
  const loadModel = React.useCallback((path, signal) => {
    const cached = cachedModel(path)
    if (cached) return Promise.resolve(cached)
    return queuePreview(async currentSignal => {
      const existing = cachedModel(path)
      if (existing) return existing
      const model = await requestModel(path, currentSignal)
      if (currentSignal?.aborted) throw new DOMException('Preview cancelled', 'AbortError')
      cacheModel(path, model)
      return model
    }, signal, true)
  }, [requestModel])
  const loadThumbnail = React.useCallback(async (path, signal, width, height) => {
    const key = status?.previewVersion ? new URL(`/__catalog_preview/${encodeURIComponent(status.previewVersion)}/${encodeURIComponent(path)}?size=${width}x${height}&render=5`, location.origin).href : null
    const preview = key ? await cachedThumbnail(key) : null
    if (signal.aborted) throw new DOMException('Preview cancelled', 'AbortError')
    if (preview) return preview
    return queuePreview(async currentSignal => {
      let model = cachedModel(path)
      if (!model) {
        model = await requestModel(path, currentSignal)
        if (currentSignal.aborted) throw new DOMException('Preview cancelled', 'AbortError')
        cacheModel(path, model)
      }
      const { renderModelThumbnail } = await import('./catalog-preview.jsx')
      currentSignal.throwIfAborted()
      return renderModelThumbnail(model, currentSignal, width, height, key)
    }, signal)
  }, [status?.previewVersion, requestModel])
  const loadSave = id => {
    if (state?.dirty && !window.confirm('This save has unsaved changes. Discard them and open another save?')) return
    return run('Opening save', async () => {
      sceneCancel.current?.()
      const next = await withProgress('Opening save', requestId => send(`/api/load?requestId=${requestId}`, { saveId: id })); applyState(next)
      clearModelCache(); setAssetVersion(value => value + 1)
      const save = saves.find(item => item.id === id)
      if (save) { setSelectedProfile(profileId(save)); setSelectedSaveId(id) }
      setCatalogLoading(true)
      try {
        const [updatedStatus, updatedCatalog] = await Promise.all([api('/api/status'), withProgress('Loading parts catalog', requestId => api(`/api/catalog?requestId=${requestId}`))])
        setStatus(updatedStatus); setCatalog(updatedCatalog)
      } finally { setCatalogLoading(false) }
      setNotice('Save opened'); return next
    })
  }
  const selectProfile = id => { setSelectedProfile(id); setSelectedSaveId('') }
  const selectTruck = id => {
    vehiclePicker.current?.removeAttribute('open')
    sceneCancel.current?.(); truckSelectRequest.current?.abort()
    const controller = new AbortController(), sequence = ++truckSelectSequence.current
    truckSelectRequest.current = controller
    return run('Switching vehicle', async () => {
      const next = await send('/api/select', { ...revisionGuard(), truckId: id }, { signal: controller.signal })
      return sequence === truckSelectSequence.current ? next : null
    })
  }
  const edit = body => { sceneCancel.current?.(); return run('Applying change', () => send('/api/edit', { ...revisionGuard(), truckId: selectedVehicleId, ...body })) }
  const save = () => run('Writing save', async () => {
    const currentStatus = await api('/api/status')
    setStatus(currentStatus)
    if (currentStatus.gameRunning && !window.confirm('ETS2 is running and may overwrite your edits. Load the edited save in ETS2 before saving again in game. Save changes anyway?')) return
    const result = await send('/api/save', revisionGuard())
    applyState(result.state); setNotice(`Saved. Backup: ${result.backupPath}`); return result.state
  })
  const history = (direction, steps = 1) => { sceneCancel.current?.(); return run(direction === 'undo' ? 'Undoing' : 'Redoing', () => send(`/api/${direction}`, { ...revisionGuard(), steps })) }
  React.useEffect(() => {
    const onKey = e => {
      if (status?.cacheMigrationRequired) return
      const target = e.target
      if (target instanceof HTMLElement && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))) return
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z' && !e.shiftKey) { e.preventDefault(); if (state?.canUndo) history('undo') }
      if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === 'y' || (e.key.toLowerCase() === 'z' && e.shiftKey))) { e.preventDefault(); if (state?.canRedo) history('redo') }
      if (e.key === 'Escape') { setSettings(false); setHistoryOpen(false); setError('') }
    }
    window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey)
  }, [state?.canUndo, state?.canRedo, status?.cacheMigrationRequired])
  React.useEffect(() => {
    if (!state?.dirty) return
    const before = e => { e.preventDefault(); e.returnValue = '' }
    window.addEventListener('beforeunload', before); return () => window.removeEventListener('beforeunload', before)
  }, [state?.dirty])

  React.useEffect(() => {
    if (category !== 'paint_job' || !activeSection?.brand) return
    const controller = new AbortController()
    setPaints([])
    setPaintsLoading(true)
    api(`/api/paints?brand=${encodeURIComponent(activeSection.brand)}`, { signal: controller.signal }).then(setPaints).catch(error => { if (error.name !== 'AbortError') reportError(error.message) }).finally(() => { if (!controller.signal.aborted) setPaintsLoading(false) })
    return () => controller.abort()
  }, [category, activeSection?.brand, assetVersion])
  const matching = React.useMemo(() => (category === 'paint_job' ? paints : catalog).filter(item => {
    if (item.suitableFor?.length) {
      const cabin = previewCab
      const unit = catalog.find(entry => entry.path === cabin?.dataPath)?.unitId
      if (unit && !item.suitableFor.includes(unit)) return false
    }
    const isHookup = item.category?.toLowerCase() === 'hookup'
    return (chosenSlot || category === 'hookup' ? isHookup : !isHookup) && (chosenSlot || (category === 'all' || item.category === category) && (brand === 'all' || item.brand === brand)) && `${item.name} ${item.category} ${advanced ? `${item.brand} ${item.path} ${item.unitId}` : brandLabel(item.brand)}`.toLowerCase().includes(query.toLowerCase())
  }), [catalog, paints, chosenSlot, category, brand, query, advanced, state?.truck?.accessories, previewCab])
  const filtered = React.useMemo(() => {
    if (showDuplicates) return matching
    const unique = new Map()
    for (const item of matching) {
      const key = item.duplicateKey || item.path
      const existing = unique.get(key)
      const rank = item.path === activePart?.dataPath ? 2 : item.brand === activeSection?.brand ? 1 : 0
      const previousRank = existing?.path === activePart?.dataPath ? 2 : existing?.brand === activeSection?.brand ? 1 : 0
      if (!existing || rank > previousRank) unique.set(key, item)
    }
    return [...unique.values()]
  }, [matching, showDuplicates, activePart?.dataPath, activeSection?.brand])
  const shownIssues = [...new Set([...(state?.issues || []), ...sceneIssues])]
  const applyDefinition = item => {
    if (!state?.truck) return
    if (item.category === 'paint_job' && paintPart) { setSelected(accessoryKey(paintPart)); edit({ op: 'paint', accessoryId: paintPart.id, dataPath: item.path }); return }
    if (chosenSlot && (mode === 'add' || mode === 'replace')) {
      if (activePart?.fields?.slot_name === undefined || activePart?.fields?.slot_hookup === undefined || selectedMarker && accessoryKey(activePart) !== accessoryKey(selectedMarker)) return
      edit({ op: 'hookup', accessoryId: activePart.id, slotName: chosenSlot, hookup: item.unitId }); return
    }
    if (mode === 'replace' && activePart) edit({ op: 'replace', accessoryId: activePart.id, dataPath: item.path })
    else if (mode === 'add') edit({ op: 'add', dataPath: item.path })
    else if (mode === 'duplicate' && activePart) edit({ op: 'duplicate', accessoryId: activePart.id, dataPath: item.path })
  }
  const saveConfig = () => {
    if (state?.dirty) { setError('Save your vehicle edits before changing folders.'); return }
    return run('Checking folders', async () => {
      const updated = await send('/api/config', { gamePath, profilesPath, decryptorPath, toolPath, cachePath }); setStatus(updated); applyState(updated.session || null); clearModelCache(); setAssetVersion(value => value + 1)
      setGamePath(updated.gamePath || gamePath); setProfilesPath(updated.profilesPath || profilesPath); setDecryptorPath(updated.decryptorPath || decryptorPath); setToolPath(updated.toolPath || toolPath); setCachePath(updated.cachePath)
      setSettings(false); setNotice(updated.message || 'Folders updated')
      if (updated.cacheMigrationRequired) { setCatalog([]); setCatalogLoading(false); return null }
      setCatalogLoading(true)
      try { const [list, defs] = await Promise.all([api('/api/saves'), api('/api/catalog')]); setSaves(list); setCatalog(defs) }
      finally { setCatalogLoading(false) }
      return null
    })
  }

  const closeSettings = () => {
    const changed = Object.entries({ gamePath, profilesPath, decryptorPath, toolPath, cachePath }).some(([key, value]) => value.trim() !== (status?.[key] || ''))
    if (changed) {
      if (window.confirm('Save your folder changes before closing? Choose Cancel to keep editing.')) saveConfig()
      return
    }
    setSettings(false)
  }

  return <div className="app-shell">
    <header className="topbar">
      <div className="brand-lockup"><span className="brand-mark"><Truck size={19} strokeWidth={1.8}/></span><span className="brand-word">S Garage <span>/</span></span><span className="brand-caption">ETS2</span></div>
      <div className="top-divider" />
      <div className="source-selects">
        <div className="profile-select"><span className="eyebrow">Profile</span><label><select disabled={!!busy} aria-label="Select profile" value={selectedProfile} onChange={e => selectProfile(e.target.value)}><option value="">Choose profile…</option>{profiles.map(profile => <option key={profile.id} value={profile.id}>{profile.name}</option>)}</select><ChevronDown size={14}/></label></div>
        <div className="save-select"><span className="eyebrow">Save file</span><label><select disabled={!!busy} aria-label="Select save" value={profileSaves.some(save => save.id === selectedSaveId) ? selectedSaveId : ''} onChange={e => e.target.value && loadSave(e.target.value)}><option value="">{profileSaves.length ? 'Choose a save…' : 'No saves in profile'}</option>{profileSaves.map(save => <option key={save.id} value={save.id}>{save.name} · {dateLabel(save.modified || save.created)}</option>)}</select><ChevronDown size={14}/></label></div>
        <button className="icon-button refresh-saves" aria-label="Refresh saves" title="Refresh profiles and saves" disabled={!!busy} onClick={() => run('Refreshing saves', async () => { const list = await api('/api/saves'); setSaves(list); setNotice(`Save list refreshed. ${list.length} saves found.`) })}><RefreshCw size={16} className={busy === 'Refreshing saves' ? 'refresh-spinning' : ''}/></button>
      </div>
      <div className="top-meta"><span className={`live-dot ${status?.ready ? 'ready' : ''}`} /><span>{status?.ready ? 'Save scanner ready' : 'Checking local files'}</span><span className="meta-sep">·</span><span>{saves.length} saves</span></div>
      <button className={`advanced-toggle ${advanced ? 'active' : ''}`} aria-pressed={advanced} onClick={() => setAdvanced(value => !value)} title="Show internal paths and save fields"><SlidersHorizontal size={15}/><span>Advanced view</span></button>
      <button className="icon-button settings-button" onClick={() => setSettings(true)} aria-label="Settings"><Settings2 size={17}/></button>
      <button className="save-button" onClick={save} disabled={!state?.dirty || !!busy}><Save size={15}/><span>{busy === 'Writing save' ? 'Saving…' : 'Save changes'}</span>{state?.dirty && <i/>}</button>
    </header>

    <main className={`workspace ${loadingJobs.length || sceneLoading ? 'workspace-loading' : ''} ${catalogOpen ? '' : 'catalog-is-closed'}`}>
      <aside className="installed-panel">
        <div className="panel-heading"><div><div className="eyebrow">Garage</div><h1>Installed parts</h1></div><span className="count-pill">{state?.truck?.accessories?.length ?? '—'}</span></div>
        {state?.trucks?.length > 0 && <details className="vehicle-picker" ref={vehiclePicker} key={state.sessionId} onKeyDown={event => { if (event.key === 'Escape') { event.currentTarget.removeAttribute('open'); event.currentTarget.querySelector('summary').focus() } }}>
          <summary aria-label="Choose truck or trailer">{state.truck?.kind === 'trailer' ? <Container size={16}/> : <Truck size={16}/>}<span>{state.truck?.name}{state.truck?.sectionCount > 1 && ` · ${state.truck.sectionCount} sections`}{state.truck?.plate && ` · ${state.truck.plate}`}</span><ChevronDown size={14}/></summary>
          <div className="vehicle-menu">
            <details className="vehicle-group" open><summary><Truck size={15}/> Trucks <span>{state.trucks.length}</span></summary><div>{state.trucks.map(vehicle => <button key={vehicle.id} className={state.truck?.id === vehicle.id ? 'selected' : ''} aria-pressed={state.truck?.id === vehicle.id} disabled={!!busy} onClick={() => selectTruck(vehicle.id)}><span>{vehicle.name}</span><small>{vehicle.plate || 'Owned truck'}</small>{state.truck?.id === vehicle.id && <Check size={14}/>}</button>)}</div></details>
            <details className="vehicle-group"><summary><Container size={15}/> Trailers <span>{state.trailers?.length ?? '?'}</span></summary><div>{state.trailers?.map(vehicle => <button key={vehicle.id} className={state.truck?.id === vehicle.id ? 'selected' : ''} aria-pressed={state.truck?.id === vehicle.id} disabled={!!busy} onClick={() => selectTruck(vehicle.id)}><span>{vehicle.name}{vehicle.sectionCount > 1 && ` · ${vehicle.sectionCount} sections`}</span><small>{vehicle.plate || 'Owned trailer'}</small>{state.truck?.id === vehicle.id && <Check size={14}/>}</button>)}{!state.trailers?.length && <p>{state.trailers ? 'No owned trailers in this save.' : 'Restart the local S Garage server to load trailers, then reload this page.'}</p>}</div></details>
          </div>
        </details>}
        {state?.truck && <div className="truck-info"><span className="truck-badge">{state.truck.kind === 'trailer' ? <Container size={21}/> : <Truck size={21}/>}</span><div><b>{state.truck.name}</b><small>{advanced && state.truck.brand ? `${state.truck.brand} · ` : ''}{state.truck.plate || (state.truck.kind === 'trailer' ? 'Trailer ready' : 'Truck ready')}</small></div><span className="truck-angle">↗</span></div>}
        <div className="part-list-title"><span>Installed components</span><span>{state?.truck?.accessories?.length || 0}</span></div>
        <div className="part-list">{state?.truck?.accessories?.map((part, index) => <button className={`part-row ${accessoryKey(activePart) === accessoryKey(part) ? 'selected' : ''}`} key={accessoryKey(part)} onClick={() => { setSelectedMarker(null); setSelected(accessoryKey(part)); setChosenSlot(''); setMountPoint(null); setMode('replace'); setBrand('all'); setQuery(''); setCategory(part.category || 'all') }}>
          <span className="part-icon">{part.category?.toLowerCase().includes('wheel') || part.category?.toLowerCase().includes('tyre') ? <Disc3 size={17}/> : part.category?.toLowerCase().includes('engine') ? <Cpu size={17}/> : <Layers3 size={17}/>}</span><span className="part-copy"><b>{partLabel(part)}</b><small>{state.truck.sections?.length > 1 && `Section ${part.section} \u00b7 `}{friendlyCategory(part.category || part.type)}</small></span><ChevronRight size={14} className="part-arrow"/>
        </button>)}</div>
        {activePart && <section className="part-detail" key={accessoryKey(activePart)}><div className="detail-overline"><span>{state.truck.sections?.length > 1 ? `Section ${activePart.section} \u00b7 ` : ''}{advanced ? 'Selected component' : 'Selected part'}</span><button title="Remove component" aria-label="Remove component" onClick={() => edit({ op: 'remove', accessoryId: activePart.id })}><X size={15}/></button></div><h2>{partLabel(activePart)}</h2>{advanced && <p className="path-text">{activePart.dataPath}</p>}
          <div className="detail-metrics"><div><span>Category</span><b>{friendlyCategory(activePart.category || activePart.type)}</b></div><div><span>Instances</span><b>{state?.truck?.accessoryCount ?? state?.truck?.accessories?.length}</b></div></div>
          {activePart.category === 'paint_job' && <PaintControls part={activePart} busy={!!busy} edit={edit} onFailure={reportError}/>}
          {activePart.slots?.length > 0 && <div className="slot-block"><div className="slot-heading"><span>Attachment points</span><span>{activePart.slots.length}</span></div>{activePart.slots.map((slot, index) => { const hookup = catalog.find(item => item.unitId === slot.hookup); return <div className="slot-entry" key={`${slot.name}:${index}`}><button className={`slot-row ${chosenSlot === slot.name ? 'slot-chosen' : ''}`} onClick={() => { setSelectedMarker({ vehicleId: activePart.vehicleId, section: activePart.section, accessoryId: activePart.id, name: slot.name, kind: 'hookup' }); setChosenSlot(slot.name); setMountPoint(null); setMode('add'); if (category !== 'hookup') { setCategory('hookup'); setBrand('all'); setQuery('') } }}><span className="slot-lamp"/><span>{friendlySlot(slot.name)}</span><code>{advanced ? slot.hookup || 'Empty' : hookup?.name || (slot.hookup ? 'Installed' : 'Empty')}</code></button><button className="slot-remove" aria-label={`Remove attachment from ${friendlySlot(slot.name)}`} title="Remove this attachment. Undo is available." onClick={() => edit({ op: 'hookup', accessoryId: activePart.id, slotName: slot.name, index, hookup: '' })}><X size={13}/></button></div>})}</div>}
          {advanced && Object.keys(activePart.fields || {}).length > 0 && <details className="field-editor"><summary><SlidersHorizontal size={13}/> Raw instance fields <ChevronDown size={13}/></summary><div className="fields-scroll">{Object.entries(activePart.fields).filter(([key]) => !/^(id|accessory|parent|_)/i.test(key)).map(([key, value]) => <label key={key}><span>{pretty(key)}</span><input defaultValue={value} onBlur={e => e.target.value !== value && edit({ op: 'fields', accessoryId: activePart.id, fields: { [key]: e.target.value } })}/></label>)}</div></details>}
          <div className="component-actions"><button title="Duplicate installed part" onClick={() => edit({ op: 'duplicate', accessoryId: activePart.id })}><CopyIcon/> DUPLICATE</button><button title="Replace from catalog" onClick={() => { setMode('replace'); setCatalogOpen(true) }}><ArrowLeftRight size={14}/> REPLACE</button></div>
        </section>}
        {!state && <div className="empty-state"><Truck size={30}/><b>Choose a save to open the workshop</b><span>S Garage reads your local profile and save files.</span></div>}
        <div className="aside-footer"><span className="small-status-dot"/><span>{status?.gameRunning ? 'Game is running' : status?.ready ? 'Local save linked' : 'Save path not set'}</span><button onClick={() => setSettings(true)}>Folders <ChevronRight size={12}/></button></div>
      </aside>

      <section className="viewport-panel">
        <div className="viewport-header"><div><span className="eyebrow">{state?.truck?.kind === 'trailer' ? 'Trailer model' : 'Truck model'}</span><h2>{state?.truck?.name || 'Truck inspection'}</h2>{advanced && activeSection?.brand && <span className="truck-make">{activeSection.brand}</span>}</div><div className="preview-controls">{paintPart && <button className="paint-open" onClick={() => { setSelected(accessoryKey(paintPart)); setSelectedMarker(null); setChosenSlot(''); setMountPoint(null); setCategory('paint_job'); setBrand(activeSection.brand); setQuery(''); setCatalogOpen(true) }}>Paint</button>}<label>Lights<select aria-label="Preview lights" value={lightMode} onChange={event => setLightMode(event.target.value)}><option value="off">Off</option><option value="low">Low</option><option value="high">High</option></select></label><label>Markers<select aria-label="Marker visibility" value={markerVisibility} onChange={event => setMarkerVisibility(event.target.value)}><option value="all">All</option><option value="selected">Selected only</option><option value="hidden">Hidden</option></select></label></div></div>
        <div className="scene-wrap">{state?.truck ? <React.Suspense fallback={<div className="scene-wait" role="status">Loading the 3D viewer...</div>}><GarageScene onLoading={onSceneLoading} lightMode={lightMode} markerVisibility={markerVisibility} key={`${state.sessionId}:${state.truck.id}`} truckKey={`${state.sessionId}:${state.truck.id}`} sceneRevision={state.revision} sessionId={state.sessionId} truckId={state.truck.id} cancelRef={sceneCancel} selectedVehicleId={activePart?.vehicleId} selectedAccessoryId={activePart?.id} selectedMarker={selectedMarker} markerLabel={point => `${state.truck.sections?.length > 1 ? `Section ${point.section} \u00b7 ` : ''}${point.kind === 'hookup' ? `${friendlyCategory(state.truck.accessories.find(part => part.id === point.accessoryId && part.vehicleId === point.vehicleId)?.category)} / ${friendlySlot(point.name)}` : friendlyCategory(point.category || point.name)}`} onPick={point => {
          setSelectedMarker(point.kind ? point : null)
          const part = state.truck.accessories.find(item => item.id === point.accessoryId && item.vehicleId === point.vehicleId)
          const nextCategory = point.kind === 'hookup' ? 'hookup' : part?.category || point.category || 'all'
          if (nextCategory !== category) { setCategory(nextCategory); setBrand('all'); setQuery('') }
          if (point.kind === 'hookup') { setSelected(accessoryKey(point)); setChosenSlot(point.name); setMountPoint(null); setMode('add') }
          else if (point.kind === 'part') { setChosenSlot(''); if (point.accessoryId) { setSelected(accessoryKey(point)); setMountPoint(null); setMode('replace') } else { setMountPoint(point); setMode('add') } }
          else if (point.accessoryId) { setSelected(accessoryKey(point)); setChosenSlot(''); setMountPoint(null); setMode('replace') }
        }} onFailure={reportError} onIssues={setSceneIssues} /></React.Suspense> : <div className="scene-empty"><div className="scan-glyph"><Truck size={39}/><span/></div><b>Waiting for a truck</b><p>Open a save to inspect the truck geometry from your game files.</p></div>}
          <div className="scene-vignette"/>{advanced && <div className="scene-label"><span className="scene-live"/> GEOMETRY STREAM <span className="scene-label-sep">·</span> MODEL DATA</div>}
          {!guideOpen && <LoadingProgress requests={[...loadingJobs, ...(sceneLoading ? [sceneLoading] : [])]}/>}
          {busy && !loadingJobs.length && !sceneLoading && <div className="scene-loading"><span className="loading-pulse"/>{busy}</div>}
        </div>
        {shownIssues.length > 0 && <div className="issue-strip"><AlertTriangle size={14}/><span>{advanced ? shownIssues.join(' · ') : `${shownIssues.length} preview issues. Enable Advanced view for details.`}</span></div>}
      </section>

      <aside className={`catalog-panel ${catalogOpen ? '' : 'catalog-collapsed'}`}>
        <div className="catalog-heading"><div><div className="eyebrow">PARTS DEPARTMENT / 03</div><h2>Catalog</h2></div><button className="icon-button" onClick={() => setCatalogOpen(!catalogOpen)} aria-label={catalogOpen ? 'Collapse catalog' : 'Expand catalog'} aria-expanded={catalogOpen}><PanelLeftClose size={16} style={{ transform: catalogOpen ? 'scaleX(-1)' : 'none' }}/></button></div>
        {catalogOpen && <>{category !== 'paint_job' && <div className="catalog-mode"><button className={mode === 'replace' ? 'active' : ''} onClick={() => { setMode('replace'); if (!chosenSlot) { setSelectedMarker(null); setChosenSlot(''); setMountPoint(null) } }}><ArrowLeftRight size={14}/> Replace</button><button className={mode === 'add' ? 'active' : ''} onClick={() => setMode('add')}><Plus size={15}/> Add</button><button className={mode === 'duplicate' ? 'active' : ''} onClick={() => { setSelectedMarker(null); setMode('duplicate'); setChosenSlot(''); setMountPoint(null) }}><CopyIcon/> Copy</button></div>}
          <label className="search-box"><Search size={16}/><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search parts, brands…"/><kbd>/</kbd></label>
          <div className="filter-row"><label><Filter size={13}/><select aria-label="Filter category" value={category} onChange={e => setCategory(e.target.value)}><option value="all">All categories</option>{categories.map(c => <option key={c} value={c}>{friendlyCategory(c)}</option>)}</select><ChevronDown size={12}/></label><label><select aria-label="Filter brand" disabled={category === 'paint_job'} value={category === 'paint_job' ? activeSection?.brand || brand : brand} onChange={e => setBrand(e.target.value)}><option value="all">All makes</option>{brands.map(b => <option key={b} value={b}>{brandLabel(b)}</option>)}</select><ChevronDown size={12}/></label></div>
          {(chosenSlot || mountPoint) && <div className="target-chip"><span className="slot-lamp"/> Target: {friendlySlot(chosenSlot || mountPoint?.name || 'Mount point')}<button aria-label="Clear selected attachment point" onClick={() => { setSelectedMarker(null); setChosenSlot(''); setMountPoint(null) }}><X size={12}/></button></div>}
          <div className="catalog-result-line"><span>{filtered.length.toLocaleString()} parts</span><label className="duplicates-toggle"><input type="checkbox" checked={showDuplicates} onChange={e => setShowDuplicates(e.target.checked)}/> Show duplicates</label></div>
          <div className="catalog-grid" key={JSON.stringify([assetVersion, category, query, brand, Boolean(chosenSlot), showDuplicates, previewCab?.dataPath, previewCab?.fields.look, previewCab?.fields.variant])}>{filtered.slice(0, catalogLimit).map((item, index) => <CatalogCard paused={!!busy || loadingJobs.length > 0 || catalogLoading || !!sceneLoading} key={item.path} item={item} index={index} advanced={advanced} previewPath={item.paintFields?.paint_job_mask && previewCab ? JSON.stringify([previewCab.dataPath, previewCab.fields.look || null, previewCab.fields.variant || null, item.path]) : item.path} onChoose={() => applyDefinition(item)} onFailure={reportError} loadModel={loadModel} loadThumbnail={loadThumbnail} />)}{filtered.length === 0 && <div className="no-results"><Search size={21}/><span>{!state ? 'Open a save to load its game parts.' : catalogLoading ? 'Loading the parts catalog...' : chosenSlot ? 'No hookup definitions match this search.' : category === 'paint_job' && paintsLoading ? 'Loading paint jobs...' : 'No parts match this filter.'}</span></div>}{filtered.length > catalogLimit && <button className="load-more" onClick={() => setCatalogLimit(limit => limit + 180)}>Show next {Math.min(180, filtered.length - catalogLimit)} parts <ChevronDown size={13}/></button>}</div>
          <div className="catalog-foot"><span><span className={`small-status-dot ${catalogLoading ? 'loading-dot' : ''}`}/>{catalogLoading ? 'IMPORTING GAME ASSETS' : !state ? 'WAITING FOR A SAVE' : 'CATALOG FROM GAME DATA'}</span><span>{filtered.length > catalogLimit ? `Showing ${catalogLimit} of ` : ''}{filtered.length}</span></div>
        </>}
      </aside>
    </main>

    <footer className="statusbar"><div className="history-actions"><button disabled={!state?.canUndo || !!busy} onClick={() => history('undo')} title="Undo (Ctrl+Z)"><Undo2 size={15}/> Undo</button><button disabled={!state?.canRedo || !!busy} onClick={() => history('redo')} title="Redo (Ctrl+Y)"><Redo2 size={15}/> Redo</button><span className="history-separator"/><button disabled={!state} onClick={() => setHistoryOpen(true)}><History size={13}/> History{advanced && ` ? ${state?.revision ?? 0}`}</button></div><div className="status-save"><span className={`dirty-marker ${state?.dirty ? 'is-dirty' : ''}`}/><span>{state?.dirty ? 'Unsaved changes' : state ? 'All changes saved' : 'No session'}</span>{activeSave && <><span className="history-separator"/><Clock3 size={13}/><span>{dateLabel(activeSave.modified || activeSave.created)}</span>{advanced && activeSave.format && <span>{activeSave.format}</span>}</>}</div><div className="status-right"><span><Cloud size={14}/> Local only</span><span className="history-separator"/><button onClick={() => setGuideOpen(true)}><CircleHelp size={14}/> Getting started</button><span className="history-separator"/><button onClick={() => setSettings(true)}>Folders</button></div></footer>
    {(error || notice) && <div role="status" className={`toast ${error ? 'toast-error' : ''}`}><span>{error || notice}</span><button onClick={() => { setError(''); setNotice('') }} aria-label="Dismiss message"><X size={15}/></button></div>}
    {historyOpen && <HistoryWindow state={state} busy={!!busy} history={history} onClose={() => setHistoryOpen(false)}/>}
    {status?.cacheMigrationRequired && <CacheRebuildNotice busy={!!busy} error={error} loadingRequests={loadingJobs} onAccept={rebuildCache}/>}
    {guideOpen && status && !status.cacheMigrationRequired && <GettingStarted loadingRequests={[...loadingJobs, ...(sceneLoading ? [sceneLoading] : [])]} onClose={() => { localStorage.setItem('yard.guideSeen', 'true'); setGuideOpen(false) }} onFolders={() => { localStorage.setItem('yard.guideSeen', 'true'); setGuideOpen(false); setSettings(true) }}/>}
    {settings && <div className="modal-backdrop" onMouseDown={e => e.target === e.currentTarget && closeSettings()}><section className="settings-modal" role="dialog" aria-modal="true" aria-labelledby="settings-title"><div className="modal-top"><div><div className="eyebrow">LOCAL CONNECTION</div><h2 id="settings-title">Game folders</h2></div><button className="icon-button" onClick={closeSettings} aria-label="Close settings"><X size={17}/></button></div><p className="modal-copy">Point S Garage at your Euro Truck Simulator 2 install and profile directory. Your save stays on this PC. Click Save folders to keep changes for the next launch.</p><label className="path-field"><span>GAME INSTALL DIRECTORY</span><input value={gamePath} onChange={e => setGamePath(e.target.value)} placeholder="C:\\Program Files (x86)\\Steam\\steamapps\\common\\Euro Truck Simulator 2"/></label><label className="path-field"><span>PROFILES DIRECTORY</span><input value={profilesPath} onChange={e => setProfilesPath(e.target.value)} placeholder="Documents\\Euro Truck Simulator 2\\profiles"/></label><label className="path-field"><span>CACHE FOLDER</span><input value={cachePath} onChange={e => setCachePath(e.target.value)} placeholder="Folder for imported game data"/></label><p className="modal-copy">Imported models and textures are stored here. Changing this folder rebuilds the cache as you browse. Existing files stay in the old folder. Settings stay in AppData\Local\ETS2Garage.</p><label className="path-field"><span>CONVERTERPIX TOOL</span><input value={toolPath} onChange={e => setToolPath(e.target.value)} placeholder="Path to converter_pix.exe"/></label><label className="path-field"><span>DECRYPTOR TOOL (OPTIONAL)</span><input value={decryptorPath} onChange={e => setDecryptorPath(e.target.value)} placeholder="Path to a compatible save decryptor executable"/></label><div className="detected-path"><span className={`small-status-dot ${status?.ready ? '' : 'off'}`}/><span>{status?.message || status?.toolPath || status?.decryptorPath || 'Waiting for folder scan'}</span></div><div className="modal-actions"><button className="text-button" onClick={() => setSettings(false)}>CANCEL</button><button className="save-button" onClick={saveConfig} disabled={!!busy}><Check size={15}/> Save folders</button></div></section></div>}
  </div>
}

function CacheRebuildNotice({ onAccept, busy, error, loadingRequests }) {
  const dialog = React.useRef(null)
  React.useEffect(() => { dialog.current.showModal() }, [])
  return <dialog ref={dialog} className="guide-window cache-rebuild-window" onCancel={event => event.preventDefault()} aria-labelledby="cache-rebuild-title" aria-describedby="cache-rebuild-copy" aria-busy={busy}>
    <div className="modal-top"><h2 id="cache-rebuild-title">Your asset cache needs rebuilding</h2></div>
    <p id="cache-rebuild-copy">S Garage now uses a new asset cache format. Accept to remove the old imported assets and load a fresh cache. This can take a few minutes on a hard disk.</p>
    <p>Your saves and settings stay intact. Models will rebuild as you open vehicles and browse parts.</p>
    <LoadingProgress requests={loadingRequests}/>
    {error && <p className="cache-rebuild-error" role="alert">{error}</p>}
    <div className="modal-actions"><button className="save-button" autoFocus disabled={busy} onClick={onAccept}><Check size={15}/>{busy ? 'Rebuilding cache...' : error ? 'Retry rebuild' : 'Accept and rebuild'}</button></div>
  </dialog>
}

function GettingStarted({ onClose, onFolders, loadingRequests }) {
  const dialog = React.useRef(null)
  React.useEffect(() => { dialog.current.showModal() }, [])
  return <dialog ref={dialog} className="guide-window" onCancel={onClose} aria-labelledby="guide-title">
    <div className="modal-top"><div><div className="eyebrow">GETTING STARTED</div><h2 id="guide-title">Bring your truck into S Garage</h2></div><button className="icon-button" onClick={onClose} aria-label="Close guide"><X size={17}/></button></div>
    <p>A profile is your ETS2 career, with its trucks, drivers and progress. Each save is a snapshot of that profile at a particular time. Choose a profile first, then the save you want to edit.</p>
    <LoadingProgress requests={loadingRequests}/>
    <div className="guide-cloud"><Cloud size={20}/><div><h3>Use a local profile</h3><p>S Garage only supports profiles with Steam Cloud disabled. Disable Steam Cloud for the profile you want to edit, then make a new manual save in ETS2.</p></div></div>
    <ol>
      <li><h3>Turn off Steam Cloud for your profile</h3><p>In ETS2's profile selection screen, select your profile, choose Edit, disable Use Steam Cloud and apply the change.</p><a href="https://www.youtube.com/watch?v=e2aYdREZX4M" target="_blank" rel="noreferrer">Watch the profile setup video <ChevronRight size={14}/></a><p className="guide-note">This video is for another tool, but explains the same local profile setup.</p></li>
      <li><h3>Create a separate manual save</h3><p>Load your profile in ETS2 and make a new manual save for your truck edits. Local profiles normally live in Documents\Euro Truck Simulator 2\profiles. If your saves are missing, check the profiles directory in Folders.</p></li>
      <li><h3>Refresh, choose a save and edit</h3><p>Click Refresh saves beside the save selector after making a new save in ETS2. Choose your profile and save, then select a truck or expand Trailers in the vehicle picker. Undo and redo let you revise your edits.</p></li>
      <li><h3>Save and load it in ETS2</h3><p>Click Save changes, then load that same save in ETS2 to see your truck in game. S Garage backs up the selected save before writing it. If ETS2 is running, load the edited save before saving again in game, or the game may overwrite your edits.</p></li>
    </ol>
    <div className="modal-actions"><button className="text-button" onClick={onFolders}>Check folders</button><button className="save-button" onClick={onClose}><Check size={15}/> Open garage</button></div>
  </dialog>
}

function HistoryWindow({ state, busy, history, onClose }) {
  const dialog = React.useRef(null)
  React.useEffect(() => { dialog.current.showModal() }, [])
  const entries = state?.history || [], position = state?.historyPosition || 0
  const vehicles = [...(state?.trucks || []), ...(state?.trailers || []).flatMap(vehicle => vehicle.sections?.length > 1 ? vehicle.sections.map(section => ({ ...section, name: `${vehicle.name} - Section ${section.section}` })) : [vehicle])]
  return <dialog ref={dialog} className="history-window" onCancel={onClose} aria-labelledby="history-title">
    <div className="modal-top"><h2 id="history-title">Edit history</h2><button className="icon-button" aria-label="Close history" onClick={onClose}><X size={18}/></button></div>
    <p>Changes across all trucks and trailers in this save, for the current session. Choose a change to undo it and every change after it.</p>
    <div className="history-list"><button disabled={!position || busy} onClick={() => history('undo', position)}><span>Opened save</span><small>Undo all {position} changes</small></button>
      {entries.map((entry, index) => <button key={`${entry.time}:${index}`} className={index >= position ? 'history-undone' : ''} disabled={busy} onClick={() => history(index < position ? 'undo' : 'redo', index < position ? position - index : index - position + 1)}>
        <span>{index + 1}. {entry.label}</span><small>{vehicles.find(vehicle => vehicle.id === entry.truckId)?.name} · {new Date(entry.time).toLocaleTimeString()} · {index < position ? `Undo ${position - index}` : `Redo ${index - position + 1}`}</small>
      </button>)}
    </div>{!entries.length && <p>No edits yet. Your changes will appear here.</p>}
    <div className="modal-actions"><button className="text-button" onClick={onClose}>Close</button></div>
  </dialog>
}

function PaintControls({ part, busy, edit, onFailure }) {
  const [settings, setSettings] = React.useState(null), [colors, setColors] = React.useState({})
  React.useEffect(() => {
    const controller = new AbortController()
    setSettings(null)
    api(`/api/paint?path=${encodeURIComponent(part.dataPath)}`, { signal: controller.signal }).then(data => setSettings(data.fields)).catch(error => { if (error.name !== 'AbortError') onFailure(error.message) })
    return () => controller.abort()
  }, [part.dataPath])
  React.useEffect(() => {
    if (settings) setColors(Object.fromEntries(['base_color', 'mask_r_color', 'mask_g_color', 'mask_b_color', 'flake_color', 'flip_color'].filter(key => settings[key]).map(key => [key, paintHex(part.fields[key] || settings[key])])))
  }, [settings, part.id, JSON.stringify(part.fields)])
  if (!settings) return <p className="paint-note">Loading paint settings…</p>
  const editable = Object.keys(colors).filter(key => settings[key.startsWith('mask_') ? key.replace('_color', '_locked') : key + '_locked'] !== 'true')
  const changed = editable.filter(key => colors[key] !== paintHex(part.fields[key] || settings[key]))
  return <div className="paint-controls"><h3>Paint colors</h3><p className="paint-note">Choose a paint job from the catalog, then apply your colors to preview them. Locked colors belong to the selected design.</p>
    {Object.entries(colors).map(([key, color]) => <label key={key}><span>{({ base_color: 'Base', mask_r_color: 'Design color 1', mask_g_color: 'Design color 2', mask_b_color: 'Design color 3', flake_color: 'Metallic flakes', flip_color: 'Flip color' })[key]}</span><input type="color" aria-label={`Paint ${key}`} value={color} disabled={!editable.includes(key) || busy} onChange={event => setColors(current => ({ ...current, [key]: event.target.value }))}/><small>{editable.includes(key) ? color.toUpperCase() : 'Locked'}</small></label>)}
    <div className="paint-actions"><button className="text-button" disabled={busy} onClick={() => {
      setColors(Object.fromEntries(Object.keys(colors).map(key => [key, paintHex(settings[key])])))
      edit({ op: 'paint', accessoryId: part.id, resetColors: true })
    }}>Reset colors</button><button className="save-button" disabled={busy || !changed.length} onClick={() => edit({ op: 'paint', accessoryId: part.id, colors: Object.fromEntries(changed.map(key => [key, paintRgb(colors[key])])) })}>Apply colors</button></div>
  </div>
}

function CatalogCard({ paused, item, index, advanced, previewPath, onChoose, onFailure, loadModel, loadThumbnail }) {
  const card = React.useRef(null), hoverRequest = React.useRef(null)
  const [preview, setPreview] = React.useState(''), [hoveredModel, setHoveredModel] = React.useState(null), [failed, setFailed] = React.useState(false)
  const canPreview = !!item.model || previewPath !== item.path
  React.useEffect(() => {
    if (!canPreview || paused || !card.current || preview) return
    let controller
    let completed = false
    const observer = new IntersectionObserver(entries => {
      const visible = entries.some(entry => entry.isIntersecting)
      if (!visible) { controller?.abort(); controller = null; return }
      if (completed || controller) return
      controller = new AbortController()
      const request = controller
      const image = card.current.querySelector('.card-image')
      loadThumbnail(previewPath, request.signal, Math.round(image.clientWidth * 1.5), Math.round(image.clientHeight * 1.5)).then(preview => {
        if (!request.signal.aborted) { completed = true; setPreview(preview); observer.disconnect() }
      }).catch(error => { if (error.name !== 'AbortError') { completed = true; observer.disconnect(); setFailed(true); onFailure(`${item.name}: ${error.message}`) } })
    }, { root: document.querySelector('.catalog-grid'), rootMargin: '0px' })
    observer.observe(card.current)
    return () => { observer.disconnect(); controller?.abort() }
  }, [canPreview, paused, preview, previewPath, item.name, loadThumbnail, onFailure])
  React.useEffect(() => () => hoverRequest.current?.abort(), [])
  const hideRotation = React.useCallback(() => { hoverRequest.current?.abort(); hoverRequest.current = null; setHoveredModel(null) }, [])
  React.useEffect(() => { if (paused) hideRotation() }, [paused, hideRotation])
  const showRotation = () => {
    if (!canPreview || paused) return
    hoverRequest.current?.abort()
    const controller = new AbortController(); hoverRequest.current = controller
    const cached = cachedModel(previewPath)
    if (cached) { setHoveredModel(cached); return }
    loadModel(previewPath, controller.signal).then(model => {
      if (!controller.signal.aborted && document.hasFocus() && card.current?.querySelector('.card-image')?.matches(':hover')) setHoveredModel(model)
    }).catch(error => { if (error.name !== 'AbortError') { setFailed(true); onFailure(`${item.name}: ${error.message}`) } })
  }
  return <button ref={card} className="catalog-card" onClick={onChoose} style={{ '--card-delay': `${Math.min(index % 14, 13) * 12}ms` }} title={advanced ? `${item.name} · ${item.path}` : item.name}>
    <span className="card-image" onPointerEnter={showRotation} onPointerLeave={hideRotation} onPointerCancel={hideRotation}>{item.paintFields && !canPreview ? <span className="paint-swatch" style={{ backgroundColor: paintHex(item.paintFields.base_color) }}><span>{["mask_r_color", "mask_g_color", "mask_b_color"].filter(key => item.paintFields[key]).map(key => <i key={key} style={{ backgroundColor: paintHex(item.paintFields[key]) }}/>)}</span></span> : hoveredModel ? <React.Suspense fallback={<span className="part-blueprint"><span>Loading preview</span></span>}><AnimatedPartPreview model={hoveredModel} label={item.name} onFailure={onFailure} onLeave={hideRotation}/></React.Suspense> : preview ? <img src={preview} loading="lazy" alt=""/> : item.iconUrl ? <img src={item.iconUrl} loading="lazy" alt=""/> : <span className={`part-blueprint ${canPreview ? '' : 'text-only'}`}><span>{failed ? 'Preview unavailable' : canPreview ? 'Loading model' : 'No 3D model'}</span><i/></span>}</span>
    <span className="card-copy"><b>{item.name}</b><small>{friendlyCategory(item.category || 'Game part')}{advanced && item.brand ? ` · ${item.brand}` : ''}</small>{advanced && <small className="card-internal">{item.unitId || item.path}</small>}</span>
    <span className="card-add"><Plus size={15}/></span>
  </button>
}function CopyIcon() { return <Layers3 size={14}/> }

createRoot(document.getElementById('root')).render(<App/>);
