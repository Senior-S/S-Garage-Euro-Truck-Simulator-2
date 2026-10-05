import React from 'react'
import { Clock3 } from 'lucide-react'

export default function LoadingProgress({ requests }) {
  const [jobs, setJobs] = React.useState({})
  const [now, setNow] = React.useState(Date.now)
  const [disconnected, setDisconnected] = React.useState(false)
  const ids = requests.map(request => request.id).join(',')
  React.useEffect(() => {
    if (!ids) return
    const controller = new AbortController()
    let timer, timeout
    const poll = async () => {
      const query = new URLSearchParams()
      for (const id of ids.split(',')) query.append('requestId', id)
      const request = new AbortController()
      const cancel = () => request.abort()
      controller.signal.addEventListener('abort', cancel, { once: true })
      timeout = setTimeout(cancel, 3000)
      try {
        const response = await fetch(`/api/progress?${query}`, { signal: request.signal })
        if (!response.ok) throw new Error('Progress unavailable')
        const data = await response.json()
        if (!controller.signal.aborted) { setJobs(data); setDisconnected(false) }
      } catch {
        if (!controller.signal.aborted) setDisconnected(true)
      } finally {
        clearTimeout(timeout)
        controller.signal.removeEventListener('abort', cancel)
        if (!controller.signal.aborted) timer = setTimeout(poll, 500)
      }
    }
    poll()
    const clock = setInterval(() => setNow(Date.now()), 1000)
    return () => { controller.abort(); clearTimeout(timer); clearTimeout(timeout); clearInterval(clock) }
  }, [ids])
  if (!requests.length) return null
  return <section className="loading-progress" aria-label="Garage loading progress">
    <div className="loading-progress-heading"><strong>Preparing your garage</strong><span>Keep this window open</span></div>
    {requests.map(request => {
      const job = jobs[request.id]
      const stage = job?.state === 'done' ? 'Finishing up' : job?.stage || request.label
      const elapsed = Math.max(0, Math.floor((now - request.startedAt) / 1000))
      const elapsedText = elapsed < 60 ? `${elapsed}s` : `${Math.floor(elapsed / 60)}m ${elapsed % 60}s`
      const measured = job?.total > 0 && job.completed != null
      return <div className="loading-progress-job" key={request.id}>
        <div className="loading-progress-stage"><span role="status">{stage}</span><span className="loading-progress-time"><Clock3 size={12}/>{elapsedText}</span></div>
        <progress aria-label={stage} max={measured ? job.total : undefined} value={measured ? job.completed : undefined}/>
        <div className="loading-progress-detail"><span>{job?.detail || request.detail || 'Checking local files and cached assets.'}</span>{measured && <span>{job.completed.toLocaleString()} / {job.total.toLocaleString()}</span>}</div>
      </div>
    })}
    <p className="loading-progress-note">{disconnected ? 'Progress connection interrupted. Retrying...' : 'First imports take longer. Imported parts are cached for your next visit.'}</p>
  </section>
}
