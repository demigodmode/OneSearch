// Copyright (C) 2026 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import StatusPage from './StatusPage'
import type { SourceStatus } from '@/types/api'

let mockSources: SourceStatus[] = []
vi.mock('@/hooks/useApi', () => ({
  useHealth: () => ({ data: undefined, isLoading: false, error: null }),
  useStatus: () => ({ data: { sources: mockSources }, isLoading: false, error: null }),
}))

const base = {
  source_name: 'Docs',
  total_files: 10,
  successful: 10,
  failed: 0,
  skipped: 0,
  last_indexed_at: '2026-11-01T10:00:00Z',
  failed_files: [],
}

function renderStatus() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <StatusPage />
    </QueryClientProvider>,
  )
}

describe('StatusPage next scan', () => {
  it('shows the next scan for an interval or default schedule', () => {
    mockSources = [{ ...base, source_id: 'docs', scan_schedule: null, next_scan_at: '2026-11-04T10:00:00Z' }]
    renderStatus()
    expect(screen.getByText(/Next scan/)).toBeInTheDocument()
  })

  it('hides the next scan when no scan is queued', () => {
    mockSources = [{ ...base, source_id: 'docs', scan_schedule: null, next_scan_at: null }]
    renderStatus()
    expect(screen.queryByText(/Next scan/)).not.toBeInTheDocument()
  })
})
