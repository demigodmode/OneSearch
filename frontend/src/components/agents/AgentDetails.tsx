import { Button } from '@/components/ui/button'
import { agentHealthText } from './health'
import type {
  AgentDetails as AgentDetailsModel,
  ProcessingMode,
} from '@/types/api'

export function AgentDetails({
  agent,
  onClose,
  onApprove,
  approvalPending = false,
  actionPending = false,
  modePending = false,
  onDisable,
  onRevoke,
  onMode,
}: {
  agent: AgentDetailsModel
  onClose: () => void
  onApprove?: () => void
  approvalPending?: boolean
  actionPending?: boolean
  modePending?: boolean
  onDisable: () => void
  onRevoke: () => void
  onMode: (mode: ProcessingMode) => void
}) {
  return (
    <section
      className="rounded-lg border border-border bg-card p-4 space-y-4"
      aria-label={`${agent.name} details`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold">{agent.name}</h2>
          <p className="text-sm text-muted-foreground">
            {agent.platform} · v{agent.version} · protocol{' '}
            {agent.protocol_version} · last contact{' '}
            {agent.last_seen_at
              ? new Date(agent.last_seen_at).toLocaleString()
              : 'never'}
          </p>
        </div>
        <Button size="sm" variant="ghost" onClick={onClose}>
          Close
        </Button>
      </div>
      {agent.status === 'degraded' && agent.health && (
        <p className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm">
          {agentHealthText(agent.health)}
        </p>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <h3 className="text-sm font-medium">Allowed roots</h3>
          <ul className="text-sm text-muted-foreground">
            {agent.allowed_roots.map((root) => (
              <li key={root.root_id}>{root.path}</li>
            ))}
          </ul>
        </div>
        <div>
          <h3 className="text-sm font-medium">Attached sources</h3>
          {agent.sources.length ? (
            <ul className="text-sm text-muted-foreground">
              {agent.sources.map((source) => (
                <li key={source.id}>
                  {source.name}: {source.root_path}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">
              No attached sources.
            </p>
          )}
        </div>
      </div>
      <label className="block text-sm">
        Default processing mode
        <select
          disabled={approvalPending || actionPending || modePending}
          value={agent.default_processing_mode}
          onChange={(event) => onMode(event.target.value as ProcessingMode)}
          className="mt-1 block rounded-lg border border-border bg-background px-2 py-1"
        >
          <option value="on_agent">On agent</option>
          <option value="on_server">On server</option>
        </select>
      </label>
      <UpdateStatus agent={agent} />
      <div>
        <h3 className="text-sm font-medium">Recent jobs</h3>
        {agent.recent_jobs.length ? (
          <ul className="mt-1 space-y-1 text-sm text-muted-foreground">
            {agent.recent_jobs.map((job) => (
              <li key={job.id}>
                {job.kind}
                {job.reason ? ` · ${job.reason.split('_').join('-')}` : ''} · {job.status}
                {job.error ? ` — ${job.error}` : ''}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">No recent jobs.</p>
        )}
      </div>
      {(agent.status === 'pending' || agent.status === 'disabled') && onApprove && (
        <Button
          size="sm"
          onClick={onApprove}
          disabled={approvalPending || actionPending}
        >
          {approvalPending
            ? agent.status === 'disabled'
              ? 'Enabling…'
              : 'Approving…'
            : agent.status === 'disabled'
              ? 'Enable agent'
              : 'Approve agent'}
        </Button>
      )}
      {!['pending', 'disabled', 'revoked'].includes(agent.status) && (
        <div className="flex gap-2">
          <Button size="sm" variant="secondary" onClick={onDisable} disabled={actionPending || modePending}>
            Disable credential
          </Button>
          <Button size="sm" variant="destructive" onClick={onRevoke} disabled={actionPending || modePending}>
            Revoke credential
          </Button>
        </div>
      )}
    </section>
  )
}

function UpdateStatus({ agent }: { agent: AgentDetailsModel }) {
  const report = agent.update_report
  if (!report) {
    return <p className="text-sm text-muted-foreground">Update status has not been reported by this agent.</p>
  }
  const disclosure = <p className="text-xs text-muted-foreground">Startup and daily GitHub release-host metadata checks occur; only native automatic updates download signed artifacts.</p>
  if (report.runtime_kind === 'docker') {
    const status = report.status === 'available' ? `Image update ${report.available_version} is available.` : `Docker update status: ${report.status}.`
    return <div className="space-y-1 text-sm text-muted-foreground"><p>{status} Run: docker compose pull onesearch-agent && docker compose up -d onesearch-agent</p>{disclosure}</div>
  }
  if (report.status === 'available' && !report.auto_update) {
    return <div className="space-y-1 text-sm text-muted-foreground"><p>Automatic install is off. Run: onesearch-agent --config {'<config.toml>'} update check</p>{disclosure}</div>
  }
  return <div className="space-y-1 text-sm text-muted-foreground"><p>Native update status: {report.status}{report.available_version ? ` (${report.available_version})` : ''}.</p>{disclosure}</div>
}
