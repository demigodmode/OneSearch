import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AgentsPage from './AgentsPage'
import type { Agent } from '@/types/api'

const hooks = vi.hoisted(() => ({ updateSettings: vi.fn(), approve: vi.fn(), enrollment: vi.fn(), mode: vi.fn(), revoke: vi.fn(), refreshAll: vi.fn() }))
const detailRefetch = vi.fn()
const agentsRefetch = vi.fn()
const online = { id: 'online', name: 'Online agent', platform: 'linux', version: '1', protocol_version: 2, allowed_roots: [], default_processing_mode: 'on_agent' as const, auto_update: false, status: 'online' as const, approved_at: null, last_seen_at: null, disabled_at: null, created_at: '', updated_at: '', health: null, summary: { attached_sources: 1, indexed_documents: 3, pending_jobs: 0, active_jobs: 0, failed_jobs: 0, earliest_next_scan_at: null } }
const offline = { ...online, id: 'offline', name: 'Offline agent', status: 'offline' as const, summary: { ...online.summary, indexed_documents: 7 } }
const pending = { ...online, id: 'pending', name: 'Pending agent', status: 'pending' as const }
const disabled = { ...online, id: 'disabled', name: 'Disabled agent', status: 'disabled' as const }
const degraded = { ...online, id: 'degraded', name: 'Degraded agent', status: 'degraded' as const, health: { code: 'recent_indexing_failures' as const, affected_sources: 2, truncated: false, observed_at: '2026-01-01T00:00:00Z' } }
let enabled = true
let agentsState: { data: Agent[]; isLoading: boolean; error: Error | null } = { data: [online, offline, pending], isLoading: false, error: null }
let enrollmentState: { data: { code: string; expires_at: string } | null; error: Error | null } = { data: null, error: null }
let detailState: { data: Record<string, unknown> | null; isLoading: boolean; error: Error | null } = { data: null, isLoading: false, error: null }
vi.mock('@/hooks/useApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/hooks/useApi')>()
  return {
    useAppSettings: () => ({ data: { remote_agents_enabled: enabled }, isLoading: false, error: null }),
    useUpdateAppSettings: () => ({ mutate: hooks.updateSettings, isPending: false, error: null }),
    useAgents: () => ({ ...agentsState, refetch: agentsRefetch }),
    useCreateAgentEnrollment: () => ({ mutate: hooks.enrollment, isPending: false, ...enrollmentState }),
    useApproveAgent: () => ({ mutate: hooks.approve, isPending: false, error: null }),
    useDisableAgent: () => ({ mutate: vi.fn(), error: null }), useRevokeAgent: () => ({ mutate: hooks.revoke, isPending: false, isError: false, error: null }),
    useUpdateAgentProcessingMode: () => ({ mutate: hooks.mode, error: null }), useAgent: () => ({ ...detailState, refetch: detailRefetch }),
    useInvalidateAgentCaches: () => hooks.refreshAll,
    // Real bounded-refresh timer logic — the polling/grace-window tests need it to behave.
    useBoundedAgentRefresh: actual.useBoundedAgentRefresh,
  }
})

describe('AgentsPage user flows', () => {
  beforeEach(() => { enabled = true; agentsState = { data: [online, offline, pending, disabled, degraded], isLoading: false, error: null }; enrollmentState = { data: null, error: null }; detailState = { data: null, isLoading: false, error: null }; vi.clearAllMocks(); detailRefetch.mockClear(); agentsRefetch.mockClear() })
  it('filters attention to pending and offline agents while showing retained documents', () => {
    render(<AgentsPage />)
    expect(screen.getByText('Remote documents')).toBeInTheDocument()
    expect(screen.getByText('19')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Attention (3)' }))
    expect(screen.getAllByText('Offline agent')).toHaveLength(3)
    expect(screen.getAllByText('Pending agent')).toHaveLength(2)
    expect(screen.getAllByText('2 sources had indexing failures in the last 24 hours.').length).toBeGreaterThan(0)
    expect(screen.queryByText('Online agent')).not.toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button', { name: 'Approve agent' })[0])
    expect(hooks.approve).toHaveBeenCalledWith('pending', expect.anything())
  })
  it('offers and persists the feature toggle when remote agents are disabled', () => {
    enabled = false
    render(<AgentsPage />)
    fireEvent.click(screen.getByRole('button', { name: 'Enable remote agents' }))
    expect(hooks.updateSettings).toHaveBeenCalledWith({ remote_agents_enabled: true })
  })
  it('renders loading, API error, and an empty agent state', () => {
    agentsState = { data: [], isLoading: true, error: null }
    const view = render(<AgentsPage />)
    expect(screen.getByText('Loading agents…')).toBeInTheDocument()
    agentsState = { data: [], isLoading: false, error: new Error('no connection') }
    view.rerender(<AgentsPage />)
    expect(screen.getByText('Unable to load remote-agent administration.')).toBeInTheDocument()
    agentsState = { data: [], isLoading: false, error: null }
    view.rerender(<AgentsPage />)
    expect(screen.getByText(/No agents match this filter/)).toBeInTheDocument()
  })
  it('renders enrollment success and API failures', () => {
    enrollmentState = { data: { code: 'OS-ABCD-1234', expires_at: '2026-01-01T01:00:00Z' }, error: null }
    const view = render(<AgentsPage />)
    fireEvent.click(screen.getByRole('button', { name: /Add agent enrollment/ }))
    expect(hooks.enrollment).toHaveBeenCalled()
    expect(screen.getByText('OS-ABCD-1234')).toBeInTheDocument()
    enrollmentState = { data: null, error: new Error('enrollment unavailable') }
    view.rerender(<AgentsPage />)
    expect(screen.getByText('enrollment unavailable')).toBeInTheDocument()
  })
  it('renders agent details and persists a changed default processing mode', () => {
    detailState = { data: { ...online, allowed_roots: [{ root_id: 'docs', path: '/srv/docs' }], auto_update: true, update_report: { auto_update: true, runtime_kind: 'native', status: 'current', available_version: null, checked_at: '2026-08-11T12:00:00Z', error_code: null }, sources: [{ id: 'source-1', name: 'Remote docs', root_path: '/srv/docs', next_scan_at: null }], recent_jobs: [{ id: 'job-1', kind: 'scan', status: 'failed', source_id: 'source-1', created_at: '', completed_at: null, error: 'disk full' }] }, isLoading: false, error: null }
    render(<AgentsPage />)
    fireEvent.click(screen.getAllByText('Online agent')[0])
    expect(screen.getByText('Allowed roots')).toBeInTheDocument()
    expect(screen.getByText('/srv/docs')).toBeInTheDocument()
    expect(screen.getByText(/Remote docs: \/srv\/docs/)).toBeInTheDocument()
    expect(screen.getByText(/scan · failed — disk full/)).toBeInTheDocument()
    expect(screen.getByText('Up to date.')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Default processing mode'), { target: { value: 'on_server' } })
    expect(hooks.mode).toHaveBeenCalledWith({ id: 'online', mode: 'on_server' }, expect.anything())
    const options = hooks.mode.mock.calls[0][1]
    options.onSuccess()
    expect(detailRefetch).toHaveBeenCalled()
  })
  it('shows detail loading and detail API errors after selection', () => {
    detailState = { data: null, isLoading: true, error: null }
    const view = render(<AgentsPage />)
    fireEvent.click(screen.getAllByText('Online agent')[0])
    expect(screen.getByText('Loading agent details…')).toBeInTheDocument()
    detailState = { data: null, isLoading: false, error: new Error('detail unavailable') }
    view.rerender(<AgentsPage />)
    expect(screen.getByText('detail unavailable')).toBeInTheDocument()
  })
  it('enables a disabled agent from its detail and refreshes it after success', () => {
    detailState = { data: { ...disabled, sources: [], recent_jobs: [] }, isLoading: false, error: null }
    render(<AgentsPage />)
    expect(screen.getAllByRole('button', { name: 'Enable agent' }).length).toBeGreaterThan(0)
    fireEvent.click(screen.getAllByText('Disabled agent')[0])
    const enableButtons = screen.getAllByRole('button', { name: 'Enable agent' })
    fireEvent.click(enableButtons[enableButtons.length - 1])
    expect(hooks.approve).toHaveBeenLastCalledWith('disabled', expect.anything())
    act(() => { hooks.approve.mock.calls[hooks.approve.mock.calls.length - 1][1].onSuccess() })
    expect(detailRefetch).toHaveBeenCalled()
  })
  it('revokes an agent, refreshes related caches, and closes the panel on success', () => {
    detailState = { data: { ...online, sources: [], recent_jobs: [] }, isLoading: false, error: null }
    render(<AgentsPage />)
    fireEvent.click(screen.getAllByText('Online agent')[0])
    fireEvent.click(screen.getByRole('button', { name: /Revoke credential/ }))
    fireEvent.click(screen.getByRole('button', { name: /Confirm revoke/i }))
    expect(hooks.revoke).toHaveBeenCalledWith(
      { id: 'online', deleteSources: false },
      expect.anything(),
    )
    expect(() => hooks.revoke.mock.calls[hooks.revoke.mock.calls.length - 1][1].onSuccess()).not.toThrow()
    expect(hooks.refreshAll).toHaveBeenCalled()
  })
  it('keeps the panel open and refreshes caches when revoke fails', () => {
    detailState = { data: { ...online, sources: [], recent_jobs: [] }, isLoading: false, error: null }
    render(<AgentsPage />)
    fireEvent.click(screen.getAllByText('Online agent')[0])
    fireEvent.click(screen.getByRole('button', { name: /Revoke credential/ }))
    fireEvent.click(screen.getByRole('button', { name: /Confirm revoke/i }))
    hooks.revoke.mock.calls[hooks.revoke.mock.calls.length - 1][1].onError()
    expect(hooks.refreshAll).toHaveBeenCalled()
    expect(screen.getByText('Allowed roots')).toBeInTheDocument()
  })

  describe('bounded refresh + grace window after enable', () => {
    beforeEach(() => { vi.useFakeTimers() })
    afterEach(() => { vi.useRealTimers() })

    it('refetches agents and agent detail multiple times over the window after enabling, then stops', () => {
      detailState = { data: { ...disabled, sources: [], recent_jobs: [] }, isLoading: false, error: null }
      render(<AgentsPage />)
      fireEvent.click(screen.getAllByText('Disabled agent')[0])
      const enableButtons = screen.getAllByRole('button', { name: 'Enable agent' })
      fireEvent.click(enableButtons[enableButtons.length - 1])
      act(() => { hooks.approve.mock.calls[hooks.approve.mock.calls.length - 1][1].onSuccess() })
      expect(agentsRefetch).not.toHaveBeenCalled() // nothing fires synchronously — only on the scheduled ticks
      act(() => { vi.advanceTimersByTime(2000) })
      const afterFirstTick = agentsRefetch.mock.calls.length
      expect(afterFirstTick).toBeGreaterThanOrEqual(1)
      act(() => { vi.advanceTimersByTime(30000) })
      const afterAllTicks = agentsRefetch.mock.calls.length
      expect(afterAllTicks).toBeGreaterThan(afterFirstTick)
      // scheduled window (2s,5s,10s,20s,30s) has fully elapsed — no more refetches should fire
      act(() => { vi.advanceTimersByTime(60000) })
      expect(agentsRefetch.mock.calls.length).toBe(afterAllTicks)
    })

    it('clears pending refetch timers on unmount so nothing fires after unmount', () => {
      detailState = { data: { ...disabled, sources: [], recent_jobs: [] }, isLoading: false, error: null }
      const view = render(<AgentsPage />)
      fireEvent.click(screen.getAllByText('Disabled agent')[0])
      const enableButtons = screen.getAllByRole('button', { name: 'Enable agent' })
      fireEvent.click(enableButtons[enableButtons.length - 1])
      act(() => { hooks.approve.mock.calls[hooks.approve.mock.calls.length - 1][1].onSuccess() })
      view.unmount()
      agentsRefetch.mockClear()
      act(() => { vi.advanceTimersByTime(60000) })
      expect(agentsRefetch).not.toHaveBeenCalled()
    })

    it('shows a calm "waiting for contact" message for a just-enabled, still-offline agent instead of the alarming banner', () => {
      agentsState = { data: [{ ...offline, id: 'offline' }], isLoading: false, error: null }
      detailState = { data: { ...disabled, id: 'offline', sources: [], recent_jobs: [] }, isLoading: false, error: null }
      render(<AgentsPage />)
      fireEvent.click(screen.getAllByRole('button', { name: 'Offline agent' })[0])
      const enableButtons = screen.getAllByRole('button', { name: 'Enable agent' })
      fireEvent.click(enableButtons[enableButtons.length - 1])
      act(() => { hooks.approve.mock.calls[hooks.approve.mock.calls.length - 1][1].onSuccess() })
      expect(screen.getByText(/Enabled — waiting for contact/)).toBeInTheDocument()
      expect(screen.queryByText(/Original files need the agent to reconnect/)).not.toBeInTheDocument()
    })

    it('reverts to the real offline banner once the grace window elapses and the agent is still offline', () => {
      agentsState = { data: [{ ...offline, id: 'offline' }], isLoading: false, error: null }
      detailState = { data: { ...disabled, id: 'offline', sources: [], recent_jobs: [] }, isLoading: false, error: null }
      render(<AgentsPage />)
      fireEvent.click(screen.getAllByRole('button', { name: 'Offline agent' })[0])
      const enableButtons = screen.getAllByRole('button', { name: 'Enable agent' })
      fireEvent.click(enableButtons[enableButtons.length - 1])
      act(() => { hooks.approve.mock.calls[hooks.approve.mock.calls.length - 1][1].onSuccess() })
      expect(screen.getByText(/Enabled — waiting for contact/)).toBeInTheDocument()
      act(() => { vi.advanceTimersByTime(61000) })
      expect(screen.queryByText(/Enabled — waiting for contact/)).not.toBeInTheDocument()
      expect(screen.getByText(/Original files need the agent to reconnect/)).toBeInTheDocument()
    })

    it('keeps each enabled agent on its own grace window when a second agent is enabled shortly after the first', () => {
      const agentA = { ...offline, id: 'agentA', name: 'Agent A' }
      const agentB = { ...offline, id: 'agentB', name: 'Agent B' }
      agentsState = { data: [agentA, agentB], isLoading: false, error: null }
      detailState = { data: { ...disabled, id: 'agentA', name: 'Agent A', sources: [], recent_jobs: [] }, isLoading: false, error: null }
      render(<AgentsPage />)

      // Each agent's banner is a single <p>Name: <state text>...</p> — assert on that
      // paragraph's own text rather than a document-wide regex, since "waiting for
      // contact" text is shared between agents.
      const bannerFor = (name: string) =>
        screen.getByText((_, node) => node?.tagName === 'P' && node.textContent?.startsWith(name) === true)

      // Enable Agent A first.
      fireEvent.click(screen.getAllByRole('button', { name: 'Agent A' })[0])
      let enableButtons = screen.getAllByRole('button', { name: 'Enable agent' })
      fireEvent.click(enableButtons[enableButtons.length - 1])
      act(() => { hooks.approve.mock.calls[hooks.approve.mock.calls.length - 1][1].onSuccess() })
      expect(bannerFor('Agent A').textContent).toMatch(/Enabled — waiting for contact/)

      // 10s later, enable Agent B too — this must not cancel Agent A's grace-end timer.
      act(() => { vi.advanceTimersByTime(10000) })
      detailState = { data: { ...disabled, id: 'agentB', name: 'Agent B', sources: [], recent_jobs: [] }, isLoading: false, error: null }
      fireEvent.click(screen.getAllByRole('button', { name: 'Agent B' })[0])
      enableButtons = screen.getAllByRole('button', { name: 'Enable agent' })
      fireEvent.click(enableButtons[enableButtons.length - 1])
      act(() => { hooks.approve.mock.calls[hooks.approve.mock.calls.length - 1][1].onSuccess() })
      expect(bannerFor('Agent A').textContent).toMatch(/Enabled — waiting for contact/)
      expect(bannerFor('Agent B').textContent).toMatch(/Enabled — waiting for contact/)

      // 50s more (60s total since Agent A was enabled, only 50s since Agent B was): Agent A's
      // own window has elapsed and its real offline banner must return, independent of Agent B.
      act(() => { vi.advanceTimersByTime(50000) })
      expect(bannerFor('Agent A').textContent).toMatch(/is offline; its/)
      expect(bannerFor('Agent B').textContent).toMatch(/Enabled — waiting for contact/)

      // Once Agent B's own 60s window elapses, it reverts too.
      act(() => { vi.advanceTimersByTime(11000) })
      expect(bannerFor('Agent A').textContent).toMatch(/is offline; its/)
      expect(bannerFor('Agent B').textContent).toMatch(/is offline; its/)
    })
  })
})
