import { useEffect, useRef, useState } from 'react'
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
  actionError = null,
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
  actionError?: string | null
  onDisable: () => void
  onRevoke: (opts: { deleteSources: boolean }) => void
  onMode: (mode: ProcessingMode) => void
}) {
  const [dialogVariant, setDialogVariant] = useState<'revoke' | 'cleanup' | null>(null)
  const [deleteSources, setDeleteSources] = useState(false)
  const triggerRef = useRef<HTMLElement | null>(null)
  const [lastAgentId, setLastAgentId] = useState(agent.id)

  if (agent.id !== lastAgentId) {
    setLastAgentId(agent.id)
    setDialogVariant(null)
    setDeleteSources(false)
  }

  function openDialog(variant: 'revoke' | 'cleanup', trigger: HTMLElement) {
    triggerRef.current = trigger
    setDeleteSources(false)
    setDialogVariant(variant)
  }

  function closeDialog() {
    setDialogVariant(null)
    setDeleteSources(false)
    triggerRef.current?.focus()
  }

  function confirmDialog() {
    const variant = dialogVariant
    onRevoke({ deleteSources: variant === 'cleanup' ? true : deleteSources })
    setDialogVariant(null)
    setDeleteSources(false)
    triggerRef.current?.focus()
  }

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
          <Button size="sm" variant="destructive" onClick={(event) => openDialog('revoke', event.currentTarget)} disabled={actionPending || modePending}>
            Revoke credential
          </Button>
        </div>
      )}
      {agent.status === 'revoked' && agent.summary.attached_sources > 0 && (
        <div className="flex gap-2">
          <Button size="sm" variant="destructive" onClick={(event) => openDialog('cleanup', event.currentTarget)} disabled={actionPending}>
            Delete remaining sources
          </Button>
        </div>
      )}
      {dialogVariant && (
        <RevokeDialog
          variant={dialogVariant}
          deleteSources={deleteSources}
          onDeleteSourcesChange={setDeleteSources}
          onCancel={closeDialog}
          onConfirm={confirmDialog}
          actionPending={actionPending}
          actionError={actionError}
        />
      )}
    </section>
  )
}

function RevokeDialog({
  variant,
  deleteSources,
  onDeleteSourcesChange,
  onCancel,
  onConfirm,
  actionPending,
  actionError,
}: {
  variant: 'revoke' | 'cleanup'
  deleteSources: boolean
  onDeleteSourcesChange: (value: boolean) => void
  onCancel: () => void
  onConfirm: () => void
  actionPending: boolean
  actionError: string | null
}) {
  const headingId = 'agent-revoke-dialog-heading'
  const dialogRef = useRef<HTMLDivElement | null>(null)
  const firstRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    firstRef.current?.focus()
  }, [])

  function handleKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape') {
      event.preventDefault()
      onCancel()
      return
    }
    if (event.key !== 'Tab') return
    const dialog = dialogRef.current
    if (!dialog) return
    const focusables = Array.from(
      dialog.querySelectorAll<HTMLElement>('button, input, [tabindex]'),
    ).filter((el) => !el.hasAttribute('disabled'))
    if (focusables.length === 0) return
    const first = focusables[0]
    const last = focusables[focusables.length - 1]
    if (event.shiftKey) {
      if (document.activeElement === first) {
        event.preventDefault()
        last.focus()
      }
    } else if (document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby={headingId}
      onKeyDown={handleKeyDown}
      className="rounded-lg border border-border bg-card p-4 space-y-3"
    >
      <h3 id={headingId} className="font-semibold">
        {variant === 'cleanup' ? 'Delete remaining sources' : 'Revoke credential'}
      </h3>
      <p className="text-sm text-muted-foreground">
        {variant === 'cleanup'
          ? 'This agent is already revoked. Retry cleanup to remove its remaining sources.'
          : 'The agent will lose access immediately. This cannot be undone.'}
      </p>
      {variant === 'revoke' && (
        <label className="flex items-center gap-2 text-sm">
          <input
            ref={(el) => {
              firstRef.current = el
            }}
            type="checkbox"
            checked={deleteSources}
            onChange={(event) => onDeleteSourcesChange(event.target.checked)}
          />
          Also delete this agent's sources
        </label>
      )}
      {actionError && (
        <p className="text-sm text-destructive">{actionError}</p>
      )}
      <div className="flex gap-2 justify-end">
        <Button
          size="sm"
          variant="outline"
          onClick={onCancel}
          disabled={actionPending}
          ref={variant === 'cleanup' ? (el) => { firstRef.current = el } : undefined}
        >
          Cancel
        </Button>
        <Button size="sm" variant="destructive" onClick={onConfirm} disabled={actionPending}>
          {variant === 'cleanup' ? 'Confirm' : 'Confirm revoke'}
        </Button>
      </div>
    </div>
  )
}

function UpdateStatus({ agent }: { agent: AgentDetailsModel }) {
  const report = agent.update_report
  if (!report) {
    return <p className="text-sm text-muted-foreground">Update status has not been reported by this agent.</p>
  }
  // A build with no signing key can't check for updates at all. Say so plainly and do
  // not imply that notifications or self-updates are happening.
  if (report.status === 'not_configured') {
    return <p className="text-sm text-muted-foreground">Update checks aren't configured for this build.</p>
  }
  const historical = agent.status === 'offline'
  const isDocker = report.runtime_kind === 'docker'

  let line: string
  if (report.status === 'available') {
    line = isDocker
      ? `Image update ${report.available_version} is available. Docker agents never update themselves — pull the new image: docker compose pull onesearch-agent && docker compose up -d onesearch-agent`
      : report.auto_update
        ? `Update ${report.available_version} is available and will be installed automatically.`
        : `Update ${report.available_version} is available. Automatic install is off — run: onesearch-agent --config <config.toml> update check`
  } else if (report.status === 'current') {
    line = 'Up to date.'
  } else if (report.status === 'error') {
    line = `Update check failed (${report.error_code}).`
  } else {
    line = 'Not checked yet.'
  }

  // Install-type note: the docker-vs-native update path is the thing that confuses people.
  const note = isDocker
    ? 'Docker agents check for updates at startup and about daily, but never download or replace their own image — you pull the new image to update.'
    : report.auto_update
      ? 'Native agents check at startup and about daily and install signed updates automatically.'
      : 'Native agents check at startup and about daily; automatic install is off, so updates are notify-only.'

  return (
    <div className="space-y-1 text-sm text-muted-foreground">
      <p>{line}</p>
      <p className="text-xs text-muted-foreground">{note}</p>
      <p className="text-xs text-muted-foreground">{historical ? 'Historical update status — ' : ''}Last checked: {new Date(report.checked_at).toLocaleString()}</p>
    </div>
  )
}
