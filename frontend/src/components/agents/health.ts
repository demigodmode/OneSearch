import type { AgentAdminHealth } from '@/types/api'

export function agentHealthText(health: AgentAdminHealth | null) {
  if (!health) return null
  const count = `${health.affected_sources}${health.truncated ? '+' : ''}`
  const sources = health.affected_sources === 1 && !health.truncated ? 'source' : 'sources'
  return `${count} ${sources} had indexing failures in the last 24 hours.`
}
