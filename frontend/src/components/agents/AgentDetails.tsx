import { Button } from '@/components/ui/button'
import type { Agent, ProcessingMode } from '@/types/api'

export function AgentDetails({ agent, onDisable, onRevoke, onMode }: { agent: Agent; onDisable: () => void; onRevoke: () => void; onMode: (mode: ProcessingMode) => void }) {
  return <section className="rounded-lg border border-border bg-card p-4 space-y-3" aria-label={`${agent.name} details`}>
    <div><h2 className="font-semibold">{agent.name}</h2><p className="text-sm text-muted-foreground">{agent.platform} · v{agent.version} · protocol {agent.protocol_version}</p></div>
    <label className="block text-sm">Default processing mode
      <select value={agent.default_processing_mode} onChange={(event) => onMode(event.target.value as ProcessingMode)} className="mt-1 block rounded-lg border border-border bg-background px-2 py-1">
        <option value="on_agent">On agent</option><option value="on_server">On server</option>
      </select>
    </label>
    <p className="text-xs text-muted-foreground">Allowed roots: {agent.allowed_roots.map((root) => root.path).join(', ') || 'none'}</p>
    {agent.status !== 'revoked' && <div className="flex gap-2"><Button size="sm" variant="secondary" onClick={onDisable}>Disable</Button><Button size="sm" variant="destructive" onClick={onRevoke}>Revoke</Button></div>}
  </section>
}
