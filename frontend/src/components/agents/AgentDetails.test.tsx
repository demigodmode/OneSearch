import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AgentDetails } from './AgentDetails'

const agent = { id: 'agent-1', name: 'Studio Mac', platform: 'macOS', version: '1.0', protocol_version: 2, allowed_roots: [{ root_id: 'media', path: '/Volumes/Media' }], default_processing_mode: 'on_agent' as const, auto_update: false, status: 'offline' as const, approved_at: null, last_seen_at: null, disabled_at: null, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', health: null, summary: { attached_sources: 0, indexed_documents: 0, pending_jobs: 0, active_jobs: 0, failed_jobs: 0, earliest_next_scan_at: null }, sources: [], recent_jobs: [] }

describe('AgentDetails', () => {
  it('shows local native update guidance without an editable toggle', () => {
    render(<AgentDetails agent={{ ...agent, auto_update: false, update_report: { auto_update: false, runtime_kind: 'native', status: 'available', available_version: '1.5.0', checked_at: 1700000000, error_code: null } }} onClose={vi.fn()} onDisable={vi.fn()} onRevoke={vi.fn()} onMode={vi.fn()} />)
    expect(screen.getByText('Automatic install is off. Run: onesearch-agent --config <config.toml> update check')).toBeInTheDocument()
    expect(screen.getByText(/Startup and daily GitHub release-host metadata checks/)).toBeInTheDocument()
  })
  it('lets an admin choose a persisted default processing mode', () => {
    const onMode = vi.fn()
    render(<AgentDetails agent={agent} onClose={vi.fn()} onDisable={vi.fn()} onRevoke={vi.fn()} onMode={onMode} />)
    fireEvent.change(screen.getByLabelText('Default processing mode'), { target: { value: 'on_server' } })
    expect(onMode).toHaveBeenCalledWith('on_server')
    expect(screen.getByText('/Volumes/Media')).toBeInTheDocument()
    expect(screen.getByText('No attached sources.')).toBeInTheDocument()
  })

  it('shows Enable instead of Disable for a disabled agent and locks actions while saving', () => {
    const onApprove = vi.fn()
    render(<AgentDetails agent={{ ...agent, status: 'disabled' }} onClose={vi.fn()} onApprove={onApprove} approvalPending={false} actionPending={false} modePending={false} onDisable={vi.fn()} onRevoke={vi.fn()} onMode={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Enable agent' }))
    expect(onApprove).toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: 'Disable credential' })).not.toBeInTheDocument()
  })

  it('locks duplicate disabled-agent recovery and processing updates while pending', () => {
    const onApprove = vi.fn()
    render(<AgentDetails agent={{ ...agent, status: 'disabled' }} onClose={vi.fn()} onApprove={onApprove} approvalPending actionPending={false} modePending={false} onDisable={vi.fn()} onRevoke={vi.fn()} onMode={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Enabling…' })).toBeDisabled()
    expect(screen.getByLabelText('Default processing mode')).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Enabling…' }))
    expect(onApprove).not.toHaveBeenCalled()
  })

  it('shows bounded degraded detail and the catch-up reason for recent jobs', () => {
    render(<AgentDetails agent={{ ...agent, status: 'degraded', health: { code: 'recent_indexing_failures', affected_sources: 99, truncated: true, observed_at: '2026-01-01T00:00:00Z' }, recent_jobs: [{ id: 'job-1', kind: 'scan', reason: 'catch_up', status: 'pending', source_id: 'source-1', created_at: '', completed_at: null, error: null }] }} onClose={vi.fn()} onDisable={vi.fn()} onRevoke={vi.fn()} onMode={vi.fn()} />)

    expect(screen.getByText('99+ sources had indexing failures in the last 24 hours.')).toBeInTheDocument()
    expect(screen.getByText('scan · catch-up · pending')).toBeInTheDocument()
  })
})
