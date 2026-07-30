import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { SourceForm } from './SourcesPage'

const testPath = vi.fn()
vi.mock('@/hooks/useApi', async () => {
  const actual = await vi.importActual<typeof import('@/hooks/useApi')>('@/hooks/useApi')
  return { ...actual, useTestSourcePath: () => ({ mutate: testPath, isPending: false }) }
})

const agent = { id: 'agent-1', name: 'Online agent', platform: 'linux', version: '1', protocol_version: 1, allowed_roots: [{ root_id: 'docs', path: '/srv/docs' }], default_processing_mode: 'on_agent' as const, auto_update: false, status: 'online' as const, approved_at: '2026-01-01T00:00:00Z', last_seen_at: null, disabled_at: null, created_at: '', updated_at: '', summary: { attached_sources: 0, indexed_documents: 0, pending_jobs: 0, active_jobs: 0, failed_jobs: 0, earliest_next_scan_at: null } }

describe('SourceForm remote source flow', () => {
  it('allows an advertised root plus manual subpath after queued remote validation', () => {
    const submit = vi.fn()
    render(<SourceForm remoteAgentsEnabled agents={[agent]} defaultSchedule={null} onSubmit={submit} onCancel={vi.fn()} isLoading={false} />)
    fireEvent.click(screen.getByLabelText('Remote agent'))
    fireEvent.change(screen.getByLabelText('Approved agent'), { target: { value: 'agent-1' } })
    fireEvent.change(screen.getByLabelText('Allowed root'), { target: { value: '/srv/docs' } })
    fireEvent.change(screen.getByLabelText('Remote path'), { target: { value: '/srv/docs/team' } })
    fireEvent.click(screen.getByRole('button', { name: 'Browse / test path' }))
    const callbacks = testPath.mock.calls[0][1]
    callbacks.onSuccess({ ok: false, status: 'pending', message: 'Queued', path: '/srv/docs/team', exists: false, is_directory: false, readable: false, inside_allowed_roots: true, allowed_roots: ['/srv/docs'], looks_like_host_path: false })
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Team docs' } })
    expect(screen.getByRole('button', { name: 'Add Source' })).not.toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Add Source' }))
    expect(submit).toHaveBeenCalledWith(expect.objectContaining({ location_type: 'agent', agent_id: 'agent-1', root_path: '/srv/docs/team', processing_mode: null }))
  })

  it('hides remote location controls while the feature is disabled', () => {
    render(<SourceForm remoteAgentsEnabled={false} agents={[agent]} defaultSchedule={null} onSubmit={vi.fn()} onCancel={vi.fn()} isLoading={false} />)
    expect(screen.queryByLabelText('Remote agent')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Root Path')).toBeInTheDocument()
  })
})
