import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, Check, Copy } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Separator } from '@/components/ui/separator'
import { agentHealthText } from './health'
import type {
  AgentDetails as AgentDetailsModel,
  AgentJobSummary,
  ProcessingMode,
} from '@/types/api'

// Statuses the agent job API is known to send. Anything else falls back to a
// neutral badge so an unrecognized status never disappears silently.
const JOB_STATUS_BADGE: Record<string, { label: string; className: string }> = {
  completed: { label: 'Completed', className: 'border-transparent bg-success/15 text-success-strong' },
  succeeded: { label: 'Succeeded', className: 'border-transparent bg-success/15 text-success-strong' },
  running: { label: 'Running', className: 'border-transparent bg-warning/15 text-warning-strong' },
  in_progress: { label: 'In progress', className: 'border-transparent bg-warning/15 text-warning-strong' },
  pending: { label: 'Pending', className: 'border-transparent bg-muted text-muted-foreground' },
  queued: { label: 'Queued', className: 'border-transparent bg-muted text-muted-foreground' },
  failed: { label: 'Failed', className: 'border-transparent bg-destructive/15 text-destructive-strong' },
  error: { label: 'Error', className: 'border-transparent bg-destructive/15 text-destructive-strong' },
}

function jobStatusBadge(status: string) {
  return (
    JOB_STATUS_BADGE[status] ?? {
      label: status.charAt(0).toUpperCase() + status.slice(1),
      className: 'border-transparent bg-muted text-muted-foreground',
    }
  )
}

function JobRow({ job }: { job: AgentJobSummary }) {
  const badge = jobStatusBadge(job.status)
  const timestamp = job.completed_at ?? job.created_at
  return (
    <li className="flex flex-wrap items-center gap-x-2 gap-y-1 py-0.5">
      <span className="text-foreground">
        {job.kind}
        {job.reason ? ` · ${job.reason.split('_').join('-')}` : ''}
      </span>
      <Badge variant="outline" className={badge.className}>
        {badge.label}
      </Badge>
      <span className="text-xs text-muted-foreground">
        {timestamp ? new Date(timestamp).toLocaleString() : ''}
      </span>
      {job.error && <span className="w-full text-xs text-destructive">{job.error}</span>}
    </li>
  )
}

function MetaChip({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-border bg-muted/40 px-2 py-0.5 text-xs">
      <span className="font-medium text-muted-foreground">{label}</span>
      <span className="text-foreground">{value}</span>
    </span>
  )
}

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
  const sectionRef = useRef<HTMLElement | null>(null)
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

  function cancelDialog() {
    // Cancel / Escape / overlay: the agent is untouched, so the trigger is still
    // mounted. Radix will restore focus to it (see handleCloseAutoFocus).
    setDialogVariant(null)
    setDeleteSources(false)
  }

  function confirmDialog() {
    // Fire the mutation but KEEP the dialog open. It's async: on success the
    // parent unmounts this whole panel (setSelectedId(null)), so the dialog
    // disappears with it and AgentsPage moves focus to its heading. On failure
    // the dialog stays open with actionError visible so the user sees the error
    // in context and can retry — and the delete-sources checkbox is preserved.
    // Buttons are disabled while actionPending, which also blocks double submit.
    onRevoke({ deleteSources: dialogVariant === 'cleanup' ? true : deleteSources })
  }

  // Radix fires this on the dialog's close AND on its unmount. On cancel/escape
  // the agent is untouched so the trigger is still mounted — restore focus to it.
  // On a *successful* revoke/cleanup the parent unmounts this whole panel, so the
  // trigger is detached by the time this runs; skip it (focusing a detached node
  // would only blur AgentsPage's heading, which it just focused via rAF).
  function handleCloseAutoFocus(event: Event) {
    event.preventDefault()
    const trigger = triggerRef.current
    if (trigger?.isConnected) trigger.focus()
  }

  return (
    <section
      ref={sectionRef}
      tabIndex={-1}
      className="rounded-lg border border-border bg-card p-4 space-y-4 outline-none"
      aria-label={`${agent.name} details`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold">{agent.name}</h2>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            <MetaChip label="OS" value={agent.platform} />
            <MetaChip label="Version" value={`v${agent.version}`} />
            <MetaChip label="Protocol" value={String(agent.protocol_version)} />
            <MetaChip
              label="Last contact"
              value={
                agent.last_seen_at
                  ? new Date(agent.last_seen_at).toLocaleString()
                  : 'never'
              }
            />
          </div>
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
      <Separator />
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
      <Separator />
      <UpdateStatus agent={agent} />
      <Separator />
      <div>
        <h3 className="text-sm font-medium">Recent jobs</h3>
        {agent.recent_jobs.length ? (
          <ul className="mt-1 space-y-1 text-sm">
            {agent.recent_jobs.map((job) => (
              <JobRow key={job.id} job={job} />
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
      <RevokeDialog
        open={dialogVariant !== null}
        variant={dialogVariant ?? 'revoke'}
        deleteSources={deleteSources}
        onDeleteSourcesChange={setDeleteSources}
        onOpenChange={(open) => {
          // Don't let escape / outside-click / the X dismiss a revoke that's
          // in flight — dismissing would hide a later in-dialog failure.
          if (actionPending) return
          if (!open) cancelDialog()
        }}
        onConfirm={confirmDialog}
        onCloseAutoFocus={handleCloseAutoFocus}
        actionPending={actionPending}
        actionError={actionError}
      />
    </section>
  )
}

function RevokeDialog({
  open,
  variant,
  deleteSources,
  onDeleteSourcesChange,
  onOpenChange,
  onConfirm,
  onCloseAutoFocus,
  actionPending,
  actionError,
}: {
  open: boolean
  variant: 'revoke' | 'cleanup'
  deleteSources: boolean
  onDeleteSourcesChange: (value: boolean) => void
  onOpenChange: (open: boolean) => void
  onConfirm: () => void
  onCloseAutoFocus: (event: Event) => void
  actionPending: boolean
  actionError: string | null
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="sm:max-w-md"
        onCloseAutoFocus={onCloseAutoFocus}
        onEscapeKeyDown={(event) => {
          if (actionPending) event.preventDefault()
        }}
        onInteractOutside={(event) => {
          if (actionPending) event.preventDefault()
        }}
      >
        <DialogHeader>
          <DialogTitle>
            {variant === 'cleanup' ? 'Delete remaining sources' : 'Revoke credential'}
          </DialogTitle>
          <DialogDescription>
            {variant === 'cleanup'
              ? 'This agent is already revoked. Retry cleanup to remove its remaining sources.'
              : 'The agent will lose access immediately. This cannot be undone.'}
          </DialogDescription>
        </DialogHeader>
        {variant === 'revoke' && (
          <label className="flex items-center gap-2 text-sm">
            <input
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
        <DialogFooter>
          <Button
            size="sm"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={actionPending}
          >
            Cancel
          </Button>
          <Button size="sm" variant="destructive" onClick={onConfirm} disabled={actionPending}>
            {variant === 'cleanup' ? 'Confirm' : 'Confirm revoke'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

const DOCKER_UPDATE_COMMAND = 'docker compose pull onesearch-agent && docker compose up -d onesearch-agent'

function CopyCommand({ command }: { command: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle')

  useEffect(() => {
    if (state === 'idle') return
    const timer = setTimeout(() => setState('idle'), 2000)
    return () => clearTimeout(timer)
  }, [state])

  async function handleCopy() {
    try {
      if (!navigator.clipboard?.writeText) {
        throw new Error('Clipboard API unavailable')
      }
      await navigator.clipboard.writeText(command)
      setState('copied')
    } catch {
      setState('failed')
    }
  }

  return (
    <div className="mt-1.5 flex items-start gap-2">
      <pre className="min-w-0 flex-1 overflow-x-auto rounded-md border border-border bg-muted/40 p-2 text-xs">
        <code>{command}</code>
      </pre>
      <Button
        size="sm"
        variant="outline"
        onClick={handleCopy}
        aria-label="Copy command"
        className="shrink-0"
      >
        <span aria-live="polite" className="inline-flex items-center gap-1.5">
          {state === 'copied' ? (
            <>
              <Check className="h-3.5 w-3.5" aria-hidden />
              Copied
            </>
          ) : state === 'failed' ? (
            'Copy failed'
          ) : (
            <>
              <Copy className="h-3.5 w-3.5" aria-hidden />
              Copy
            </>
          )}
        </span>
      </Button>
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
  const showDockerCommand = isDocker && report.status === 'available'

  let line: string
  if (report.status === 'available') {
    line = isDocker
      ? `Image update ${report.available_version} is available. Docker agents never update themselves — pull the new image below.`
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
      <p
        className={`flex items-start gap-1.5 ${
          report.status === 'error'
            ? 'text-destructive'
            : report.status === 'available'
              ? 'text-foreground'
              : ''
        }`}
      >
        {report.status === 'error' && (
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
        )}
        <span>{line}</span>
      </p>
      {showDockerCommand && <CopyCommand command={DOCKER_UPDATE_COMMAND} />}
      <p className="text-xs text-muted-foreground">{note}</p>
      <p className="text-xs text-muted-foreground">{historical ? 'Historical update status — ' : ''}Last checked: {new Date(report.checked_at).toLocaleString()}</p>
    </div>
  )
}
