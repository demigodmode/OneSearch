import { Badge } from '@/components/ui/badge'
import { agentAvailability } from '@/lib/agentAvailability'

/**
 * One consistent badge for a source/hit whose backing agent is unavailable
 * (offline / disabled / revoked). Renders nothing for local or online sources.
 * The visible label carries the meaning (no title-only affordance); the optional
 * hover title adds the download caveat.
 */
export function AgentUnavailableBadge({
  status,
  className,
}: {
  status: string | null | undefined
  className?: string
}) {
  const availability = agentAvailability(status)
  if (!availability.unavailable) return null
  return (
    <Badge
      variant={availability.tone === 'danger' ? 'destructive' : 'warning'}
      className={className}
      title="The original file can't be downloaded until the agent is back online."
    >
      {availability.label}
    </Badge>
  )
}
