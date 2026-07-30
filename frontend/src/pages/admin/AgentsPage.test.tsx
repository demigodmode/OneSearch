import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AgentsPage from './AgentsPage'

const hooks = vi.hoisted(() => ({ updateSettings: vi.fn(), approve: vi.fn(), enrollment: vi.fn(), mode: vi.fn() }))
const online = { id: 'online', name: 'Online agent', platform: 'linux', version: '1', protocol_version: 2, allowed_roots: [], default_processing_mode: 'on_agent' as const, auto_update: false, status: 'online' as const, approved_at: null, last_seen_at: null, disabled_at: null, created_at: '', updated_at: '', summary: { attached_sources: 1, indexed_documents: 3, pending_jobs: 0, active_jobs: 0, failed_jobs: 0, earliest_next_scan_at: null } }
const offline = { ...online, id: 'offline', name: 'Offline agent', status: 'offline' as const, summary: { ...online.summary, indexed_documents: 7 } }
const pending = { ...online, id: 'pending', name: 'Pending agent', status: 'pending' as const }
let enabled = true
vi.mock('@/hooks/useApi', () => ({
  useAppSettings: () => ({ data: { remote_agents_enabled: enabled }, isLoading: false, error: null }),
  useUpdateAppSettings: () => ({ mutate: hooks.updateSettings, isPending: false, error: null }),
  useAgents: () => ({ data: [online, offline, pending], isLoading: false, error: null }),
  useCreateAgentEnrollment: () => ({ mutate: hooks.enrollment, isPending: false, data: null, error: null }),
  useApproveAgent: () => ({ mutate: hooks.approve, isPending: false, error: null }),
  useDisableAgent: () => ({ mutate: vi.fn(), error: null }), useRevokeAgent: () => ({ mutate: vi.fn(), error: null }),
  useUpdateAgentProcessingMode: () => ({ mutate: hooks.mode, error: null }), useAgent: () => ({ data: null, error: null, refetch: vi.fn() }),
}))

describe('AgentsPage user flows', () => {
  beforeEach(() => { enabled = true; vi.clearAllMocks() })
  it('filters attention to pending and offline agents while showing retained documents', () => {
    render(<AgentsPage />)
    expect(screen.getByText('Remote documents')).toBeInTheDocument()
    expect(screen.getByText('13')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Attention (2)' }))
    expect(screen.getAllByText('Offline agent')).toHaveLength(3)
    expect(screen.getAllByText('Pending agent')).toHaveLength(2)
    expect(screen.queryByText('Online agent')).not.toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button', { name: 'Approve agent' })[0])
    expect(hooks.approve).toHaveBeenCalledWith('pending')
  })
  it('offers and persists the feature toggle when remote agents are disabled', () => {
    enabled = false
    render(<AgentsPage />)
    fireEvent.click(screen.getByRole('button', { name: 'Enable remote agents' }))
    expect(hooks.updateSettings).toHaveBeenCalledWith({ remote_agents_enabled: true })
  })
})
