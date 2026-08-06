import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { RemotePathPicker } from './RemotePathPicker'
import type { Agent, SourcePathTestResponse } from '@/types/api'

const agent = {
  id: 'agent-1', name: 'Agent', platform: 'linux', version: '1', protocol_version: 1,
  allowed_roots: [{ root_id: 'docs', path: '/srv/docs' }], default_processing_mode: 'on_agent',
  auto_update: false, status: 'online', approved_at: '2026-01-01', last_seen_at: null,
  disabled_at: null, created_at: '', updated_at: '', health: null, summary: { attached_sources: 0,
    indexed_documents: 0, pending_jobs: 0, active_jobs: 0, failed_jobs: 0, earliest_next_scan_at: null },
} satisfies Agent

const completed = {
  path: '/srv/docs', ok: true, exists: true, is_directory: true, readable: true,
  inside_allowed_roots: true, allowed_roots: ['/srv/docs'], looks_like_host_path: false,
  message: 'Remote path is ready to use.', status: 'completed',
} satisfies SourcePathTestResponse

describe('RemotePathPicker', () => {
  it('shows polling state without implying that it browses directories', () => {
    render(<RemotePathPicker agent={agent} value="/srv/docs" onChange={vi.fn()} onTest={vi.fn()} testing result={null} />)

    expect(screen.getByRole('button', { name: 'Testing path...' })).toBeDisabled()
    expect(screen.getByText('Waiting for the agent to test this path.')).toBeInTheDocument()
    expect(screen.queryByText(/browse/i)).not.toBeInTheDocument()
  })

  it('shows the completed path checks', () => {
    render(<RemotePathPicker agent={agent} value="/srv/docs" onChange={vi.fn()} onTest={vi.fn()} testing={false} result={completed} />)

    expect(screen.getByRole('button', { name: 'Test path' })).toBeEnabled()
    expect(screen.getByText('Exists: yes · Directory: yes · Readable: yes')).toBeInTheDocument()
  })

  it('keeps path testing available while a connected agent is degraded', () => {
    render(<RemotePathPicker agent={{ ...agent, status: 'degraded' }} value="/srv/docs" onChange={vi.fn()} onTest={vi.fn()} testing={false} result={null} />)

    expect(screen.getByRole('button', { name: 'Test path' })).toBeEnabled()
    expect(screen.queryByText(/must be online/i)).not.toBeInTheDocument()
  })
})
