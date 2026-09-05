import { useEffect, useRef, useState } from 'react'
import { ChevronUp, Folder } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { Agent, SourceBrowseRequest, SourceBrowseResponse, SourcePathTestResponse } from '@/types/api'

function absolutePath(root: string, relative: string, platform?: string) {
  if (!relative) return root
  if (platform?.toLowerCase().startsWith('win')) {
    const nativeRelative = relative.replace(/\//g, '\\')
    if (/^[A-Za-z]:[\\/]+$/.test(root)) return `${root.replace(/\//g, '\\')}${nativeRelative}`
    return `${root.replace(/[\\/]+$/, '')}\\${nativeRelative}`
  }
  return `${root.replace(/\/+$/, '')}/${relative}`
}

export function RemotePathPicker({ agent, value, onChange, onTest, result, testing, onBrowse }: {
  agent?: Agent; value: string; onChange: (value: string) => void; onTest: () => void
  result?: SourcePathTestResponse | null; testing: boolean
  onBrowse?: (request: SourceBrowseRequest) => Promise<SourceBrowseResponse>
}) {
  const connected = agent?.status === 'online' || agent?.status === 'degraded'
  const [rootId, setRootId] = useState('')
  const [relativePath, setRelativePath] = useState('')
  const [browseResult, setBrowseResult] = useState<SourceBrowseResponse | null>(null)
  const [browseError, setBrowseError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const requestId = useRef(0)
  const mounted = useRef(true)
  const root = agent?.allowed_roots.find((item) => item.root_id === rootId)

  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false; requestId.current += 1 }
  }, [])
  const load = (nextRootId: string, nextRelativePath: string) => {
    if (!agent || !connected || loading) return
    const id = ++requestId.current
    setRootId(nextRootId); setRelativePath(nextRelativePath); setBrowseResult(null); setBrowseError(null); setLoading(true)
    if (!onBrowse) { setLoading(false); setBrowseError('Directory browsing is unavailable. Enter a path manually.'); return }
    onBrowse({ agent_id: agent.id, root_id: nextRootId, path: nextRelativePath })
      .then((response) => {
        if (!mounted.current || requestId.current !== id || response.root_id !== nextRootId || response.path !== nextRelativePath) return
        if (response.status !== 'completed') { setBrowseError(response.error || 'Directory browse did not complete. Retry when the agent is available.'); return }
        setBrowseResult(response)
      })
      .catch((error: unknown) => { if (mounted.current && requestId.current === id) setBrowseError(error instanceof Error ? error.message : 'Unable to browse this directory. Retry when the agent is available.') })
      .finally(() => { if (mounted.current && requestId.current === id) setLoading(false) })
  }
  const selectRoot = (nextRootId: string) => {
    const nextRoot = agent?.allowed_roots.find((item) => item.root_id === nextRootId)
    if (!nextRoot) return
    onChange(nextRoot.path); load(nextRootId, '')
  }
  const navigate = (nextRelativePath: string) => {
    if (!root) return
    onChange(absolutePath(root.path, nextRelativePath, agent?.platform)); load(root.root_id, nextRelativePath)
  }

  return <div className="space-y-2">
    <label className="text-sm font-medium" htmlFor="remote-root-path">Remote path</label>
    <select aria-label="Allowed root" className="w-full rounded-lg border border-border bg-background px-3 py-2" value={rootId} onChange={(event) => selectRoot(event.target.value)} disabled={!connected || loading}>
      <option value="">Choose an allowed root (or enter a path)</option>
      {agent?.allowed_roots.map((item) => <option key={item.root_id} value={item.root_id}>{item.label ?? item.path}</option>)}
    </select>
    <input id="remote-root-path" value={value} onChange={(event) => { requestId.current += 1; setRootId(''); setRelativePath(''); setLoading(false); setBrowseResult(null); setBrowseError(null); onChange(event.target.value) }} className="w-full rounded-lg border border-border bg-background px-3 py-2 font-mono text-sm" placeholder="/srv/documents" />
    <Button type="button" size="sm" variant="secondary" onClick={onTest} disabled={!connected || testing}>{testing ? 'Testing path...' : 'Test path'}</Button>
    {agent && !connected && <p className="text-xs text-destructive" role="status">The agent must be online before OneSearch can test or browse its path.</p>}
    {testing && <p className="text-xs text-muted-foreground" role="status">Waiting for the agent to test this path.</p>}
    {root && <div className="space-y-2 rounded-lg border border-border p-3" aria-live="polite">
      <p className="truncate font-mono text-xs" title={absolutePath(root.path, relativePath, agent?.platform)}>Browsing: {absolutePath(root.path, relativePath, agent?.platform)}</p>
      {relativePath && <Button type="button" size="sm" variant="ghost" onClick={() => navigate(relativePath.split('/').slice(0, -1).join('/'))} disabled={loading}><ChevronUp className="mr-1 h-4 w-4" />Parent folder</Button>}
      {loading && <p className="text-xs text-muted-foreground" role="status">Loading folders from {absolutePath(root.path, relativePath, agent?.platform)}…</p>}
      {browseError && <div className="flex flex-wrap items-center gap-2 text-xs text-destructive" role="alert"><span>{browseError}</span><Button type="button" size="sm" variant="secondary" onClick={() => load(root.root_id, relativePath)} disabled={loading}>Retry</Button></div>}
      {!loading && !browseError && browseResult?.entries.length === 0 && <p className="text-xs text-muted-foreground">No subfolders here. You can still enter a path manually.</p>}
      {browseResult?.truncated && <p className="text-xs text-muted-foreground">Only the first 500 folders are shown. Enter a path manually for another folder.</p>}
      <div className="space-y-1">{browseResult?.entries.map((entry) => <button key={entry.path} type="button" onClick={() => navigate(entry.path)} disabled={loading} className="flex w-full min-w-0 items-center gap-2 rounded-md px-2 py-1 text-left text-sm hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50" title={entry.name} aria-label={`Open folder ${entry.name}`}><Folder className="h-4 w-4 shrink-0" /><span className="truncate">{entry.name}</span></button>)}</div>
    </div>}
    {result && <div className={result.ok ? 'text-xs text-success' : 'text-xs text-destructive'} role={result.ok ? 'status' : 'alert'} aria-live={result.ok ? 'polite' : 'assertive'}><p>{result.message}{result.status && ['pending', 'claimed', 'running', 'cancelling'].includes(result.status) ? ' Validation is still pending.' : ''}</p>{result.status === 'completed' && <p className="mt-1">Exists: {result.exists ? 'yes' : 'no'} · Directory: {result.is_directory ? 'yes' : 'no'} · Readable: {result.readable ? 'yes' : 'no'}</p>}</div>}
  </div>
}
