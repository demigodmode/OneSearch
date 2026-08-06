import { Button } from '@/components/ui/button'
import type { Agent, SourcePathTestResponse } from '@/types/api'

export function RemotePathPicker({
  agent,
  value,
  onChange,
  onTest,
  result,
  testing,
}: {
  agent?: Agent
  value: string
  onChange: (value: string) => void
  onTest: () => void
  result?: SourcePathTestResponse | null
  testing: boolean
}) {
  return (
    <div className="space-y-2">
      <label className="text-sm font-medium" htmlFor="remote-root-path">
        Remote path
      </label>
      <select
        aria-label="Allowed root"
        className="w-full rounded-lg border border-border bg-background px-3 py-2"
        value=""
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">Choose an allowed root (or enter a path)</option>
        {agent?.allowed_roots.map((root) => (
          <option key={root.root_id} value={root.path}>
            {root.label ?? root.path}
          </option>
        ))}
      </select>
      <input
        id="remote-root-path"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-lg border border-border bg-background px-3 py-2 font-mono text-sm"
        placeholder="/srv/documents"
      />
      <Button
        type="button"
        size="sm"
        variant="secondary"
        onClick={onTest}
        disabled={!agent || agent.status !== 'online' || testing}
      >
        {testing ? 'Testing path...' : 'Test path'}
      </Button>
      {agent?.status !== 'online' && (
        <p className="text-xs text-destructive">
          The agent must be online before OneSearch can test its path.
        </p>
      )}
      {testing && <p className="text-xs text-muted-foreground">Waiting for the agent to test this path.</p>}
      {result && (
        <div className={result.ok ? 'text-xs text-success' : 'text-xs text-destructive'}>
          <p>
            {result.message}
            {result.status && ['pending', 'claimed', 'running', 'cancelling'].includes(result.status)
              ? ' Validation is still pending.'
              : ''}
          </p>
          {result.status === 'completed' && (
            <p className="mt-1">
              Exists: {result.exists ? 'yes' : 'no'} · Directory: {result.is_directory ? 'yes' : 'no'} · Readable: {result.readable ? 'yes' : 'no'}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
