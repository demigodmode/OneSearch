import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Link, MemoryRouter, Route, Routes, useParams } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import DocumentPage from './DocumentPage'
import type { Document } from '@/types/api'

const base: Document = {
  id: 'doc-1', source_id: 'src-1', source_name: 'Notes', path: '/data/notes.md', basename: 'notes.md',
  extension: 'md', type: 'markdown', size_bytes: 120, modified_at: 1700000000, indexed_at: 1700000100,
  content: '# Body text', title: 'Notes', metadata: {},
}
const docTwo: Document = {
  ...base, id: 'doc-2', path: '/data/other.md', basename: 'other.md', modified_at: 1700000500,
  content: '# Other body', title: 'Other',
}
let current: Document = base
const useDocumentRawText = vi.fn((..._args: unknown[]) => ({
  data: '---\ntitle: Notes\n---\n\n# Body text', isLoading: false, error: null, refetch: vi.fn(),
}))

vi.mock('@/hooks/useApi', () => ({
  useDocument: (id: string) => ({ data: id === 'doc-2' ? docTwo : current, isLoading: false, error: null }),
  useAppSettings: () => ({ data: { max_preview_size_mb: 25 } }),
  useDocumentRawText: (...args: unknown[]) => useDocumentRawText(...args),
}))

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={['/document/doc-1']}>
      <Routes>
        <Route path="/document/:id" element={<DocumentPage />} />
      </Routes>
    </MemoryRouter>,
  )

function NavHarness() {
  const { id } = useParams<{ id: string }>()
  return (
    <>
      <DocumentPage />
      <Link to="/document/doc-2">go-to-doc-2</Link>
      <span data-testid="route-id">{id}</span>
    </>
  )
}

const renderWithNav = () =>
  render(
    <MemoryRouter initialEntries={['/document/doc-1']}>
      <Routes>
        <Route path="/document/:id" element={<NavHarness />} />
      </Routes>
    </MemoryRouter>,
  )

describe('DocumentPage raw view', () => {
  beforeEach(() => {
    current = base
    useDocumentRawText.mockClear()
  })

  it('offers Rendered/Raw for markdown and only fetches once Raw is picked', async () => {
    const { container } = renderPage()

    expect(screen.getByRole('heading', { name: 'Body text' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Rendered' })).toHaveAttribute('aria-pressed', 'true')
    expect(useDocumentRawText).not.toHaveBeenCalled()

    await userEvent.click(screen.getByRole('button', { name: 'Raw' }))

    expect(container.textContent).toMatch(/title: Notes/)
    expect(useDocumentRawText).toHaveBeenCalledWith('doc-1', 1700000000, true)
  })

  it('still offers Raw when the markdown body is empty (front-matter only)', async () => {
    current = { ...base, content: '' }
    const { container } = renderPage()

    expect(screen.getByText(/no text content/i)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Raw' }))
    expect(container.textContent).toMatch(/title: Notes/)
  })

  it('resets the toggle to Rendered when navigating to another document', async () => {
    renderWithNav()

    await userEvent.click(screen.getByRole('button', { name: 'Raw' }))
    expect(screen.getByRole('button', { name: 'Raw' })).toHaveAttribute('aria-pressed', 'true')

    await userEvent.click(screen.getByText('go-to-doc-2'))

    expect(screen.getByTestId('route-id')).toHaveTextContent('doc-2')
    expect(screen.getByRole('heading', { name: 'Other body' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Rendered' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('has no toggle for other types', () => {
    current = { ...base, type: 'text', extension: 'txt', basename: 'notes.txt', content: 'plain' }
    renderPage()

    expect(screen.queryByRole('button', { name: 'Raw' })).not.toBeInTheDocument()
  })
})
