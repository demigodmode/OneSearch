import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import SearchPage from './SearchPage'
import { SearchSettingsProvider } from '@/contexts/SearchSettingsContext'
import type { SearchResult } from '@/types/api'

const revokedResult: SearchResult = {
  id: 'doc-1',
  path: '/docs/report.pdf',
  basename: 'report.pdf',
  source_name: 'Remote agent source',
  source_id: 'src-1',
  agent_status: 'revoked',
  type: 'pdf',
  size_bytes: 1024,
  modified_at: 1700000000,
  snippet: 'a matching <mark>snippet</mark>',
  score: 1,
}

vi.mock('@/hooks/useApi', () => ({
  useSources: () => ({ data: [] }),
  useSearch: () => ({
    data: { results: [revokedResult], total: 1, limit: 20, offset: 0, processing_time_ms: 1 },
    isLoading: false,
    error: null,
  }),
}))

function renderSearchPage() {
  return render(
    <MemoryRouter initialEntries={['/search?q=report']}>
      <SearchSettingsProvider>
        <SearchPage />
      </SearchSettingsProvider>
    </MemoryRouter>,
  )
}

describe('SearchPage result availability indicator', () => {
  it('shows an unavailable indicator without claiming preview-only', async () => {
    renderSearchPage()
    expect(await screen.findByText('Agent revoked')).toBeInTheDocument()
    expect(screen.queryByText(/preview only/i)).not.toBeInTheDocument()
  })
})
