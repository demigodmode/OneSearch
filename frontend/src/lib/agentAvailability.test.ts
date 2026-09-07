import { describe, expect, it } from 'vitest'
import { agentAvailability } from './agentAvailability'

describe('agentAvailability', () => {
  it('treats online and local (null) as available', () => {
    expect(agentAvailability(null).unavailable).toBe(false)
    expect(agentAvailability('online').unavailable).toBe(false)
  })
  it('labels unavailable states', () => {
    expect(agentAvailability('offline')).toMatchObject({ unavailable: true, label: 'Agent offline', tone: 'warn' })
    expect(agentAvailability('disabled')).toMatchObject({ unavailable: true, label: 'Agent disabled', tone: 'warn' })
    expect(agentAvailability('revoked')).toMatchObject({ unavailable: true, label: 'Agent revoked', tone: 'danger' })
  })
})
