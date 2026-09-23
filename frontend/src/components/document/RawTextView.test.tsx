import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { RawTextView } from './RawTextView'

const refetch = vi.fn()
const rawState = { data: undefined as string | undefined, isLoading: false, error: null as Error | null, refetch }
const useDocumentRawText = vi.fn((..._args: unknown[]) => rawState)

vi.mock('@/hooks/useApi', () => ({
  useDocumentRawText: (...args: unknown[]) => useDocumentRawText(...args),
}))

const doc = { id: 'doc-1', modified_at: 1700000000, size_bytes: 2048 }

describe('RawTextView', () => {
  beforeEach(() => {
    Object.assign(rawState, { data: undefined, isLoading: false, error: null })
    useDocumentRawText.mockClear()
    refetch.mockClear()
  })

  it('shows the original text including front-matter', () => {
    rawState.data = '---\ntitle: Notes\n---\n\n# Body'
    const { container } = render(<RawTextView document={doc} language="markdown" maxBytes={25 * 1024 * 1024} />)

    expect(container.textContent).toMatch(/title: Notes/)
    expect(useDocumentRawText).toHaveBeenCalledWith('doc-1', 1700000000, true, 25 * 1024 * 1024)
  })

  it('does not fetch files over the preview size limit', () => {
    render(<RawTextView document={{ ...doc, size_bytes: 30 * 1024 * 1024 }} language="markdown" maxBytes={25 * 1024 * 1024} />)

    expect(screen.getByText(/too large to show here/i)).toBeInTheDocument()
    expect(useDocumentRawText).toHaveBeenCalledWith('doc-1', 1700000000, false, 25 * 1024 * 1024)
  })

  it('shows loading', () => {
    rawState.isLoading = true
    render(<RawTextView document={doc} language="markdown" maxBytes={25 * 1024 * 1024} />)
    expect(screen.getByText(/loading original file/i)).toBeInTheDocument()
  })

  it('shows the error with a retry', async () => {
    rawState.error = new Error('Remote agent is unavailable')
    render(<RawTextView document={doc} language="markdown" maxBytes={25 * 1024 * 1024} />)

    expect(screen.getByText('Remote agent is unavailable')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /retry/i }))
    expect(refetch).toHaveBeenCalled()
  })
})
