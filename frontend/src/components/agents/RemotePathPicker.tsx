import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { FolderBrowser, type BrowsePage, type PathStyle } from '@/components/FolderBrowser'
import type { Agent, SourceBrowseRequest, SourceBrowseResponse, SourcePathTestResponse } from '@/types/api'

export function RemotePathPicker({ agent, value, onChange, onTest, result, testing, onBrowse }: {
  agent?: Agent; value: string; onChange: (value: string) => void; onTest: () => void
  result?: SourcePathTestResponse | null; testing: boolean
  onBrowse?: (request: SourceBrowseRequest) => Promise<SourceBrowseResponse>
}) {
  const connected = agent?.status === 'online' || agent?.status === 'degraded'
  const [browserKey, setBrowserKey] = useState(0)
  const pathStyle: PathStyle = agent?.platform?.toLowerCase().startsWith('win') ? 'windows' : 'posix'
  const browse = (rootId: string, path: string): Promise<BrowsePage> => {
    if (!agent || !onBrowse) return Promise.reject(new Error('Directory browsing is unavailable. Enter a path manually.'))
    return onBrowse({ agent_id: agent.id, root_id: rootId, path })
      .then((response) => (
        // don't throw: FolderBrowser checks root/path before showing the error
        response.status === 'completed'
          ? response
          : { ...response, error: response.error || 'Directory browse did not complete. Retry when the agent is available.' }
      ), (error: unknown) => {
        throw error instanceof Error ? error : new Error('Unable to browse this directory. Retry when the agent is available.')
      })
  }

  return <div className="space-y-2">
    <label className="text-sm font-medium" htmlFor="remote-root-path">Remote path</label>
    <FolderBrowser resetSignal={browserKey} roots={agent?.allowed_roots ?? []} available={connected} pathStyle={pathStyle} browse={browse} onSelect={onChange}>
      <input id="remote-root-path" value={value} onChange={(event) => { setBrowserKey((k) => k + 1); onChange(event.target.value) }} className="w-full rounded-lg border border-border bg-background px-3 py-2 font-mono text-sm" placeholder="/srv/documents" />
      <Button type="button" size="sm" variant="secondary" onClick={onTest} disabled={!connected || testing}>{testing ? 'Testing path...' : 'Test path'}</Button>
      {agent && !connected && <p className="text-xs text-destructive" role="status">The agent must be online before OneSearch can test or browse its path.</p>}
      {testing && <p className="text-xs text-muted-foreground" role="status">Waiting for the agent to test this path.</p>}
    </FolderBrowser>
    {result && <div className={result.ok ? 'text-xs text-success' : 'text-xs text-destructive'} role={result.ok ? 'status' : 'alert'} aria-live={result.ok ? 'polite' : 'assertive'}><p>{result.message}{result.status && ['pending', 'claimed', 'running', 'cancelling'].includes(result.status) ? ' Validation is still pending.' : ''}</p>{result.status === 'completed' && <p className="mt-1">Exists: {result.exists ? 'yes' : 'no'} · Directory: {result.is_directory ? 'yes' : 'no'} · Readable: {result.readable ? 'yes' : 'no'}</p>}</div>}
  </div>
}
