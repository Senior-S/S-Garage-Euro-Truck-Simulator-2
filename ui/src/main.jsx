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
import { AlertTriangle, ArrowLeftRight, Check, ChevronDown, ChevronRight, CircleHelp, Clock3, Cloud, Cpu, Disc3, Eye, Filter, History, Layers3, Move3D, PanelLeftClose, Plus, RotateCcw, Save, Search, Settings2, SlidersHorizontal, Truck, Undo2, Redo2, X } from 'lucide-react'
import GarageScene from './scene.jsx'
import { AnimatedPartPreview, cachedThumbnail, cacheModel, cachedModel, clearModelCache, queuePreview, renderModelThumbnail } from './catalog-preview.jsx'
import './style.css'

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

function App() {
  const [status, setStatus] = React.useState(null), [saves, setSaves] = React.useState([]), [state, setState] = React.useState(null), [catalog, setCatalog] = React.useState([]), [catalogLoading, setCatalogLoading] = React.useState(true)
  const [selectedProfile, setSelectedProfile] = React.useState(''), [selectedSaveId, setSelectedSaveId] = React.useState('')
  const [error, setError] = React.useState(''), [notice, setNotice] = React.useState(''), [busy, setBusy] = React.useState(''), [mode, setMode] = React.useState('replace'), [sceneIssues, setSceneIssues] = React.useState([])
  const [category, setCategory] = React.useState('all'), [query, setQuery] = React.useState(''), [brand, setBrand] = React.useState('all'), [selected, setSelected] = React.useState(''), [chosenSlot, setChosenSlot] = React.useState('')
  const [mountPoint, setMountPoint] = React.useState(null), [selectedMarker, setSelectedMarker] = React.useState(null)
  const [settings, setSettings] = React.useState(false), [gamePath, setGamePath] = React.useState(''), [profilesPath, setProfilesPath] = React.useState(''), [decryptorPath, setDecryptorPath] = React.useState(''), [toolPath, setToolPath] = React.useState('')
  const [catalogOpen, setCatalogOpen] = React.useState(true)
  const [lightMode, setLightMode] = React.useState('off'), [markerVisibility, setMarkerVisibility] = React.useState('all')
  const [showDuplicates, setShowDuplicates] = React.useState(() => localStorage.getItem('yard.showDuplicates') === 'true')
  const [catalogLimit, setCatalogLimit] = React.useState(180)
  const [assetVersion, setAssetVersion] = React.useState(0)
  const [advanced, setAdvanced] = React.useState(() => localStorage.getItem('yard.advanced') === 'true')
  const sceneCancel = React.useRef(null), truckSelectRequest = React.useRef(null), truckSelectSequence = React.useRef(0)
  const reportError = React.useCallback(message => setError(message), [])
  const activePart = state?.truck?.accessories?.find(a => a.id === selected) || state?.truck?.accessories?.[0]
  const categories = [...new Set([...catalog, ...(state?.truck?.accessories || [])].map(item => item.category).filter(Boolean))].sort()
  const brands = [...new Set(catalog.map(item => item.brand).filter(Boolean))].sort()
  const profiles = [...new Map(saves.map(save => [profileId(save), { id: profileId(save), name: save.profile || 'Profile' }])).values()]
  const profileSaves = saves.filter(save => profileId(save) === selectedProfile).sort((a, b) => new Date(b.modified || b.created || 0) - new Date(a.modified || a.created || 0))
  const activeSave = saves.find(save => save.id === state?.saveId)
  const partLabel = part => catalog.find(item => item.path === part.dataPath)?.name || friendlyCategory(part.category || part.type)

  const applyState = React.useCallback(data => {
    setState(data)
    setSelected(current => data?.truck?.accessories?.some(p => p.id === data.editedAccessoryId) ? data.editedAccessoryId : data?.truck?.accessories?.some(p => p.id === current) ? current : data?.truck?.accessories?.[0]?.id || '')
  }, [])
  const refresh = React.useCallback(async () => {
    const [next, list] = await Promise.all([api('/api/status'), api('/api/saves')]); setStatus(next); setSaves(list)
    if (next.gamePath) setGamePath(next.gamePath)
    if (next.profilesPath) setProfilesPath(next.profilesPath)
    if (next.decryptorPath) setDecryptorPath(next.decryptorPath)
    if (next.toolPath) setToolPath(next.toolPath)
    if (next.session) applyState(next.session)
    else applyState(null)
    setCatalogLoading(true)
    try { setCatalog(await api('/api/catalog')) } finally { setCatalogLoading(false) }
  }, [applyState])
  React.useEffect(() => { refresh().catch(e => setError(e.message)) }, [refresh])
  React.useEffect(() => { if (!notice) return; const id = setTimeout(() => setNotice(''), 3600); return () => clearTimeout(id) }, [notice])
  React.useEffect(() => setCatalogLimit(180), [query, category, brand, Boolean(chosenSlot), showDuplicates])
  React.useEffect(() => { setSelectedMarker(null); setChosenSlot(''); setMountPoint(null) }, [state?.sessionId, state?.truck?.id])
  React.useEffect(() => {
    if (!state?.truck) return
    if (chosenSlot) {
      const owner = state.truck.accessories.find(part => part.id === (selectedMarker?.accessoryId || selected))
      setMode(owner?.slots?.some(slot => slot.name === chosenSlot && slot.hookup) ? 'replace' : 'add')
    } else if (selectedMarker?.kind === 'part') {
      const parts = state.truck.accessories.filter(part => part.category === selectedMarker.category)
      const fitted = parts.find(part => part.id === state.editedAccessoryId) || parts.find(part => part.id === selectedMarker.accessoryId) || parts[0]
      if (fitted) {
        if (selectedMarker.accessoryId !== fitted.id) setSelectedMarker({ ...selectedMarker, accessoryId: fitted.id })
        setSelected(fitted.id); setMountPoint(null); setMode('replace')
      } else {
        const empty = selectedMarker.accessoryId ? { ...selectedMarker, accessoryId: null } : selectedMarker
        if (empty !== selectedMarker) setSelectedMarker(empty)
        setMountPoint(empty); setMode('add')
      }
    }
  }, [state?.revision, chosenSlot, selectedMarker])
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
  const requestModel = React.useCallback(async (path, signal) => {
    signal.throwIfAborted()
    const requestId = crypto.randomUUID()
    const cancel = () => { send('/api/cancel-model', { requestId }).catch(error => reportError(error.message)) }
    signal.addEventListener('abort', cancel, { once: true })
    try { return await api(`/api/model?path=${encodeURIComponent(path)}&requestId=${requestId}`, { signal }) }
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
    const key = status?.previewVersion ? new URL(`/__catalog_preview/${encodeURIComponent(status.previewVersion)}/${encodeURIComponent(path)}?size=${width}x${height}&render=3`, location.origin).href : null
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
      return renderModelThumbnail(model, currentSignal, width, height, key)
    }, signal)
  }, [status?.previewVersion, requestModel])
  const loadSave = id => {
    if (state?.dirty && !window.confirm('This save has unsaved changes. Discard them and open another save?')) return
    return run('Opening save', async () => {
      sceneCancel.current?.()
      const next = await send('/api/load', { saveId: id }); applyState(next)
      clearModelCache(); setAssetVersion(value => value + 1)
      const save = saves.find(item => item.id === id)
      if (save) { setSelectedProfile(profileId(save)); setSelectedSaveId(id) }
      setCatalogLoading(true)
      try {
        const [updatedStatus, updatedCatalog] = await Promise.all([api('/api/status'), api('/api/catalog')])
        setStatus(updatedStatus); setCatalog(updatedCatalog)
      } finally { setCatalogLoading(false) }
      setNotice('Save opened'); return next
    })
  }
  const selectProfile = id => { setSelectedProfile(id); setSelectedSaveId('') }
  const selectTruck = id => {
    sceneCancel.current?.(); truckSelectRequest.current?.abort()
    const controller = new AbortController(), sequence = ++truckSelectSequence.current
    truckSelectRequest.current = controller
    return run('Switching truck', async () => {
      const next = await send('/api/select', { ...revisionGuard(), truckId: id }, { signal: controller.signal })
      return sequence === truckSelectSequence.current ? next : null
    })
  }
  const edit = body => { sceneCancel.current?.(); return run('Applying change', () => send('/api/edit', { ...revisionGuard(), truckId: state?.truck?.id, ...body })) }
  const save = () => run('Writing save', async () => { const result = await send('/api/save', revisionGuard()); applyState(result.state); setNotice(`Saved. Backup: ${result.backupPath}`); return result.state })
  const history = direction => { sceneCancel.current?.(); return run(direction === 'undo' ? 'Undoing' : 'Redoing', () => send(`/api/${direction}`, revisionGuard())) }
  React.useEffect(() => {
    const onKey = e => {
      const target = e.target
      if (target instanceof HTMLElement && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))) return
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z' && !e.shiftKey) { e.preventDefault(); if (state?.canUndo) history('undo') }
      if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === 'y' || (e.key.toLowerCase() === 'z' && e.shiftKey))) { e.preventDefault(); if (state?.canRedo) history('redo') }
      if (e.key === 'Escape') { setSettings(false); setError('') }
    }
    window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey)
  }, [state?.canUndo, state?.canRedo])
  React.useEffect(() => {
    if (!state?.dirty) return
    const before = e => { e.preventDefault(); e.returnValue = '' }
    window.addEventListener('beforeunload', before); return () => window.removeEventListener('beforeunload', before)
  }, [state?.dirty])

  const matching = React.useMemo(() => catalog.filter(item => {
    const isHookup = item.category?.toLowerCase() === 'hookup'
    return (chosenSlot || category === 'hookup' ? isHookup : !isHookup) && (chosenSlot || (category === 'all' || item.category === category) && (brand === 'all' || item.brand === brand)) && `${item.name} ${item.category} ${advanced ? `${item.brand} ${item.path} ${item.unitId}` : brandLabel(item.brand)}`.toLowerCase().includes(query.toLowerCase())
  }), [catalog, chosenSlot, category, brand, query, advanced])
  const filtered = React.useMemo(() => {
    if (showDuplicates) return matching
    const unique = new Map()
    for (const item of matching) {
      const key = item.duplicateKey || item.path
      const existing = unique.get(key)
      const rank = item.path === activePart?.dataPath ? 2 : item.brand === state?.truck?.brand ? 1 : 0
      const previousRank = existing?.path === activePart?.dataPath ? 2 : existing?.brand === state?.truck?.brand ? 1 : 0
      if (!existing || rank > previousRank) unique.set(key, item)
    }
    return [...unique.values()]
  }, [matching, showDuplicates, activePart?.dataPath, state?.truck?.brand])
  const shownIssues = [...new Set([...(state?.issues || []), ...sceneIssues])]
  const applyDefinition = item => {
    if (!state?.truck) return
    if (chosenSlot && (mode === 'add' || mode === 'replace') && activePart) { edit({ op: 'hookup', accessoryId: activePart.id, slotName: chosenSlot, hookup: item.unitId }); return }
    if (mode === 'replace' && activePart) edit({ op: 'replace', accessoryId: activePart.id, dataPath: item.path })
    else if (mode === 'add') edit({ op: 'add', dataPath: item.path })
    else if (mode === 'duplicate' && activePart) edit({ op: 'duplicate', accessoryId: activePart.id, dataPath: item.path })
  }
  const saveConfig = () => {
    if (state?.dirty && !window.confirm('Changing folders will close the current save. Discard unsaved changes and continue?')) return
    return run('Checking folders', async () => {
      const updated = await send('/api/config', { gamePath, profilesPath, decryptorPath, toolPath }); setStatus(updated); applyState(updated.session || null); clearModelCache(); setAssetVersion(value => value + 1)
      setGamePath(updated.gamePath || gamePath); setProfilesPath(updated.profilesPath || profilesPath); setDecryptorPath(updated.decryptorPath || decryptorPath); setToolPath(updated.toolPath || toolPath)
      setSettings(false); setNotice(updated.message || 'Folders updated')
      setCatalogLoading(true)
      try { const [list, defs] = await Promise.all([api('/api/saves'), api('/api/catalog')]); setSaves(list); setCatalog(defs) }
      finally { setCatalogLoading(false) }
      return null
    })
  }

  return <div className="app-shell">
    <header className="topbar">
      <div className="brand-lockup"><span className="brand-mark"><Truck size={19} strokeWidth={1.8}/></span><span className="brand-word">S Garage <span>/</span></span><span className="brand-caption">ETS2</span></div>
      <div className="top-divider" />
      <div className="source-selects">
        <div className="profile-select"><span className="eyebrow">Profile</span><label><select aria-label="Select profile" value={selectedProfile} onChange={e => selectProfile(e.target.value)}><option value="">Choose profile…</option>{profiles.map(profile => <option key={profile.id} value={profile.id}>{profile.name}</option>)}</select><ChevronDown size={14}/></label></div>
        <div className="save-select"><span className="eyebrow">Save file</span><label><select aria-label="Select save" value={profileSaves.some(save => save.id === selectedSaveId) ? selectedSaveId : ''} onChange={e => e.target.value && loadSave(e.target.value)}><option value="">{profileSaves.length ? 'Choose a save…' : 'No saves in profile'}</option>{profileSaves.map(save => <option key={save.id} value={save.id}>{save.name} · {dateLabel(save.modified || save.created)}</option>)}</select><ChevronDown size={14}/></label></div>
      </div>
      <div className="top-meta"><span className={`live-dot ${status?.ready ? 'ready' : ''}`} /><span>{status?.ready ? 'Save scanner ready' : 'Checking local files'}</span><span className="meta-sep">·</span><span>{saves.length} saves</span></div>
      <button className={`advanced-toggle ${advanced ? 'active' : ''}`} aria-pressed={advanced} onClick={() => setAdvanced(value => !value)} title="Show internal paths and save fields"><SlidersHorizontal size={15}/><span>Advanced view</span></button>
      <button className="icon-button settings-button" onClick={() => setSettings(true)} aria-label="Settings"><Settings2 size={17}/></button>
      <button className="save-button" onClick={save} disabled={!state?.dirty || !!busy}><Save size={15}/><span>{busy === 'Writing save' ? 'Saving…' : 'Save changes'}</span>{state?.dirty && <i/>}</button>
    </header>

    <main className="workspace">
      <aside className="installed-panel">
        <div className="panel-heading"><div><div className="eyebrow">Garage</div><h1>Installed parts</h1></div><span className="count-pill">{state?.truck?.accessories?.length ?? '—'}</span></div>
        {state?.trucks?.length > 0 && <label className="truck-switch"><Truck size={15}/><select aria-label="Select truck" value={state.truck?.id || ''} onChange={e => selectTruck(e.target.value)}>{state.trucks.map(t => <option value={t.id} key={t.id}>{t.name} · {t.plate}</option>)}</select><ChevronDown size={14}/></label>}
        {state?.truck && <div className="truck-info"><span className="truck-badge"><Truck size={21}/></span><div><b>{state.truck.name}</b><small>{advanced && state.truck.brand ? `${state.truck.brand} · ` : ''}{state.truck.plate || 'Truck ready'}</small></div><span className="truck-angle">↗</span></div>}
        <div className="part-list-title"><span>Installed components</span><span>{state?.truck?.accessories?.length || 0}</span></div>
        <div className="part-list">{state?.truck?.accessories?.map((part, index) => <button className={`part-row ${activePart?.id === part.id ? 'selected' : ''}`} key={part.id} onClick={() => { setSelectedMarker(null); setSelected(part.id); setChosenSlot(''); setMountPoint(null); setMode('replace'); setBrand('all'); setQuery(''); setCategory(part.category || 'all') }}>
          <span className="part-icon">{part.category?.toLowerCase().includes('wheel') || part.category?.toLowerCase().includes('tyre') ? <Disc3 size={17}/> : part.category?.toLowerCase().includes('engine') ? <Cpu size={17}/> : <Layers3 size={17}/>}</span><span className="part-copy"><b>{partLabel(part)}</b><small>{friendlyCategory(part.category || part.type)}</small></span><ChevronRight size={14} className="part-arrow"/>
        </button>)}</div>
        {activePart && <section className="part-detail"><div className="detail-overline"><span>{advanced ? 'Selected component' : 'Selected part'}</span><button title="Remove component" aria-label="Remove component" onClick={() => edit({ op: 'remove', accessoryId: activePart.id })}><X size={15}/></button></div><h2>{partLabel(activePart)}</h2>{advanced && <p className="path-text">{activePart.dataPath}</p>}
          <div className="detail-metrics"><div><span>Category</span><b>{friendlyCategory(activePart.category || activePart.type)}</b></div><div><span>Instances</span><b>{state?.truck?.accessoryCount ?? state?.truck?.accessories?.length}</b></div></div>
          {activePart.slots?.length > 0 && <div className="slot-block"><div className="slot-heading"><span>Attachment points</span><span>{activePart.slots.length}</span></div>{activePart.slots.map((slot, index) => { const hookup = catalog.find(item => item.unitId === slot.hookup); return <div className="slot-entry" key={`${slot.name}:${index}`}><button className={`slot-row ${chosenSlot === slot.name ? 'slot-chosen' : ''}`} onClick={() => { setSelectedMarker({ accessoryId: activePart.id, name: slot.name, kind: 'hookup' }); setChosenSlot(slot.name); setMountPoint(null); setMode('add'); if (category !== 'hookup') { setCategory('hookup'); setBrand('all'); setQuery('') } }}><span className="slot-lamp"/><span>{friendlySlot(slot.name)}</span><code>{advanced ? slot.hookup || 'Empty' : hookup?.name || (slot.hookup ? 'Installed' : 'Empty')}</code></button><button className="slot-remove" aria-label={`Remove attachment from ${friendlySlot(slot.name)}`} title="Remove this attachment. Undo is available." onClick={() => edit({ op: 'hookup', accessoryId: activePart.id, slotName: slot.name, index, hookup: '' })}><X size={13}/></button></div>})}</div>}
          {advanced && Object.keys(activePart.fields || {}).length > 0 && <details className="field-editor"><summary><SlidersHorizontal size={13}/> Raw instance fields <ChevronDown size={13}/></summary><div className="fields-scroll">{Object.entries(activePart.fields).filter(([key]) => !/^(id|accessory|parent|_)/i.test(key)).map(([key, value]) => <label key={key}><span>{pretty(key)}</span><input defaultValue={value} onBlur={e => e.target.value !== value && edit({ op: 'fields', accessoryId: activePart.id, fields: { [key]: e.target.value } })}/></label>)}</div></details>}
          <div className="component-actions"><button title="Duplicate installed part" onClick={() => edit({ op: 'duplicate', accessoryId: activePart.id })}><CopyIcon/> DUPLICATE</button><button title="Replace from catalog" onClick={() => { setMode('replace'); setCatalogOpen(true) }}><ArrowLeftRight size={14}/> REPLACE</button></div>
        </section>}
        {!state && <div className="empty-state"><Truck size={30}/><b>Choose a save to open the workshop</b><span>S Garage reads your local profile and save files.</span></div>}
        <div className="aside-footer"><span className="small-status-dot"/><span>{status?.gameRunning ? 'Game is running' : status?.ready ? 'Local save linked' : 'Save path not set'}</span><button onClick={() => setSettings(true)}>Folders <ChevronRight size={12}/></button></div>
      </aside>

      <section className="viewport-panel">
        <div className="viewport-header"><div><span className="eyebrow">Truck model</span><h2>{state?.truck?.name || 'Truck inspection'}</h2>{advanced && state?.truck?.brand && <span className="truck-make">{state.truck.brand}</span>}</div><div className="preview-controls"><label>Lights<select aria-label="Preview lights" value={lightMode} onChange={event => setLightMode(event.target.value)}><option value="off">Off</option><option value="low">Low</option><option value="high">High</option></select></label><label>Markers<select aria-label="Marker visibility" value={markerVisibility} onChange={event => setMarkerVisibility(event.target.value)}><option value="all">All</option><option value="selected">Selected only</option><option value="hidden">Hidden</option></select></label></div></div>
        <div className="scene-wrap">{state?.truck ? <GarageScene lightMode={lightMode} markerVisibility={markerVisibility} key={`${state.sessionId}:${state.truck.id}`} truckKey={`${state.sessionId}:${state.truck.id}`} sceneRevision={state.revision} sessionId={state.sessionId} truckId={state.truck.id} cancelRef={sceneCancel} selectedAccessoryId={activePart?.id} selectedMarker={selectedMarker} markerLabel={point => point.kind === 'hookup' ? `${friendlyCategory(state.truck.accessories.find(part => part.id === point.accessoryId)?.category)} / ${friendlySlot(point.name)}` : friendlyCategory(point.category || point.name)} onPick={point => {
          setSelectedMarker(point.kind ? point : null)
          const part = state.truck.accessories.find(item => item.id === point.accessoryId)
          const nextCategory = point.kind === 'hookup' ? 'hookup' : part?.category || point.category || 'all'
          if (nextCategory !== category) { setCategory(nextCategory); setBrand('all'); setQuery('') }
          if (point.kind === 'hookup') { setSelected(point.accessoryId); setChosenSlot(point.name); setMountPoint(null); setMode('add') }
          else if (point.kind === 'part') { setChosenSlot(''); if (point.accessoryId) { setSelected(point.accessoryId); setMountPoint(null); setMode('replace') } else { setMountPoint(point); setMode('add') } }
          else if (point.accessoryId) { setSelected(point.accessoryId); setChosenSlot(''); setMountPoint(null); setMode('replace') }
        }} onFailure={reportError} onIssues={setSceneIssues} /> : <div className="scene-empty"><div className="scan-glyph"><Truck size={39}/><span/></div><b>Waiting for a truck</b><p>Open a save to inspect the truck geometry from your game files.</p></div>}
          <div className="scene-vignette"/>{advanced && <div className="scene-label"><span className="scene-live"/> GEOMETRY STREAM <span className="scene-label-sep">·</span> MODEL DATA</div>}
          {busy && <div className="scene-loading"><span className="loading-pulse"/>{busy}</div>}
        </div>
        {shownIssues.length > 0 && <div className="issue-strip"><AlertTriangle size={14}/><span>{advanced ? shownIssues.join(' · ') : `${shownIssues.length} preview issues. Enable Advanced view for details.`}</span></div>}
      </section>

      <aside className={`catalog-panel ${catalogOpen ? '' : 'catalog-collapsed'}`}>
        <div className="catalog-heading"><div><div className="eyebrow">PARTS DEPARTMENT / 03</div><h2>Catalog</h2></div><button className="icon-button" onClick={() => setCatalogOpen(!catalogOpen)} aria-label="Collapse catalog"><PanelLeftClose size={16}/></button></div>
        {catalogOpen && <><div className="catalog-mode"><button className={mode === 'replace' ? 'active' : ''} onClick={() => { setMode('replace'); if (!chosenSlot) { setSelectedMarker(null); setChosenSlot(''); setMountPoint(null) } }}><ArrowLeftRight size={14}/> Replace</button><button className={mode === 'add' ? 'active' : ''} onClick={() => setMode('add')}><Plus size={15}/> Add</button><button className={mode === 'duplicate' ? 'active' : ''} onClick={() => { setSelectedMarker(null); setMode('duplicate'); setChosenSlot(''); setMountPoint(null) }}><CopyIcon/> Copy</button></div>
          <label className="search-box"><Search size={16}/><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search parts, brands…"/><kbd>/</kbd></label>
          <div className="filter-row"><label><Filter size={13}/><select aria-label="Filter category" value={category} onChange={e => setCategory(e.target.value)}><option value="all">All categories</option>{categories.map(c => <option key={c} value={c}>{friendlyCategory(c)}</option>)}</select><ChevronDown size={12}/></label><label><select aria-label="Filter brand" value={brand} onChange={e => setBrand(e.target.value)}><option value="all">All makes</option>{brands.map(b => <option key={b} value={b}>{brandLabel(b)}</option>)}</select><ChevronDown size={12}/></label></div>
          {(chosenSlot || mountPoint) && <div className="target-chip"><span className="slot-lamp"/> Target: {friendlySlot(chosenSlot || mountPoint?.name || 'Mount point')}<button aria-label="Clear selected attachment point" onClick={() => { setSelectedMarker(null); setChosenSlot(''); setMountPoint(null) }}><X size={12}/></button></div>}
          <div className="catalog-result-line"><span>{filtered.length.toLocaleString()} parts</span><label className="duplicates-toggle"><input type="checkbox" checked={showDuplicates} onChange={e => setShowDuplicates(e.target.checked)}/> Show duplicates</label></div>
          <div className="catalog-grid" key={JSON.stringify([assetVersion, category, query, brand, Boolean(chosenSlot), showDuplicates])}>{filtered.slice(0, catalogLimit).map((item, index) => <CatalogCard key={item.path} item={item} index={index} advanced={advanced} onChoose={() => applyDefinition(item)} onFailure={reportError} loadModel={loadModel} loadThumbnail={loadThumbnail} />)}{filtered.length === 0 && <div className="no-results"><Search size={21}/><span>{chosenSlot ? 'No hookup definitions match this search.' : 'No parts match this filter.'}</span></div>}{filtered.length > catalogLimit && <button className="load-more" onClick={() => setCatalogLimit(limit => limit + 180)}>Show next {Math.min(180, filtered.length - catalogLimit)} parts <ChevronDown size={13}/></button>}</div>
          <div className="catalog-foot"><span><span className={`small-status-dot ${catalogLoading ? 'loading-dot' : ''}`}/>{catalogLoading ? 'IMPORTING GAME ASSETS' : 'CATALOG FROM GAME DATA'}</span><span>{filtered.length > catalogLimit ? `Showing ${catalogLimit} of ` : ''}{filtered.length}</span></div>
        </>}
      </aside>
    </main>

    <footer className="statusbar"><div className="history-actions"><button disabled={!state?.canUndo || !!busy} onClick={() => history('undo')} title="Undo (Ctrl+Z)"><Undo2 size={15}/> Undo</button><button disabled={!state?.canRedo || !!busy} onClick={() => history('redo')} title="Redo (Ctrl+Y)"><Redo2 size={15}/> Redo</button><span className="history-separator"/><span className="revision"><History size={13}/> {advanced ? `Revision ${state?.revision ?? '—'}` : 'History'}</span></div><div className="status-save"><span className={`dirty-marker ${state?.dirty ? 'is-dirty' : ''}`}/><span>{state?.dirty ? 'Unsaved changes' : state ? 'All changes saved' : 'No session'}</span>{activeSave && <><span className="history-separator"/><Clock3 size={13}/><span>{dateLabel(activeSave.modified || activeSave.created)}</span>{advanced && activeSave.format && <span>{activeSave.format}</span>}</>}</div><div className="status-right"><span><Cloud size={14}/> Local only</span><span className="history-separator"/><button onClick={() => setSettings(true)}><CircleHelp size={14}/> Help & paths</button></div></footer>
    {(error || notice) && <div role="status" className={`toast ${error ? 'toast-error' : ''}`}><span>{error || notice}</span><button onClick={() => { setError(''); setNotice('') }} aria-label="Dismiss message"><X size={15}/></button></div>}
    {settings && <div className="modal-backdrop" onMouseDown={e => e.target === e.currentTarget && setSettings(false)}><section className="settings-modal" role="dialog" aria-modal="true" aria-labelledby="settings-title"><div className="modal-top"><div><div className="eyebrow">LOCAL CONNECTION</div><h2 id="settings-title">Game folders</h2></div><button className="icon-button" onClick={() => setSettings(false)} aria-label="Close settings"><X size={17}/></button></div><p className="modal-copy">Point S Garage at your Euro Truck Simulator 2 install and profile directory. Your save stays on this PC.</p><label className="path-field"><span>GAME INSTALL DIRECTORY</span><input value={gamePath} onChange={e => setGamePath(e.target.value)} placeholder="C:\\Program Files (x86)\\Steam\\steamapps\\common\\Euro Truck Simulator 2"/></label><label className="path-field"><span>PROFILES DIRECTORY</span><input value={profilesPath} onChange={e => setProfilesPath(e.target.value)} placeholder="Documents\\Euro Truck Simulator 2\\profiles"/></label><label className="path-field"><span>CONVERTERPIX TOOL</span><input value={toolPath} onChange={e => setToolPath(e.target.value)} placeholder="Path to converter_pix.exe"/></label><label className="path-field"><span>DECRYPTOR TOOL (OPTIONAL)</span><input value={decryptorPath} onChange={e => setDecryptorPath(e.target.value)} placeholder="Path to a compatible save decryptor executable"/></label><div className="detected-path"><span className={`small-status-dot ${status?.ready ? '' : 'off'}`}/><span>{status?.message || status?.toolPath || status?.decryptorPath || 'Waiting for folder scan'}</span></div><div className="modal-actions"><button className="text-button" onClick={() => setSettings(false)}>CANCEL</button><button className="save-button" onClick={saveConfig} disabled={!!busy}><Check size={15}/> SCAN FOLDERS</button></div></section></div>}
  </div>
}

function CatalogCard({ item, index, advanced, onChoose, onFailure, loadModel, loadThumbnail }) {
  const card = React.useRef(null), hoverRequest = React.useRef(null)
  const [preview, setPreview] = React.useState(''), [hoveredModel, setHoveredModel] = React.useState(null), [failed, setFailed] = React.useState(false)
  const canPreview = !!item.model
  React.useEffect(() => {
    if (!canPreview || !card.current) return
    let controller
    let completed = false
    const observer = new IntersectionObserver(entries => {
      const visible = entries.some(entry => entry.isIntersecting)
      if (!visible) { controller?.abort(); controller = null; return }
      if (completed || controller) return
      controller = new AbortController()
      const request = controller
      const image = card.current.querySelector('.card-image')
      loadThumbnail(item.path, request.signal, Math.round(image.clientWidth * 1.5), Math.round(image.clientHeight * 1.5)).then(preview => {
        if (!request.signal.aborted) { completed = true; setPreview(preview); observer.disconnect() }
      }).catch(error => { if (error.name !== 'AbortError') { completed = true; observer.disconnect(); setFailed(true); onFailure(`${item.name}: ${error.message}`) } })
    }, { root: document.querySelector('.catalog-grid'), rootMargin: '0px' })
    observer.observe(card.current)
    return () => { observer.disconnect(); controller?.abort() }
  }, [canPreview, item.path, item.name, loadThumbnail, onFailure])
  React.useEffect(() => () => hoverRequest.current?.abort(), [])
  const showRotation = () => {
    if (!canPreview) return
    hoverRequest.current?.abort()
    const controller = new AbortController(); hoverRequest.current = controller
    const cached = cachedModel(item.path)
    if (cached) { setHoveredModel(cached); return }
    loadModel(item.path, controller.signal).then(model => {
      if (!controller.signal.aborted) setHoveredModel(model)
    }).catch(error => { if (error.name !== 'AbortError') { setFailed(true); onFailure(`${item.name}: ${error.message}`) } })
  }
  const hideRotation = () => { hoverRequest.current?.abort(); hoverRequest.current = null; setHoveredModel(null) }
  return <button ref={card} className="catalog-card" onClick={onChoose} style={{ '--card-delay': `${Math.min(index % 14, 13) * 12}ms` }} title={advanced ? `${item.name} · ${item.path}` : item.name}>
    <span className="card-image" onPointerEnter={showRotation} onPointerLeave={hideRotation} onPointerCancel={hideRotation}>{hoveredModel ? <AnimatedPartPreview model={hoveredModel} label={item.name} onFailure={onFailure}/> : preview ? <img src={preview} loading="lazy" alt=""/> : item.iconUrl ? <img src={item.iconUrl} loading="lazy" alt=""/> : <span className={`part-blueprint ${canPreview ? '' : 'text-only'}`}><span>{failed ? 'Preview unavailable' : canPreview ? 'Loading model' : 'No 3D model'}</span><i/></span>}</span>
    <span className="card-copy"><b>{item.name}</b><small>{friendlyCategory(item.category || 'Game part')}{advanced && item.brand ? ` · ${item.brand}` : ''}</small>{advanced && <small className="card-internal">{item.unitId || item.path}</small>}</span>
    <span className="card-add"><Plus size={15}/></span>
  </button>
}function CopyIcon() { return <Layers3 size={14}/> }

createRoot(document.getElementById('root')).render(<App/>);
