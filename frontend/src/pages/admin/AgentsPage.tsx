import { useState } from 'react'
import { Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { AgentApproval } from '@/components/agents/AgentApproval'
import { AgentDetails } from '@/components/agents/AgentDetails'
import { useAgents, useApproveAgent, useCreateAgentEnrollment, useDisableAgent, useRevokeAgent, useUpdateAgentProcessingMode } from '@/hooks/useApi'
import type { Agent, AgentStatus } from '@/types/api'

const statusText: Record<AgentStatus, string> = { pending: 'Pending approval', online: 'Online', offline: 'Offline', degraded: 'Needs attention', disabled: 'Disabled', revoked: 'Revoked' }
export default function AgentsPage() {
  const agents = useAgents(); const enrollment = useCreateAgentEnrollment(); const approve = useApproveAgent(); const disable = useDisableAgent(); const revoke = useRevokeAgent(); const mode = useUpdateAgentProcessingMode()
  const [filter, setFilter] = useState<'all' | 'online' | 'attention'>('all'); const [selected, setSelected] = useState<Agent | null>(null)
  if (agents.isLoading) return <p className="text-muted-foreground">Loading agents…</p>
  if (agents.error) return <p className="text-destructive">Unable to load agents.</p>
  const list = agents.data ?? []; const visible = list.filter((a) => filter === 'all' || (filter === 'online' ? a.status === 'online' : a.status !== 'online'))
  const online = list.filter((a) => a.status === 'online').length
  return <div className="space-y-5 animate-fade-in"><div className="flex flex-wrap items-start justify-between gap-3"><div><h1 className="text-2xl font-bold">Remote agents</h1><p className="mt-1 text-sm text-muted-foreground">Offline agents’ indexed documents remain searchable.</p></div><Button onClick={() => enrollment.mutate()}><Plus className="mr-2 h-4 w-4" />Create enrollment code</Button></div>
    {enrollment.data && <div className="rounded-lg border border-brand/30 bg-brand/10 p-3 text-sm">Enrollment code: <code>{enrollment.data.code}</code> · expires {new Date(enrollment.data.expires_at).toLocaleString()}</div>}
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4"><Summary label="All agents" value={list.length} /><Summary label="Online" value={online} /><Summary label="Attention" value={list.length - online} /><Summary label="Pending" value={list.filter((a) => a.status === 'pending').length} /></div>
    <div className="flex gap-2">{(['all', 'online', 'attention'] as const).map((value) => <Button key={value} size="sm" variant={filter === value ? 'default' : 'secondary'} onClick={() => setFilter(value)}>{value === 'all' ? 'All' : value === 'online' ? 'Online' : 'Attention'}</Button>)}</div>
    {visible.length === 0 ? <div className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">No agents match this filter. Create an enrollment code to connect a machine.</div> : <div className="overflow-hidden rounded-lg border border-border"><table className="w-full text-sm"><thead className="bg-secondary/50 text-left"><tr><th className="p-3">Agent</th><th className="p-3">Status</th><th className="p-3 hidden sm:table-cell">Processing</th><th className="p-3" /></tr></thead><tbody>{visible.map((agent) => <tr key={agent.id} className="border-t border-border"><td className="p-3"><button className="text-left font-medium hover:text-brand" onClick={() => setSelected(agent)}>{agent.name}</button><span className="block text-xs text-muted-foreground">{agent.platform}</span></td><td className="p-3"><span className="inline-flex items-center gap-1"><span className={agent.status === 'online' ? 'h-2 w-2 rounded-full bg-success' : 'h-2 w-2 rounded-full bg-muted-foreground'} />{statusText[agent.status]}</span></td><td className="p-3 hidden sm:table-cell">{agent.default_processing_mode === 'on_agent' ? 'On agent' : 'On server'}</td><td className="p-3 text-right"><AgentApproval agent={agent} pending={approve.isPending} onApprove={() => approve.mutate(agent.id)} /></td></tr>)}</tbody></table></div>}
    {selected && <AgentDetails agent={selected} onDisable={() => disable.mutate(selected.id)} onRevoke={() => revoke.mutate(selected.id)} onMode={(selectedMode) => mode.mutate({ id: selected.id, mode: selectedMode })} />}
  </div>
}
function Summary({ label, value }: { label: string; value: number }) { return <div className="rounded-lg border border-border bg-card p-3"><p className="text-xs text-muted-foreground">{label}</p><p className="text-xl font-semibold">{value}</p></div> }
