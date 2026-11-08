import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, useLocation, useNavigationType } from 'react-router-dom'
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

function LocationProbe() {
  const location = useLocation()
  const navigationType = useNavigationType()
  return <output data-testid="location" data-nav={navigationType}>{location.pathname + location.search}</output>
}

describe('SearchPage filters and URL', () => {
  it('drops source and type from the URL when Clear filters is used', () => {
    render(
      <MemoryRouter initialEntries={['/search?q=report&source=src-1&type=pdf']}>
        <SearchSettingsProvider>
          <SearchPage />
        </SearchSettingsProvider>
        <LocationProbe />
      </MemoryRouter>,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    const probe = screen.getByTestId('location')
    expect(probe).toHaveTextContent(/^\/search\?q=report$/)
    expect(probe).toHaveAttribute('data-nav', 'REPLACE')
  })

  it('opens a result with Enter from the keyboard', () => {
    render(
      <MemoryRouter initialEntries={['/search?q=report']}>
        <SearchSettingsProvider>
          <SearchPage />
        </SearchSettingsProvider>
        <LocationProbe />
      </MemoryRouter>,
    )
    const card = screen.getByRole('link', { name: /report\.pdf/ })
    card.focus()
    expect(card).toHaveFocus()
    fireEvent.keyDown(card, { key: 'Enter' })
    expect(screen.getByTestId('location')).toHaveTextContent('/document/doc-1?q=report')
  })
})
