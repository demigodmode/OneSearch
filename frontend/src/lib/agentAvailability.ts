export type AgentAvailability = { unavailable: boolean; label: string; tone: 'warn' | 'danger' }

export function agentAvailability(status: string | null | undefined): AgentAvailability {
  switch (status) {
    case 'revoked': return { unavailable: true, label: 'Agent revoked', tone: 'danger' }
    case 'disabled': return { unavailable: true, label: 'Agent disabled', tone: 'warn' }
    case 'offline': return { unavailable: true, label: 'Agent offline', tone: 'warn' }
    default: return { unavailable: false, label: '', tone: 'warn' } // 'online' or null (local)
  }
}
