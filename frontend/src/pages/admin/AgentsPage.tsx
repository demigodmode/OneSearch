import { useEffect, useRef, useState } from 'react'
import { AlertCircle, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { AgentApproval } from '@/components/agents/AgentApproval'
import { AgentDetails } from '@/components/agents/AgentDetails'
import { agentHealthText } from '@/components/agents/health'
import {
  useAgent,
  useAgents,
  useApproveAgent,
  useAppSettings,
  useBoundedAgentRefresh,
  useCreateAgentEnrollment,
  useDisableAgent,
  useInvalidateAgentCaches,
  useRevokeAgent,
  useUpdateAgentProcessingMode,
  useUpdateAppSettings,
} from '@/hooks/useApi'
import type { Agent, AgentStatus } from '@/types/api'

const attentionStatuses: AgentStatus[] = ['pending', 'offline', 'degraded']
const statusText: Record<AgentStatus, string> = {
  pending: 'Pending approval',
  online: 'Online',
  offline: 'Offline',
  degraded: 'Degraded',
  disabled: 'Disabled',
  revoked: 'Revoked',
}

// After Enable/Disable, refetch a few times over this window instead of a
// permanent poll — enough chances to catch the agent's next heartbeat.
const REFRESH_DELAYS_MS = [2000, 5000, 10000, 20000, 30000]
// How long a just-enabled agent gets the calm "waiting for contact" treatment
// before a genuine outage is shown as a real offline state.
const ENABLE_GRACE_MS = 60000

export default function AgentsPage() {
  const refreshAll = useInvalidateAgentCaches()
  const settings = useAppSettings()
  const updateSettings = useUpdateAppSettings()
  const agents = useAgents()
  const enrollment = useCreateAgentEnrollment()
  const approve = useApproveAgent()
  const disable = useDisableAgent()
  const revoke = useRevokeAgent()
  const mode = useUpdateAgentProcessingMode()
  const [filter, setFilter] = useState<'all' | 'online' | 'attention'>('all')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  // On a successful revoke the whole details panel unmounts, so Radix can't
  // restore focus to the (now-gone) trigger. Move it to the page heading, a
  // surviving element, so keyboard focus doesn't fall to <body>.
  const headingRef = useRef<HTMLHeadingElement>(null)
  const detail = useAgent(selectedId ?? '')
  // Client-side record of which agents were just enabled — deliberately NOT
  // derived from approved_at, which the server preserves from the original
  // approval and doesn't move on re-enable. Membership (rather than a
  // stored timestamp compared against Date.now() during render) is what
  // drives the "waiting for contact" presentation, so the grace state is
  // set and cleared entirely from event handlers and timers.
  const [recentlyEnabledIds, setRecentlyEnabledIds] = useState<Set<string>>(
    new Set(),
  )
  const scheduleRefresh = useBoundedAgentRefresh()
  // Per-agent-id grace-end timers, keyed so enabling one agent doesn't
  // clobber another's still-pending grace window (unlike the bounded
  // refresh timers above, which are fine to share since refetch is global).
  const graceEndTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(
    new Map(),
  )

  useEffect(() => {
    const timers = graceEndTimers.current
    return () => {
      timers.forEach((timer) => clearTimeout(timer))
      timers.clear()
    }
  }, [])

  function isEnabledRecently(id: string) {
    return recentlyEnabledIds.has(id)
  }

  function afterAgentAction() {
    scheduleRefresh(() => {
      agents.refetch()
      detail.refetch()
    }, REFRESH_DELAYS_MS)
  }

  function afterEnable(id: string) {
    setRecentlyEnabledIds((prev) => new Set(prev).add(id))
    afterAgentAction()
    // Drop the grace flag once this agent's own window elapses so a still-
    // offline agent falls back to the real offline presentation, regardless
    // of whether other agents were enabled in the meantime.
    const existing = graceEndTimers.current.get(id)
    if (existing) clearTimeout(existing)
    const timer = setTimeout(() => {
      graceEndTimers.current.delete(id)
      setRecentlyEnabledIds((prev) => {
        if (!prev.has(id)) return prev
        const next = new Set(prev)
        next.delete(id)
        return next
      })
    }, ENABLE_GRACE_MS)
    graceEndTimers.current.set(id, timer)
  }

  if (settings.isLoading || agents.isLoading)
    return <p className="text-muted-foreground">Loading agents…</p>
  if (settings.error || agents.error)
    return (
      <p className="text-destructive">
        Unable to load remote-agent administration.
      </p>
    )
  if (!settings.data?.remote_agents_enabled)
    return (
      <section className="space-y-4">
        <h1 className="text-2xl font-bold">Agents</h1>
        <p className="text-sm text-muted-foreground">
          Remote agents are disabled for this instance.
        </p>
        <Button
          onClick={() => updateSettings.mutate({ remote_agents_enabled: true })}
        >
          Enable remote agents
        </Button>
        {updateSettings.error && <ErrorMessage error={updateSettings.error} />}
      </section>
    )

  const list = agents.data ?? []
  const attention = list.filter((agent) =>
    attentionStatuses.includes(agent.status),
  )
  const visible = list.filter(
    (agent) =>
      filter === 'all' ||
      (filter === 'online'
        ? agent.status === 'online'
        : attentionStatuses.includes(agent.status)),
  )
  const documents = list.reduce(
    (sum, agent) => sum + agent.summary.indexed_documents,
    0,
  )
  return (
    <div className="space-y-5 animate-fade-in">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 ref={headingRef} tabIndex={-1} className="text-2xl font-bold outline-none">
            Agents
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Connected machines provide remote sources; sources keep their own
            schedules.
          </p>
        </div>
        <Button
          onClick={() => enrollment.mutate()}
          disabled={enrollment.isPending}
        >
          <Plus className="mr-2 h-4 w-4" />
          Add agent enrollment
        </Button>
      </div>
      {enrollment.data && (
        <div className="rounded-lg border border-brand/30 bg-brand/10 p-3 text-sm">
          Enrollment code: <code>{enrollment.data.code}</code> · expires{' '}
          {new Date(enrollment.data.expires_at).toLocaleString()}
        </div>
      )}
      {enrollment.error && <ErrorMessage error={enrollment.error} />}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        <Summary label="Registered" value={list.length} />
        <Summary
          label="Online"
          value={list.filter((agent) => agent.status === 'online').length}
        />
        <Summary label="Attention" value={attention.length} />
        <Summary label="Remote documents" value={documents} />
        <Summary
          label="Pending jobs"
          value={list.reduce(
            (sum, agent) => sum + agent.summary.pending_jobs,
            0,
          )}
        />
      </div>
      {list
        .filter((agent) => agent.status === 'offline')
        .map((agent) =>
          isEnabledRecently(agent.id) ? (
            <p
              key={agent.id}
              className="rounded-lg border border-border bg-secondary/40 p-3 text-sm text-foreground"
            >
              <strong>{agent.name}</strong>: Enabled — waiting for contact.
              It was just re-enabled and should reconnect shortly.
            </p>
          ) : (
            <p
              key={agent.id}
              className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-foreground"
            >
              <strong>{agent.name}</strong> is offline; its{' '}
              {agent.summary.indexed_documents} indexed documents remain
              searchable. Last contact: {formatContact(agent.last_seen_at)}.
              Original files need the agent to reconnect.
            </p>
          ),
        )}
      <div className="flex flex-wrap gap-2" aria-label="Agent filters">
        {(
          [
            { value: 'all', label: 'All', count: list.length },
            {
              value: 'online',
              label: 'Online',
              count: list.filter((agent) => agent.status === 'online').length,
            },
            { value: 'attention', label: 'Attention', count: attention.length },
          ] as const
        ).map((item) => (
          <Button
            key={item.value}
            size="sm"
            variant={filter === item.value ? 'default' : 'secondary'}
            onClick={() => setFilter(item.value)}
          >
            {item.label} ({item.count})
          </Button>
        ))}
      </div>
      {visible.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
          No agents match this filter. Add an enrollment code to connect a
          machine.
        </div>
      ) : (
        <div className="grid gap-3 lg:hidden">
          {visible.map((agent) => (
            <AgentCard
              key={agent.id}
              agent={agent}
              onSelect={() => setSelectedId(agent.id)}
              onApprove={() =>
                approve.mutate(agent.id, { onSuccess: () => afterEnable(agent.id) })
              }
              approving={approve.isPending}
            />
          ))}
        </div>
      )}
      {visible.length > 0 && (
        <div className="hidden overflow-x-auto rounded-lg border border-border lg:block">
          <table className="w-full text-sm">
            <thead className="bg-secondary/50 text-left">
              <tr>
                <th className="p-3">Agent</th>
                <th className="p-3">Status</th>
                <th className="p-3">Sources</th>
                <th className="p-3">Next activity</th>
                <th className="p-3">Default</th>
                <th className="p-3">Version</th>
                <th className="p-3">Last contact</th>
                <th className="p-3" />
              </tr>
            </thead>
            <tbody>
              {visible.map((agent) => (
                <tr key={agent.id} className="border-t border-border">
                  <td className="p-3">
                    <button
                      className="font-medium hover:text-brand"
                      onClick={() => setSelectedId(agent.id)}
                    >
                      {agent.name}
                    </button>
                  </td>
                  <td className="p-3">
                    <Status agent={agent} />
                  </td>
                  <td className="p-3">{agent.summary.attached_sources}</td>
                  <td className="p-3">{nextActivity(agent)}</td>
                  <td className="p-3">
                    {agent.default_processing_mode === 'on_agent'
                      ? 'On agent'
                      : 'On server'}
                  </td>
                  <td className="p-3">{agent.version}</td>
                  <td className="p-3">{formatContact(agent.last_seen_at)}</td>
                  <td className="p-3">
                    <AgentApproval
                      agent={agent}
                      pending={approve.isPending}
                      onApprove={() =>
                        approve.mutate(agent.id, {
                          onSuccess: () => afterEnable(agent.id),
                        })
                      }
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {(approve.error || disable.error || revoke.error || mode.error) && (
        <ErrorMessage
          error={approve.error ?? disable.error ?? revoke.error ?? mode.error}
        />
      )}
      {selectedId && detail.isLoading && (
        <p className="text-sm text-muted-foreground">Loading agent details…</p>
      )}
      {selectedId && detail.data && (
        <AgentDetails
          agent={detail.data}
          onClose={() => setSelectedId(null)}
          onApprove={() =>
            approve.mutate(selectedId, {
              onSuccess: () => {
                detail.refetch()
                afterEnable(selectedId)
              },
            })
          }
          approvalPending={approve.isPending}
          actionPending={disable.isPending || revoke.isPending}
          modePending={mode.isPending}
          onDisable={() =>
            disable.mutate(selectedId, {
              onSuccess: () => {
                detail.refetch()
                afterAgentAction()
              },
            })
          }
          onRevoke={({ deleteSources }) =>
            revoke.mutate(
              { id: selectedId, deleteSources },
              {
                onSuccess: () => {
                  refreshAll()
                  setSelectedId(null)
                  // Panel just unmounted — land focus on a surviving element.
                  requestAnimationFrame(() => headingRef.current?.focus())
                },
                onError: () => refreshAll(),
              },
            )
          }
          actionError={
            revoke.isError
              ? 'Revoke/cleanup failed — some sources may remain. Retry "Delete remaining sources".'
              : null
          }
          onMode={(selectedMode) =>
            mode.mutate(
              { id: selectedId, mode: selectedMode },
              { onSuccess: () => detail.refetch() },
            )
          }
        />
      )}
      {selectedId && detail.error && <ErrorMessage error={detail.error} />}
    </div>
  )
}

function AgentCard({
  agent,
  onSelect,
  onApprove,
  approving,
}: {
  agent: Agent
  onSelect: () => void
  onApprove: () => void
  approving: boolean
}) {
  return (
    <article className="rounded-lg border border-border bg-card p-4 space-y-2">
      <div className="flex justify-between gap-2">
        <button
          className="font-semibold text-left hover:text-brand"
          onClick={onSelect}
        >
          {agent.name}
        </button>
        <Status agent={agent} />
      </div>
      <p className="text-xs text-muted-foreground">
        {agent.summary.attached_sources} sources ·{' '}
        {agent.summary.indexed_documents} retained documents ·{' '}
        {nextActivity(agent)}
      </p>
      <p className="text-xs text-muted-foreground">
        v{agent.version} · last contact {formatContact(agent.last_seen_at)}
      </p>
      <AgentApproval agent={agent} pending={approving} onApprove={onApprove} />
    </article>
  )
}
function Status({ agent }: { agent: Agent }) {
  const color =
    agent.status === 'online'
      ? 'bg-success'
      : attentionStatuses.includes(agent.status)
        ? 'bg-amber-500'
        : 'bg-muted-foreground'
  return (
    <span className="inline-flex flex-col items-start gap-0.5">
      <span className="inline-flex items-center gap-1">
        <span aria-hidden="true" className={`h-2 w-2 rounded-full ${color}`} />
        {statusText[agent.status]}
      </span>
      {agent.status === 'degraded' && agent.health && (
        <span className="max-w-56 text-xs text-muted-foreground">
          {agentHealthText(agent.health)}
        </span>
      )}
    </span>
  )
}
function Summary({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-xl font-semibold">{value}</p>
    </div>
  )
}
function formatContact(value: string | null) {
  return value ? new Date(value).toLocaleString() : 'Never'
}
function nextActivity(agent: Agent) {
  return agent.summary.active_jobs
    ? `${agent.summary.active_jobs} active job${agent.summary.active_jobs === 1 ? '' : 's'}`
    : agent.summary.pending_jobs
      ? `${agent.summary.pending_jobs} pending job${agent.summary.pending_jobs === 1 ? '' : 's'}`
      : agent.summary.earliest_next_scan_at
        ? new Date(agent.summary.earliest_next_scan_at).toLocaleString()
        : 'No scheduled activity'
}
function ErrorMessage({ error }: { error: unknown }) {
  return (
    <p className="flex items-center gap-2 text-sm text-destructive">
      <AlertCircle className="h-4 w-4" />
      {error instanceof Error
        ? error.message
        : 'The requested action could not be completed.'}
    </p>
  )
}
