import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PrismLight as SyntaxHighlighter } from 'react-syntax-highlighter'
import markdown from 'react-syntax-highlighter/dist/esm/languages/prism/markdown'
import { RawTextView } from './RawTextView'
import { RAW_PAGE_CHARS, RAW_PAGE_LINES, buildRawTextPages } from './rawTextPages'

SyntaxHighlighter.registerLanguage('markdown', markdown)

const refetch = vi.fn()
const rawState = { data: undefined as string | undefined, isLoading: false, error: null as Error | null, refetch }
const useDocumentRawText = vi.fn((..._args: unknown[]) => rawState)

vi.mock('@/hooks/useApi', () => ({
  useDocumentRawText: (...args: unknown[]) => useDocumentRawText(...args),
}))

const doc = { id: 'doc-1', modified_at: 1700000000, size_bytes: 2048 }

function pageStatus(pageIndex: number, pageCount: number) {
  return (_content: string, element: Element | null) => element?.textContent === `Page ${pageIndex} of ${pageCount}`
}

function renderedSource(container: HTMLElement) {
  const code = container.querySelector('code')?.cloneNode(true) as HTMLElement | null
  code?.querySelectorAll('[class*="line-number"], [class*="linenumber"]').forEach((element) => element.remove())
  return code?.textContent ?? ''
}

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

  it('marks the raw exact query without matching line-number DOM', () => {
    rawState.data = '---\r\ntitle: Body text\r\n---\r\n\r\n# Body text'
    const { container } = render(<RawTextView document={doc} language="markdown" maxBytes={25 * 1024 * 1024} searchQuery="body text" />)

    expect(container.querySelectorAll('mark')).toHaveLength(2)
    expect(container.querySelector('.linenumber mark')).toBeNull()
  })

  it('reconstructs each real Prism Raw page exactly across a CRLF character boundary and keeps selected marks after revisit', async () => {
    const user = userEvent.setup()
    const source = `---\r\ntitle: 😀\r\n---\r\n${'before token\r\n'.repeat(3)}${'x'.repeat(RAW_PAGE_CHARS - 55)}\r\nbody text\r\n  trailing whitespace  `
    rawState.data = source
    const pages = buildRawTextPages(source)
    expect(pages).toHaveLength(2)

    const { container } = render(<RawTextView document={doc} language="markdown" maxBytes={25 * 1024 * 1024} searchQuery="body text" />)
    expect(renderedSource(container)).toBe(source.slice(pages[0].start, pages[0].end))
    expect(container.querySelectorAll('mark')).toHaveLength(0)

    await user.click(screen.getByRole('button', { name: /next/i }))
    expect(renderedSource(container)).toBe(source.slice(pages[1].start, pages[1].end))
    expect(container.querySelectorAll('mark')).toHaveLength(1)
    expect(container.querySelector('mark')).toHaveTextContent('body text')

    await user.click(screen.getByRole('button', { name: /previous/i }))
    expect(renderedSource(container)).toBe(source.slice(pages[0].start, pages[0].end))
    await user.click(screen.getByRole('button', { name: /next/i }))
    expect(renderedSource(container)).toBe(source.slice(pages[1].start, pages[1].end))
    expect(container.querySelectorAll('mark')).toHaveLength(1)
  })

  it('keeps a later Raw page on query rerender and applies global exact priority without losing source', async () => {
    const user = userEvent.setup()
    const source = `${'body token\n'.repeat(10)}${'x'.repeat(RAW_PAGE_CHARS)}\nbody text\nbody token`
    rawState.data = source
    const pages = buildRawTextPages(source)
    const { container, rerender } = render(<RawTextView document={doc} language="markdown" maxBytes={25 * 1024 * 1024} searchQuery="body token" />)

    await user.click(screen.getByRole('button', { name: /next/i }))
    expect(screen.getByText(pageStatus(2, pages.length))).toBeInTheDocument()
    rerender(<RawTextView document={doc} language="markdown" maxBytes={25 * 1024 * 1024} searchQuery="body text" />)

    expect(screen.getByText(pageStatus(2, pages.length))).toBeInTheDocument()
    expect(renderedSource(container)).toBe(source.slice(pages[1].start, pages[1].end))
    expect(Array.from(container.querySelectorAll('mark')).map((mark) => mark.textContent).join('')).toBe('body text')

    await user.click(screen.getByRole('button', { name: /previous/i }))
    expect(renderedSource(container)).toBe(source.slice(pages[0].start, pages[0].end))
    expect(container.querySelectorAll('mark')).toHaveLength(0)
  })

  it('keeps exact-match priority across Raw pages', async () => {
    const user = userEvent.setup()
    rawState.data = `${'x'.repeat(RAW_PAGE_CHARS - 4)} body\ntext \nbody text`
    const { container } = render(<RawTextView document={doc} language="markdown" maxBytes={25 * 1024 * 1024} searchQuery="body text" />)

    expect(container.querySelectorAll('mark')).toHaveLength(0)
    await user.click(screen.getByRole('button', { name: /next/i }))
    expect(container.querySelectorAll('mark')).toHaveLength(1)
    expect(container.querySelector('mark')).toHaveTextContent('body text')
  })

  it('keeps small Raw markdown syntax-highlighted through the real renderer', () => {
    rawState.data = '# Notes\n\nA **bold** line.'
    const { container } = render(<RawTextView document={doc} language="markdown" maxBytes={25 * 1024 * 1024} />)

    expect(container.querySelector('code')).toHaveClass('language-markdown')
    expect(container.querySelector('code span:not(.linenumber)[style*="color"]')).toBeInTheDocument()
  })

  it('paginates large Raw markdown as plain text before Prism sees the full input', () => {
    rawState.data = '# heading\n'.repeat(Math.ceil((RAW_PAGE_CHARS + 1) / 10))
    const { container } = render(<RawTextView document={doc} language="markdown" maxBytes={25 * 1024 * 1024} />)

    const pageCount = buildRawTextPages(rawState.data).length
    expect(screen.getByText(pageStatus(1, pageCount))).toBeInTheDocument()
    expect(screen.getByText('Showing plain text for this large file.')).toBeInTheDocument()
    expect(container.querySelector('code')).toHaveClass('language-text')
    expect(container.querySelectorAll('.linenumber')).toHaveLength(RAW_PAGE_LINES + 1)
  }, 5_000)

  it('preserves CRLF, whitespace, and surrogate pairs at Raw page boundaries', () => {
    const source = `  first\r\n${'x'.repeat(RAW_PAGE_CHARS - 10)}😀\r\n  last  `
    const pages = buildRawTextPages(source)

    expect(pages.length).toBeGreaterThan(1)
    expect(pages.map((page) => source.slice(page.start, page.end)).join('')).toBe(source)
    for (const page of pages.slice(0, -1)) {
      expect(source.slice(page.end - 1, page.end)).not.toMatch(/[\uD800-\uDBFF]/)
      expect(source.slice(page.end, page.end + 1)).not.toMatch(/[\uDC00-\uDFFF]/)
    }
  })

  it('keeps a huge one-line Raw page within the character cap', () => {
    rawState.data = 'x'.repeat(RAW_PAGE_CHARS * 2)
    const { container } = render(<RawTextView document={doc} language="markdown" maxBytes={25 * 1024 * 1024} />)

    expect(buildRawTextPages(rawState.data)[0].end).toBe(RAW_PAGE_CHARS)
    expect(container.querySelectorAll('.linenumber')).toHaveLength(1)
    expect(container.querySelector('code')?.textContent).toHaveLength(RAW_PAGE_CHARS + 1)
  })

  it('does not advance past a trailing malformed high surrogate', () => {
    const source = `${'x'.repeat(RAW_PAGE_CHARS)}\ud800`
    const pages = buildRawTextPages(source)

    expect(pages.map((page) => source.slice(page.start, page.end)).join('')).toBe(source)
    expect(pages[pages.length - 1]?.end).toBe(source.length)
    expect(pages.every((page) => page.end <= source.length)).toBe(true)
  })

  it('counts CRLF but preserves lone CR as source text for Prism line numbers', () => {
    const source = `one\rtwo\r\n${'x'.repeat(RAW_PAGE_CHARS)}`
    const pages = buildRawTextPages(source)

    expect(pages.map((page) => source.slice(page.start, page.end)).join('')).toBe(source)
    expect(pages[1].startingLineNumber).toBe(2)
  })

  it('labels the physical line that continues onto the next page', () => {
    rawState.data = `first line\n${'x'.repeat(RAW_PAGE_CHARS)}`
    render(<RawTextView document={doc} language="markdown" maxBytes={25 * 1024 * 1024} />)

    expect(screen.getByText('Line 2 continues on the next page.')).toBeInTheDocument()
  })

  it('uses source line numbers and resets Raw pagination when the content changes', async () => {
    const user = userEvent.setup()
    rawState.data = Array.from({ length: RAW_PAGE_LINES + 1 }, (_, index) => `line ${index + 1}`).join('\n')
    const { container, rerender } = render(<RawTextView document={doc} language="markdown" maxBytes={25 * 1024 * 1024} />)

    expect(container.querySelector('code')).toHaveClass('language-text')
    await user.click(screen.getByRole('button', { name: /next/i }))
    expect(screen.getByText(pageStatus(2, 2))).toBeInTheDocument()
    expect(screen.getByText('201')).toBeInTheDocument()

    rawState.data = 'replacement'
    rerender(<RawTextView document={{ ...doc, id: 'doc-2' }} language="markdown" maxBytes={25 * 1024 * 1024} />)
    expect(screen.queryByRole('button', { name: /next/i })).not.toBeInTheDocument()
    expect(screen.getByText('replacement')).toBeInTheDocument()
  })

  it('does not restore a prior document page after switching away and back', async () => {
    const user = userEvent.setup()
    rawState.data = Array.from({ length: RAW_PAGE_LINES + 1 }, (_, index) => `line ${index + 1}`).join('\n')
    const { rerender } = render(<RawTextView document={doc} language="markdown" maxBytes={25 * 1024 * 1024} />)

    await user.click(screen.getByRole('button', { name: /next/i }))
    expect(screen.getByText(pageStatus(2, 2))).toBeInTheDocument()

    rerender(<RawTextView document={{ ...doc, id: 'doc-2' }} language="markdown" maxBytes={25 * 1024 * 1024} />)
    expect(screen.getByText(pageStatus(1, 2))).toBeInTheDocument()

    rerender(<RawTextView document={doc} language="markdown" maxBytes={25 * 1024 * 1024} />)
    expect(screen.getByText(pageStatus(1, 2))).toBeInTheDocument()
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
