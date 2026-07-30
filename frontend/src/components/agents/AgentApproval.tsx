import { Button } from '@/components/ui/button'
import type { Agent } from '@/types/api'

export function AgentApproval({
  agent,
  onApprove,
  pending,
}: {
  agent: Agent
  onApprove: () => void
  pending: boolean
}) {
  if (agent.status !== 'pending' && agent.status !== 'disabled') return null

  const label = agent.status === 'disabled' ? 'Enable agent' : 'Approve agent'
  return (
    <Button size="sm" onClick={onApprove} disabled={pending}>
      {pending ? `${agent.status === 'disabled' ? 'Enabling' : 'Approving'}…` : label}
    </Button>
  )
}
