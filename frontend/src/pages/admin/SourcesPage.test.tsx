import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SourceForm } from './SourcesPage'
import { ApiError } from '@/lib/api'

const testPath = vi.fn()
let mutationPending = false
vi.mock('@/hooks/useApi', async () => {
  const actual = await vi.importActual<typeof import('@/hooks/useApi')>('@/hooks/useApi')
  return { ...actual, useTestSourcePath: () => ({ mutate: testPath, isPending: mutationPending }) }
})

const agent = { id: 'agent-1', name: 'Online agent', platform: 'linux', version: '1', protocol_version: 1, allowed_roots: [{ root_id: 'docs', path: '/srv/docs' }], default_processing_mode: 'on_agent' as const, auto_update: false, status: 'online' as const, approved_at: '2026-01-01T00:00:00Z', last_seen_at: null, disabled_at: null, created_at: '', updated_at: '', health: null, summary: { attached_sources: 0, indexed_documents: 0, pending_jobs: 0, active_jobs: 0, failed_jobs: 0, earliest_next_scan_at: null } }

describe('SourceForm remote source flow', () => {
  beforeEach(() => { testPath.mockReset(); mutationPending = false })
  it('shows a successful local test started from a blank path', () => {
    render(<SourceForm remoteAgentsEnabled agents={[]} defaultSchedule={null} onSubmit={vi.fn()} onCancel={vi.fn()} isLoading={false} />)
    fireEvent.change(screen.getByLabelText('Root Path'), { target: { value: '/data/documents' } })
    fireEvent.click(screen.getByRole('button', { name: 'Test' }))
    act(() => testPath.mock.calls[testPath.mock.calls.length - 1][1].onSuccess({ ok: true, message: 'Ready', path: '/data/documents', exists: true, is_directory: true, readable: true, inside_allowed_roots: true, allowed_roots: ['/data'], looks_like_host_path: false }))
    expect(screen.getByText('Ready')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Ready')
  })

  it('announces local validation failure as an alert', () => {
    render(<SourceForm remoteAgentsEnabled agents={[]} defaultSchedule={null} onSubmit={vi.fn()} onCancel={vi.fn()} isLoading={false} />)
    fireEvent.change(screen.getByLabelText('Root Path'), { target: { value: '/data/missing' } })
    fireEvent.click(screen.getByRole('button', { name: 'Test' }))
    act(() => testPath.mock.calls[testPath.mock.calls.length - 1][1].onError(new Error('path unavailable')))
    expect(screen.getByRole('alert')).toHaveTextContent('path unavailable')
  })

  it('ignores a late local test error after its path changes', () => {
    render(<SourceForm remoteAgentsEnabled agents={[]} defaultSchedule={null} onSubmit={vi.fn()} onCancel={vi.fn()} isLoading={false} />)
    fireEvent.change(screen.getByLabelText('Root Path'), { target: { value: '/data/old' } })
    fireEvent.click(screen.getByRole('button', { name: 'Test' }))
    const oldRequest = testPath.mock.calls[testPath.mock.calls.length - 1][1]
    fireEvent.change(screen.getByLabelText('Root Path'), { target: { value: '/data/new' } })
    act(() => oldRequest.onError(new Error('old failure')))
    expect(screen.queryByText('old failure')).not.toBeInTheDocument()
  })

  it('ignores a late local test result after its path changes', () => {
    render(<SourceForm remoteAgentsEnabled agents={[]} defaultSchedule={null} onSubmit={vi.fn()} onCancel={vi.fn()} isLoading={false} />)
    fireEvent.change(screen.getByLabelText('Root Path'), { target: { value: '/data/old' } })
    fireEvent.click(screen.getByRole('button', { name: 'Test' }))
    const oldRequest = testPath.mock.calls[testPath.mock.calls.length - 1][1]
    fireEvent.change(screen.getByLabelText('Root Path'), { target: { value: '/data/new' } })
    act(() => oldRequest.onSuccess({ ok: true, message: 'old ready', path: '/data/old', exists: true, is_directory: true, readable: true, inside_allowed_roots: true, allowed_roots: ['/data'], looks_like_host_path: false }))
    expect(screen.queryByText('old ready')).not.toBeInTheDocument()
  })

  it('lets a new path test supersede a pending request and only accepts the newest result', () => {
    testPath.mockImplementation(() => { mutationPending = true })
    render(<SourceForm remoteAgentsEnabled agents={[]} defaultSchedule={null} onSubmit={vi.fn()} onCancel={vi.fn()} isLoading={false} />)
    fireEvent.change(screen.getByLabelText('Root Path'), { target: { value: '/data/a' } })
    fireEvent.click(screen.getByRole('button', { name: 'Test' }))
    const requestA = testPath.mock.calls[0][1]
    fireEvent.change(screen.getByLabelText('Root Path'), { target: { value: '/data/b' } })
    expect(screen.getByRole('button', { name: 'Test' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Test' }))
    const requestB = testPath.mock.calls[1][1]
    act(() => requestA.onSuccess({ ok: true, message: 'A ready', path: '/data/a', exists: true, is_directory: true, readable: true, inside_allowed_roots: true, allowed_roots: ['/data'], looks_like_host_path: false }))
    expect(screen.queryByText('A ready')).not.toBeInTheDocument()
    act(() => requestB.onSuccess({ ok: true, message: 'B ready', path: '/data/b', exists: true, is_directory: true, readable: true, inside_allowed_roots: true, allowed_roots: ['/data'], looks_like_host_path: false }))
    expect(screen.getByRole('status')).toHaveTextContent('B ready')
  })

  it('lets agent and location changes abandon a pending remote test', () => {
    testPath.mockImplementation(() => { mutationPending = true })
    render(<SourceForm remoteAgentsEnabled agents={[agent, { ...agent, id: 'agent-2', name: 'Other agent' }]} defaultSchedule={null} onSubmit={vi.fn()} onCancel={vi.fn()} isLoading={false} />)
    fireEvent.click(screen.getByLabelText('Remote agent'))
    fireEvent.change(screen.getByLabelText('Approved agent'), { target: { value: 'agent-1' } })
    fireEvent.change(screen.getByLabelText('Remote path'), { target: { value: '/srv/docs/a' } })
    fireEvent.click(screen.getByRole('button', { name: 'Test path' }))
    fireEvent.change(screen.getByLabelText('Approved agent'), { target: { value: 'agent-2' } })
    fireEvent.change(screen.getByLabelText('Remote path'), { target: { value: '/srv/docs/b' } })
    expect(screen.getByRole('button', { name: 'Test path' })).toBeEnabled()
    fireEvent.click(screen.getByLabelText('Local'))
    expect(screen.getByRole('button', { name: 'Test' })).toBeEnabled()
  })
  it('requires completed remote validation before saving a new path', () => {
    const submit = vi.fn()
    render(<SourceForm remoteAgentsEnabled agents={[agent]} defaultSchedule={null} onSubmit={submit} onCancel={vi.fn()} isLoading={false} />)
    fireEvent.click(screen.getByLabelText('Remote agent'))
    fireEvent.change(screen.getByLabelText('Approved agent'), { target: { value: 'agent-1' } })
    fireEvent.change(screen.getByLabelText('Allowed root'), { target: { value: '/srv/docs' } })
    fireEvent.change(screen.getByLabelText('Remote path'), { target: { value: '/srv/docs/team' } })
    fireEvent.click(screen.getByRole('button', { name: 'Test path' }))
    const callbacks = testPath.mock.calls[0][1]
    act(() => callbacks.onSuccess({ ok: false, status: 'pending', message: 'Queued', path: '/srv/docs/team', exists: false, is_directory: false, readable: false, inside_allowed_roots: true, allowed_roots: ['/srv/docs'], looks_like_host_path: false }))
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Team docs' } })
    expect(screen.getByRole('button', { name: 'Add Source' })).toBeDisabled()
    act(() => callbacks.onSuccess({ ok: true, status: 'completed', job_id: 'validation-job', message: 'Ready', path: '/srv/docs/team', exists: true, is_directory: true, readable: true, inside_allowed_roots: true, allowed_roots: ['/srv/docs'], looks_like_host_path: false }))
    expect(screen.getByRole('button', { name: 'Add Source' })).not.toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Add Source' }))
    expect(submit).toHaveBeenCalledWith(expect.objectContaining({ location_type: 'agent', agent_id: 'agent-1', root_path: '/srv/docs/team', processing_mode: null, path_validation_job_id: 'validation-job' }))
  })

  it('tests and saves the native path selected from a Windows agent root', () => {
    const submit = vi.fn()
    const windows = { ...agent, platform: 'win32-x64', allowed_roots: [{ root_id: 'docs', path: 'C:\\Data\\Docs' }] }
    render(<SourceForm remoteAgentsEnabled agents={[windows]} defaultSchedule={null} onSubmit={submit} onCancel={vi.fn()} isLoading={false} />)
    fireEvent.click(screen.getByLabelText('Remote agent'))
    fireEvent.change(screen.getByLabelText('Approved agent'), { target: { value: 'agent-1' } })
    fireEvent.change(screen.getByLabelText('Allowed root'), { target: { value: 'docs' } })
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Windows docs' } })
    fireEvent.click(screen.getByRole('button', { name: 'Test path' }))
    expect(testPath).toHaveBeenLastCalledWith(expect.objectContaining({ root_path: 'C:\\Data\\Docs' }), expect.anything())
    act(() => testPath.mock.calls[testPath.mock.calls.length - 1][1].onSuccess({ ok: true, status: 'completed', job_id: 'windows-validation', message: 'Ready', path: 'C:\\Data\\Docs', exists: true, is_directory: true, readable: true, inside_allowed_roots: true, allowed_roots: ['C:\\Data\\Docs'], looks_like_host_path: false }))
    fireEvent.click(screen.getByRole('button', { name: 'Add Source' }))
    expect(submit).toHaveBeenCalledWith(expect.objectContaining({ root_path: 'C:\\Data\\Docs', path_validation_job_id: 'windows-validation' }))
  })

  it('hides remote location controls while the feature is disabled', () => {
    render(<SourceForm remoteAgentsEnabled={false} agents={[agent]} defaultSchedule={null} onSubmit={vi.fn()} onCancel={vi.fn()} isLoading={false} />)
    expect(screen.queryByLabelText('Remote agent')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Root Path')).toBeInTheDocument()
  })

  it('shows the offline response from remote validation', () => {
    render(<SourceForm remoteAgentsEnabled agents={[agent]} defaultSchedule={null} onSubmit={vi.fn()} onCancel={vi.fn()} isLoading={false} />)
    fireEvent.click(screen.getByLabelText('Remote agent'))
    fireEvent.change(screen.getByLabelText('Approved agent'), { target: { value: 'agent-1' } })
    fireEvent.change(screen.getByLabelText('Remote path'), { target: { value: '/srv/docs' } })
    fireEvent.click(screen.getByRole('button', { name: 'Test path' }))
    act(() => testPath.mock.calls[testPath.mock.calls.length - 1][1].onError(new ApiError('agent_offline', 409, 'agent_offline')))
    expect(screen.getByText('agent_offline')).toBeInTheDocument()
  })

  it('allows a degraded connected agent to be selected and tested', () => {
    const degraded = { ...agent, status: 'degraded' as const, health: { code: 'recent_indexing_failures' as const, affected_sources: 1, truncated: false, observed_at: '2026-01-01T00:00:00Z' } }
    render(<SourceForm remoteAgentsEnabled agents={[degraded]} defaultSchedule={null} onSubmit={vi.fn()} onCancel={vi.fn()} isLoading={false} />)

    fireEvent.click(screen.getByLabelText('Remote agent'))
    fireEvent.change(screen.getByLabelText('Approved agent'), { target: { value: 'agent-1' } })
    fireEvent.change(screen.getByLabelText('Remote path'), { target: { value: '/srv/docs' } })

    expect(screen.getByRole('button', { name: 'Test path' })).toBeEnabled()
  })

  it('shows the backend allowed-root validation message', () => {
    render(<SourceForm remoteAgentsEnabled agents={[agent]} defaultSchedule={null} onSubmit={vi.fn()} onCancel={vi.fn()} isLoading={false} />)
    fireEvent.click(screen.getByLabelText('Remote agent'))
    fireEvent.change(screen.getByLabelText('Approved agent'), { target: { value: 'agent-1' } })
    fireEvent.change(screen.getByLabelText('Remote path'), { target: { value: '/outside' } })
    fireEvent.click(screen.getByRole('button', { name: 'Test path' }))
    act(() => testPath.mock.calls[testPath.mock.calls.length - 1][1].onError(new ApiError('path is outside allowed roots', 422, 'path is outside allowed roots')))
    expect(screen.getByText('path is outside allowed roots')).toBeInTheDocument()
  })

  it('keeps global scheduling and agent ownership when a remote source follows the default', () => {
    const submit = vi.fn()
    render(<SourceForm remoteAgentsEnabled agents={[agent]} defaultSchedule={{ schedule_type: 'cron', scan_schedule: '@daily' }} onSubmit={submit} onCancel={vi.fn()} isLoading={false} />)
    fireEvent.click(screen.getByLabelText('Remote agent'))
    fireEvent.change(screen.getByLabelText('Approved agent'), { target: { value: 'agent-1' } })
    fireEvent.change(screen.getByLabelText('Remote path'), { target: { value: '/srv/docs' } })
    fireEvent.click(screen.getByRole('button', { name: 'Test path' }))
    testPath.mock.calls[testPath.mock.calls.length - 1][1].onSuccess({ ok: true, status: 'completed', job_id: 'default-validation-job', message: 'Ready', path: '/srv/docs', exists: true, is_directory: true, readable: true, inside_allowed_roots: true, allowed_roots: ['/srv/docs'], looks_like_host_path: false })
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Remote docs' } })
    expect(screen.getByLabelText('Use global default')).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('Use global default'))
    fireEvent.click(screen.getByRole('button', { name: 'Add Source' }))
    expect(submit).toHaveBeenCalledWith(expect.objectContaining({ agent_id: 'agent-1', location_type: 'agent', path_validation_job_id: 'default-validation-job', use_default_schedule: true, schedule_type: 'cron', scan_schedule: null }))
  })

  it('supports a processing override and returning to inherited mode', () => {
    const submit = vi.fn()
    const source = { id: 'remote-source', name: 'Remote docs', root_path: '/srv/docs', location_type: 'agent' as const, agent_id: 'agent-1', processing_mode: null, created_at: '', updated_at: '' }
    const view = render(<SourceForm source={source} remoteAgentsEnabled agents={[agent]} defaultSchedule={null} onSubmit={submit} onCancel={vi.fn()} isLoading={false} />)
    fireEvent.change(screen.getByLabelText('Processing mode'), { target: { value: 'on_server' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }))
    expect(submit).toHaveBeenLastCalledWith(expect.objectContaining({ processing_mode: 'on_server', agent_id: 'agent-1', root_path: '/srv/docs' }))
    view.unmount(); submit.mockClear()
    render(<SourceForm source={{ ...source, processing_mode: 'on_server' }} remoteAgentsEnabled agents={[agent]} defaultSchedule={null} onSubmit={submit} onCancel={vi.fn()} isLoading={false} />)
    fireEvent.change(screen.getByLabelText('Processing mode'), { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }))
    expect(submit).toHaveBeenLastCalledWith(expect.objectContaining({ processing_mode: null, agent_id: 'agent-1', root_path: '/srv/docs' }))
  })

  it('sends a fresh completed validation proof when editing a remote path', () => {
    const submit = vi.fn()
    const source = { id: 'remote-source', name: 'Remote docs', root_path: '/srv/docs', location_type: 'agent' as const, agent_id: 'agent-1', processing_mode: null, created_at: '', updated_at: '' }
    render(<SourceForm source={source} remoteAgentsEnabled agents={[agent]} defaultSchedule={null} onSubmit={submit} onCancel={vi.fn()} isLoading={false} />)
    fireEvent.change(screen.getByLabelText('Remote path'), { target: { value: '/srv/docs/new' } })
    fireEvent.click(screen.getByRole('button', { name: 'Test path' }))
    act(() => testPath.mock.calls[testPath.mock.calls.length - 1][1].onSuccess({ ok: true, status: 'completed', job_id: 'update-validation', message: 'Ready', path: '/srv/docs/new', exists: true, is_directory: true, readable: true, inside_allowed_roots: true, allowed_roots: ['/srv/docs'], looks_like_host_path: false }))

    fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }))

    expect(submit).toHaveBeenCalledWith(expect.objectContaining({ root_path: '/srv/docs/new', path_validation_job_id: 'update-validation' }))
  })

  it('ignores a late validation result after the remote path changes', () => {
    render(<SourceForm remoteAgentsEnabled agents={[agent]} defaultSchedule={null} onSubmit={vi.fn()} onCancel={vi.fn()} isLoading={false} />)
    fireEvent.click(screen.getByLabelText('Remote agent'))
    fireEvent.change(screen.getByLabelText('Approved agent'), { target: { value: 'agent-1' } })
    fireEvent.change(screen.getByLabelText('Remote path'), { target: { value: '/srv/docs/old' } })
    fireEvent.click(screen.getByRole('button', { name: 'Test path' }))
    const oldRequest = testPath.mock.calls[testPath.mock.calls.length - 1][1]
    fireEvent.change(screen.getByLabelText('Remote path'), { target: { value: '/srv/docs/new' } })
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Remote docs' } })

    oldRequest.onSuccess({ ok: true, status: 'completed', job_id: 'old-validation', message: 'Ready', path: '/srv/docs/old', exists: true, is_directory: true, readable: true, inside_allowed_roots: true, allowed_roots: ['/srv/docs'], looks_like_host_path: false })

    expect(screen.getByRole('button', { name: 'Add Source' })).toBeDisabled()
  })

  it('does not authorize create from pending or failed validation responses', () => {
    render(<SourceForm remoteAgentsEnabled agents={[agent]} defaultSchedule={null} onSubmit={vi.fn()} onCancel={vi.fn()} isLoading={false} />)
    fireEvent.click(screen.getByLabelText('Remote agent'))
    fireEvent.change(screen.getByLabelText('Approved agent'), { target: { value: 'agent-1' } })
    fireEvent.change(screen.getByLabelText('Remote path'), { target: { value: '/srv/docs/team' } })
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Team docs' } })
    fireEvent.click(screen.getByRole('button', { name: 'Test path' }))
    const callbacks = testPath.mock.calls[testPath.mock.calls.length - 1][1]
    act(() => callbacks.onSuccess({ ok: false, status: 'pending', job_id: 'pending', message: 'Queued', path: '/srv/docs/team', exists: false, is_directory: false, readable: false, inside_allowed_roots: true, allowed_roots: ['/srv/docs'], looks_like_host_path: false }))
    expect(screen.getByRole('button', { name: 'Add Source' })).toBeDisabled()
    act(() => callbacks.onSuccess({ ok: false, status: 'failed', job_id: 'failed', message: 'Failed', path: '/srv/docs/team', exists: false, is_directory: false, readable: false, inside_allowed_roots: true, allowed_roots: ['/srv/docs'], looks_like_host_path: false }))
    expect(screen.getByRole('button', { name: 'Add Source' })).toBeDisabled()
  })

  it('invalidates completed validation when the remote agent or location changes', () => {
    const secondAgent = { ...agent, id: 'agent-2', name: 'Other agent' }
    render(<SourceForm remoteAgentsEnabled agents={[agent, secondAgent]} defaultSchedule={null} onSubmit={vi.fn()} onCancel={vi.fn()} isLoading={false} />)
    fireEvent.click(screen.getByLabelText('Remote agent'))
    fireEvent.change(screen.getByLabelText('Approved agent'), { target: { value: 'agent-1' } })
    fireEvent.change(screen.getByLabelText('Remote path'), { target: { value: '/srv/docs/team' } })
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Team docs' } })
    fireEvent.click(screen.getByRole('button', { name: 'Test path' }))
    act(() => testPath.mock.calls[testPath.mock.calls.length - 1][1].onSuccess({ ok: true, status: 'completed', job_id: 'validation-job', message: 'Ready', path: '/srv/docs/team', exists: true, is_directory: true, readable: true, inside_allowed_roots: true, allowed_roots: ['/srv/docs'], looks_like_host_path: false }))
    expect(screen.getByRole('button', { name: 'Add Source' })).not.toBeDisabled()

    fireEvent.change(screen.getByLabelText('Approved agent'), { target: { value: 'agent-2' } })
    fireEvent.change(screen.getByLabelText('Remote path'), { target: { value: '/srv/docs/team' } })
    expect(screen.getByRole('button', { name: 'Add Source' })).toBeDisabled()
    fireEvent.click(screen.getByLabelText('Local'))
    fireEvent.click(screen.getByLabelText('Remote agent'))
    fireEvent.change(screen.getByLabelText('Remote path'), { target: { value: '/srv/docs/team' } })
    expect(screen.getByRole('button', { name: 'Add Source' })).toBeDisabled()
  })

  it('keeps an unchanged existing remote source editable while its agent is offline', () => {
    const submit = vi.fn()
    const offlineAgent = { ...agent, status: 'offline' as const }
    const source = { id: 'remote-source', name: 'Remote docs', root_path: '/srv/docs', location_type: 'agent' as const, agent_id: 'agent-1', processing_mode: null, created_at: '', updated_at: '' }
    render(<SourceForm source={source} remoteAgentsEnabled agents={[offlineAgent]} defaultSchedule={null} onSubmit={submit} onCancel={vi.fn()} isLoading={false} />)
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Renamed docs' } })

    expect(screen.getByRole('button', { name: 'Save Changes' })).not.toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }))
    expect(submit).toHaveBeenCalledWith(expect.objectContaining({ name: 'Renamed docs', root_path: '/srv/docs' }))
  })

  it('preserves a disabled remote binding while submitting a maintenance-only edit', () => {
    const submit = vi.fn()
    render(<SourceForm source={{ id: 'remote-source', name: 'Remote docs', root_path: '/srv/docs', location_type: 'agent', agent_id: 'agent-1', processing_mode: null, created_at: '', updated_at: '' }} remoteAgentsEnabled={false} agents={[agent]} defaultSchedule={null} onSubmit={submit} onCancel={vi.fn()} isLoading={false} />)
    expect(screen.getByText(/Remote source binding is unavailable while remote agents are disabled/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Renamed remote docs' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }))
    expect(submit).toHaveBeenCalledWith(expect.objectContaining({ name: 'Renamed remote docs' }))
    expect(submit.mock.calls[0][0]).not.toHaveProperty('location_type')
    expect(submit.mock.calls[0][0]).not.toHaveProperty('agent_id')
    expect(submit.mock.calls[0][0]).not.toHaveProperty('root_path')
    expect(submit.mock.calls[0][0]).not.toHaveProperty('processing_mode')
  })
})
