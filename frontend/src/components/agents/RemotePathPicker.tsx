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
        Browse / test path
      </Button>
      {agent?.status !== 'online' && (
        <p className="text-xs text-destructive">
          The agent must be online before OneSearch can browse or test its path.
        </p>
      )}
      {result && (
        <p
          className={
            result.ok ? 'text-xs text-success' : 'text-xs text-destructive'
          }
        >
          {result.message}
          {result.status === 'pending'
            ? ' Directory browsing is still pending; allowed roots and manual entry remain available.'
            : ''}
        </p>
      )}
    </div>
  )
}
