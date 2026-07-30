import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AgentDetails } from './AgentDetails'

const agent = { id: 'agent-1', name: 'Studio Mac', platform: 'macOS', version: '1.0', protocol_version: 2, allowed_roots: [{ root_id: 'media', path: '/Volumes/Media' }], default_processing_mode: 'on_agent' as const, auto_update: false, status: 'offline' as const, approved_at: null, last_seen_at: null, disabled_at: null, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' }

describe('AgentDetails', () => {
  it('lets an admin choose a persisted default processing mode', () => {
    const onMode = vi.fn()
    render(<AgentDetails agent={agent} onDisable={vi.fn()} onRevoke={vi.fn()} onMode={onMode} />)
    fireEvent.change(screen.getByLabelText('Default processing mode'), { target: { value: 'on_server' } })
    expect(onMode).toHaveBeenCalledWith('on_server')
    expect(screen.getByText(/Allowed roots: \/Volumes\/Media/)).toBeInTheDocument()
  })
})
