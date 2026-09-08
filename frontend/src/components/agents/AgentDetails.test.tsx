import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AgentDetails } from './AgentDetails'

const agent = { id: 'agent-1', name: 'Studio Mac', platform: 'macOS', version: '1.0', protocol_version: 2, allowed_roots: [{ root_id: 'media', path: '/Volumes/Media' }], default_processing_mode: 'on_agent' as const, auto_update: false, status: 'offline' as const, approved_at: null, last_seen_at: null, disabled_at: null, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', health: null, summary: { attached_sources: 0, indexed_documents: 0, pending_jobs: 0, active_jobs: 0, failed_jobs: 0, earliest_next_scan_at: null }, sources: [], recent_jobs: [] }

describe('AgentDetails', () => {
  it('shows local native update guidance without an editable toggle', () => {
    render(<AgentDetails agent={{ ...agent, auto_update: false, update_report: { auto_update: false, runtime_kind: 'native', status: 'available', available_version: '1.5.0', checked_at: 1700000000, error_code: null } }} onClose={vi.fn()} onDisable={vi.fn()} onRevoke={vi.fn()} onMode={vi.fn()} />)
    expect(screen.getByText(/Update 1\.5\.0 is available\. Automatic install is off — run: onesearch-agent --config <config\.toml> update check/)).toBeInTheDocument()
    expect(screen.getByText(/automatic install is off, so updates are notify-only/)).toBeInTheDocument()
  })

  it('tells docker agents to pull a new image and never implies self-update', () => {
    render(<AgentDetails agent={{ ...agent, update_report: { auto_update: false, runtime_kind: 'docker', status: 'available', available_version: '1.5.0', checked_at: 1700000000, error_code: null } }} onClose={vi.fn()} onDisable={vi.fn()} onRevoke={vi.fn()} onMode={vi.fn()} />)
    expect(screen.getByText(/Image update 1\.5\.0 is available\. Docker agents never update themselves/)).toBeInTheDocument()
    expect(screen.getByText(/docker compose pull onesearch-agent/)).toBeInTheDocument()
  })

  it('shows header metadata as labeled chips', () => {
    render(<AgentDetails agent={{ ...agent, platform: 'macOS', version: '1.0', protocol_version: 2 }} onClose={vi.fn()} onDisable={vi.fn()} onRevoke={vi.fn()} onMode={vi.fn()} />)
    expect(screen.getByText('OS')).toBeInTheDocument()
    expect(screen.getByText('macOS')).toBeInTheDocument()
    expect(screen.getByText('Version')).toBeInTheDocument()
    expect(screen.getByText('v1.0')).toBeInTheDocument()
    expect(screen.getByText('Protocol')).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument()
    expect(screen.getByText('Last contact')).toBeInTheDocument()
    expect(screen.getByText('never')).toBeInTheDocument()
  })

  it('copies the docker update command to the clipboard', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    render(<AgentDetails agent={{ ...agent, update_report: { auto_update: false, runtime_kind: 'docker', status: 'available', available_version: '1.5.0', checked_at: 1700000000, error_code: null } }} onClose={vi.fn()} onDisable={vi.fn()} onRevoke={vi.fn()} onMode={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: /copy command/i }))
    expect(writeText).toHaveBeenCalledWith('docker compose pull onesearch-agent && docker compose up -d onesearch-agent')
    expect(await screen.findByText('Copied')).toBeInTheDocument()
  })

  it('handles a rejected clipboard write without throwing', async () => {
    const writeText = vi.fn().mockRejectedValue(new Error('nope'))
    Object.assign(navigator, { clipboard: { writeText } })
    render(<AgentDetails agent={{ ...agent, update_report: { auto_update: false, runtime_kind: 'docker', status: 'available', available_version: '1.5.0', checked_at: 1700000000, error_code: null } }} onClose={vi.fn()} onDisable={vi.fn()} onRevoke={vi.fn()} onMode={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: /copy command/i }))
    expect(await screen.findByText('Copy failed')).toBeInTheDocument()
  })

  it('handles a non-secure context with no clipboard API without throwing', async () => {
    Object.assign(navigator, { clipboard: undefined })
    render(<AgentDetails agent={{ ...agent, update_report: { auto_update: false, runtime_kind: 'docker', status: 'available', available_version: '1.5.0', checked_at: 1700000000, error_code: null } }} onClose={vi.fn()} onDisable={vi.fn()} onRevoke={vi.fn()} onMode={vi.fn()} />)
    expect(() => fireEvent.click(screen.getByRole('button', { name: /copy command/i }))).not.toThrow()
    expect(await screen.findByText('Copy failed')).toBeInTheDocument()
  })

  it('shows a calm "not configured" message for a keyless build, without error or a pull command', () => {
    render(<AgentDetails agent={{ ...agent, update_report: { auto_update: false, runtime_kind: 'docker', status: 'not_configured', available_version: null, checked_at: 1700000000, error_code: null } }} onClose={vi.fn()} onDisable={vi.fn()} onRevoke={vi.fn()} onMode={vi.fn()} />)
    expect(screen.getByText("Update checks aren't configured for this build.")).toBeInTheDocument()
    expect(screen.queryByText(/docker compose pull/)).not.toBeInTheDocument()
    expect(screen.queryByText(/error/i)).not.toBeInTheDocument()
  })

  it('labels the last update report as historical while the agent is offline', () => {
    render(<AgentDetails agent={{ ...agent, status: 'offline', update_report: { auto_update: false, runtime_kind: 'native', status: 'current', available_version: null, checked_at: '2026-08-11T12:00:00Z', error_code: null } }} onClose={vi.fn()} onDisable={vi.fn()} onRevoke={vi.fn()} onMode={vi.fn()} />)
    expect(screen.getByText(/Historical update status/)).toBeInTheDocument()
    expect(screen.getByText(/Last checked: 8\/11\/2026/)).toBeInTheDocument()
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
    render(<AgentDetails agent={{ ...agent, status: 'degraded', health: { code: 'recent_indexing_failures', affected_sources: 99, truncated: true, observed_at: '2026-01-01T00:00:00Z' }, recent_jobs: [{ id: 'job-1', kind: 'scan', reason: 'catch_up', status: 'pending', source_id: 'source-1', created_at: '2026-01-02T00:00:00Z', completed_at: null, error: null }] }} onClose={vi.fn()} onDisable={vi.fn()} onRevoke={vi.fn()} onMode={vi.fn()} />)

    expect(screen.getByText('99+ sources had indexing failures in the last 24 hours.')).toBeInTheDocument()
    expect(screen.getByText('scan · catch-up')).toBeInTheDocument()
    expect(screen.getByText('Pending')).toBeInTheDocument()
  })

  it('shows a status label and timestamp for each recent job row', () => {
    render(<AgentDetails agent={{ ...agent, recent_jobs: [
      { id: 'job-2', kind: 'extract_file', reason: null, status: 'completed', source_id: 'source-1', created_at: '2026-01-02T00:00:00Z', completed_at: '2026-01-02T00:05:00Z', error: null },
    ] }} onClose={vi.fn()} onDisable={vi.fn()} onRevoke={vi.fn()} onMode={vi.fn()} />)

    expect(screen.getByText('extract_file')).toBeInTheDocument()
    expect(screen.getByText('Completed')).toBeInTheDocument()
    expect(screen.getByText(new Date('2026-01-02T00:05:00Z').toLocaleString())).toBeInTheDocument()
  })

  it('renders a failed job row with the destructive status and its error', () => {
    render(<AgentDetails agent={{ ...agent, recent_jobs: [
      { id: 'job-3', kind: 'stream_file', reason: null, status: 'failed', source_id: 'source-1', created_at: '2026-01-02T00:00:00Z', completed_at: '2026-01-02T00:01:00Z', error: 'connection reset' },
    ] }} onClose={vi.fn()} onDisable={vi.fn()} onRevoke={vi.fn()} onMode={vi.fn()} />)

    const failedBadge = screen.getByText('Failed')
    expect(failedBadge).toBeInTheDocument()
    expect(failedBadge.className).toMatch(/text-destructive/)
    expect(screen.getByText('connection reset')).toBeInTheDocument()
  })

  it('renders a running job row with the warning status', () => {
    render(<AgentDetails agent={{ ...agent, recent_jobs: [
      { id: 'job-4', kind: 'scan', reason: null, status: 'running', source_id: 'source-1', created_at: '2026-01-02T00:00:00Z', completed_at: null, error: null },
    ] }} onClose={vi.fn()} onDisable={vi.fn()} onRevoke={vi.fn()} onMode={vi.fn()} />)

    const runningBadge = screen.getByText('Running')
    expect(runningBadge).toBeInTheDocument()
    expect(runningBadge.className).toMatch(/text-warning/)
  })

  it('confirms revoke, can request source deletion, and moves focus into the dialog', () => {
    const onRevoke = vi.fn()
    render(<AgentDetails agent={{ ...agent, status: 'online', summary: { ...agent.summary, attached_sources: 2 } }} onClose={vi.fn()} onDisable={vi.fn()} onRevoke={onRevoke} onMode={vi.fn()} />)
    const trigger = screen.getByRole('button', { name: /Revoke credential/ })
    fireEvent.click(trigger)
    const dialog = screen.getByRole('dialog')
    expect(dialog).toBeInTheDocument()
    expect(dialog.contains(document.activeElement)).toBe(true)
    fireEvent.click(screen.getByLabelText(/also delete .*sources/i))
    fireEvent.click(screen.getByRole('button', { name: /Confirm revoke/i }))
    expect(onRevoke).toHaveBeenCalledWith({ deleteSources: true })
  })
  it('restores focus to the trigger when the dialog is cancelled', async () => {
    render(<AgentDetails agent={{ ...agent, status: 'online', summary: { ...agent.summary, attached_sources: 1 } }} onClose={vi.fn()} onDisable={vi.fn()} onRevoke={vi.fn()} onMode={vi.fn()} />)
    const trigger = screen.getByRole('button', { name: /Revoke credential/ })
    fireEvent.click(trigger)
    fireEvent.click(screen.getByRole('button', { name: /Cancel/i }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    // Agent untouched, so the trigger survives — focus is handed back to it.
    // Radix restores focus in a queued microtask, so wait for it to settle.
    await waitFor(() => expect(document.activeElement).toBe(trigger))
  })
  it('closes on Escape and returns focus to the trigger', async () => {
    render(<AgentDetails agent={{ ...agent, status: 'online', summary: { ...agent.summary, attached_sources: 1 } }} onClose={vi.fn()} onDisable={vi.fn()} onRevoke={vi.fn()} onMode={vi.fn()} />)
    const trigger = screen.getByRole('button', { name: /Revoke credential/ })
    fireEvent.click(trigger)
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await waitFor(() => expect(document.activeElement).toBe(trigger))
  })
  it('keeps the dialog open on confirm instead of closing it synchronously', () => {
    // The mutation is async. Closing on confirm would race a later failure, so
    // the error would land on an already-closed dialog. The dialog must stay
    // open until the parent resolves it (unmounts on success; shows error on
    // failure). Panel-unmount-on-success is exercised in AgentsPage.test.tsx.
    const onRevoke = vi.fn()
    render(<AgentDetails agent={{ ...agent, status: 'online', summary: { ...agent.summary, attached_sources: 1 } }} onClose={vi.fn()} onDisable={vi.fn()} onRevoke={onRevoke} onMode={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: /Revoke credential/ }))
    fireEvent.click(screen.getByRole('button', { name: /Confirm revoke/i }))
    expect(onRevoke).toHaveBeenCalledWith({ deleteSources: false })
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })
  it('disables the dialog buttons while pending, then surfaces the failure inside the dialog and preserves the checkbox', () => {
    const shared = { agent: { ...agent, status: 'online' as const, summary: { ...agent.summary, attached_sources: 2 } }, onClose: vi.fn(), onDisable: vi.fn(), onRevoke: vi.fn(), onMode: vi.fn() }
    const { rerender } = render(<AgentDetails {...shared} actionPending={false} actionError={null} />)
    fireEvent.click(screen.getByRole('button', { name: /Revoke credential/ }))
    fireEvent.click(screen.getByLabelText(/also delete .*sources/i))
    fireEvent.click(screen.getByRole('button', { name: /Confirm revoke/i }))
    // Mutation in flight: dialog stays open, both actions locked (double-submit guard).
    rerender(<AgentDetails {...shared} actionPending actionError={null} />)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Confirm revoke/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Cancel/i })).toBeDisabled()
    // Failure resolves: dialog is still open, the error shows in context, and the
    // "also delete sources" choice survives so a retry keeps the user's intent.
    rerender(<AgentDetails {...shared} actionPending={false} actionError="Revoke/cleanup failed — retry." />)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText('Revoke/cleanup failed — retry.')).toBeInTheDocument()
    expect((screen.getByLabelText(/also delete .*sources/i) as HTMLInputElement).checked).toBe(true)
  })
  it('traps focus inside the open revoke dialog and wraps at both edges', () => {
    render(<AgentDetails agent={{ ...agent, status: 'online', summary: { ...agent.summary, attached_sources: 1 } }} onClose={vi.fn()} onDisable={vi.fn()} onRevoke={vi.fn()} onMode={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: /Revoke credential/ }))
    const dialog = screen.getByRole('dialog')
    // Initial focus lands inside the modal on open.
    expect(dialog.contains(document.activeElement)).toBe(true)
    const focusables = Array.from(
      dialog.querySelectorAll<HTMLElement>(
        'button, input, [href], [tabindex]:not([tabindex="-1"])',
      ),
    )
    const first = focusables[0]
    const last = focusables[focusables.length - 1]
    // Tab from the last control wraps back to the first (Radix FocusScope trap).
    last.focus()
    fireEvent.keyDown(last, { key: 'Tab' })
    expect(document.activeElement).toBe(first)
    // Shift-Tab from the first control wraps to the last.
    first.focus()
    fireEvent.keyDown(first, { key: 'Tab', shiftKey: true })
    expect(document.activeElement).toBe(last)
  })
  it('keeps the dialog open when escape is pressed during a pending revoke', () => {
    const shared = { agent: { ...agent, status: 'online' as const, summary: { ...agent.summary, attached_sources: 1 } }, onClose: vi.fn(), onDisable: vi.fn(), onRevoke: vi.fn(), onMode: vi.fn() }
    const { rerender } = render(<AgentDetails {...shared} />)
    fireEvent.click(screen.getByRole('button', { name: /Revoke credential/ }))
    fireEvent.click(screen.getByRole('button', { name: /Confirm revoke/i }))
    rerender(<AgentDetails {...shared} actionPending />)
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    // Dismissal is blocked while the mutation is in flight.
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })
  it('offers "Delete remaining sources" for a revoked agent that still has sources', () => {
    const onRevoke = vi.fn()
    render(<AgentDetails agent={{ ...agent, status: 'revoked', summary: { ...agent.summary, attached_sources: 3 } }} onClose={vi.fn()} onDisable={vi.fn()} onRevoke={onRevoke} onMode={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: /Delete remaining sources/i }))
    fireEvent.click(screen.getByRole('button', { name: /Confirm/i }))
    expect(onRevoke).toHaveBeenCalledWith({ deleteSources: true })
  })
})
