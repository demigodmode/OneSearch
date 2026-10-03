import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { PrismLight as SyntaxHighlighter } from 'react-syntax-highlighter'
import javascript from 'react-syntax-highlighter/dist/esm/languages/prism/javascript'
import python from 'react-syntax-highlighter/dist/esm/languages/prism/python'
import { MarkdownRenderer } from './MarkdownRenderer'

SyntaxHighlighter.registerLanguage('javascript', javascript)
SyntaxHighlighter.registerLanguage('python', python)

describe('MarkdownRenderer', () => {
  it('renders headings, links, and inline code', () => {
    render(<MarkdownRenderer content={'# Title\n\nSee [docs](https://example.com) and `code`.'} />)

    expect(screen.getByRole('heading', { level: 1, name: 'Title' })).toBeInTheDocument()
    const link = screen.getByRole('link', { name: 'docs' })
    expect(link).toHaveAttribute('href', 'https://example.com')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    expect(screen.getByText('code').tagName).toBe('CODE')
  })

  it('uses the contrast-safe brand color for link and inline code text', () => {
    render(<MarkdownRenderer content={'[docs](https://example.com) and `code`'} />)

    expect(screen.getByRole('link', { name: 'docs' })).toHaveClass('text-brand-strong')
    expect(screen.getByText('code')).toHaveClass('text-brand-strong')
  })

  it('renders pipe tables inside a horizontal scroll wrapper', () => {
    const md = '| Name | Size |\n| --- | --- |\n| a.txt | 1 KB |\n| b.txt | 2 KB |'
    render(<MarkdownRenderer content={md} />)

    const table = screen.getByRole('table')
    expect(table.parentElement).toHaveClass('overflow-x-auto')
    expect(screen.getByRole('columnheader', { name: 'Name' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Size' })).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: 'b.txt' })).toBeInTheDocument()
    expect(screen.getAllByRole('row')).toHaveLength(3)
  })

  it('renders strikethrough and task lists', () => {
    render(<MarkdownRenderer content={'~~old~~\n\n- [x] done\n- [ ] todo'} />)

    expect(screen.getByText('old').tagName).toBe('DEL')
    const boxes = screen.getAllByRole('checkbox')
    expect(boxes).toHaveLength(2)
    expect(boxes[0]).toBeChecked()
    expect(boxes[1]).not.toBeChecked()
  })

  it('highlights an exact literal query across inline Markdown leaves', () => {
    render(<MarkdownRenderer content={'Body **text** and [more](https://example.com).'} searchQuery={'body text'} />)

    expect(screen.getByText('Body')).toHaveClass('rounded', 'bg-brand/30')
    expect(screen.getByText('text')).toHaveClass('rounded', 'bg-brand/30')
    expect(screen.getByRole('link', { name: 'more' })).toHaveAttribute('href', 'https://example.com')
  })

  it('uses case-insensitive literal fallback terms only when the exact phrase is absent', () => {
    render(<MarkdownRenderer content={'A+ body only; TEXT elsewhere.'} searchQuery={'a+ body text'} />)

    expect(screen.getByText('A+')).toHaveClass('bg-brand/30')
    expect(screen.getByText('body')).toHaveClass('bg-brand/30')
    expect(screen.getByText('TEXT')).toHaveClass('bg-brand/30')
  })

  it('marks a fenced-code phrase across Prism token spans without losing token colors', () => {
    render(<MarkdownRenderer content={'```javascript\nconst bodyText = 1\n```'} searchQuery="const bodyText" />)

    expect(screen.getByText('const').closest('mark')).toHaveClass('bg-brand/30')
    expect(screen.getByText('bodyText').closest('mark')).toHaveClass('bg-brand/30')
    expect(document.querySelector('code span[style*="color"]')).toBeInTheDocument()
  })

  it('uses an exact phrase found only in a fence instead of prose fallback terms', () => {
    render(<MarkdownRenderer content={'body prose token\n\n```javascript\nconst body token = 1\n```'} searchQuery="body token" />)

    expect(screen.getByText('body prose token').querySelector('mark')).toBeNull()
    expect(screen.getByText('body token').closest('mark')).toHaveClass('bg-brand/30')
    expect(document.querySelector('code span[style*="color"]')).toBeInTheDocument()
  })

  it('uses an exact phrase found only in prose instead of fenced fallback terms', () => {
    render(<MarkdownRenderer content={'body text prose\n\n```python\nbody = text\n```'} searchQuery="body text" />)

    expect(screen.getByText('body text').closest('mark')).toHaveClass('bg-brand/30')
    expect(screen.getByText('body', { selector: 'code *' }).closest('mark')).toBeNull()
    expect(screen.getByText('text', { selector: 'code *' }).closest('mark')).toBeNull()
  })

  it('does not synthesize exact phrases across table cells or nested block containers', () => {
    render(<MarkdownRenderer content={'| First | Second |\n| --- | --- |\n| body | text |\n\n> body\n>\n> text'} searchQuery="body text" />)

    expect(screen.getByRole('cell', { name: 'body' }).querySelector('mark')).toHaveTextContent('body')
    expect(screen.getByRole('cell', { name: 'text' }).querySelector('mark')).toHaveTextContent('text')
    expect(screen.getAllByText('body')[1].closest('mark')).toHaveClass('bg-brand/30')
    expect(screen.getAllByText('text')[1].closest('mark')).toHaveClass('bg-brand/30')
  })

  it('keeps query text literal and preserves Markdown URL sanitization', () => {
    render(<MarkdownRenderer content={'<script>alert(1)</script>\n\n[bad](javascript:alert(1)) [safe](https://example.com)'} searchQuery="alert(1)" />)

    expect(document.querySelector('script')).toBeNull()
    expect(screen.getByText('alert(1)')).toHaveClass('bg-brand/30')
    const bad = screen.getByText('bad').closest('a')
    expect(bad).not.toBeNull()
    expect(bad?.getAttribute('href') ?? '').not.toMatch(/^javascript:/i)
    expect(screen.getByRole('link', { name: 'safe' })).toHaveAttribute('href', 'https://example.com')
    expect(screen.getByRole('link', { name: 'safe' })).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('does not join nested list items or list prose with a fenced block', () => {
    render(<MarkdownRenderer content={'- outer\n  - nested target\n\n  ```javascript\n  const target = 1\n  ```'} searchQuery="outer nested target" />)

    expect(screen.getByText('outer').closest('mark')).toHaveClass('bg-brand/30')
    expect(screen.getByText('nested').closest('mark')).toHaveClass('bg-brand/30')
    expect(screen.getByText('target', { selector: 'code *' }).closest('mark')).toHaveClass('bg-brand/30')
  })

  it('does not join visible text across a hard Markdown line break', () => {
    const { container } = render(<MarkdownRenderer content={'body\\\ntext'} searchQuery="bodytext" />)

    expect(container.querySelector('br')).toBeInTheDocument()
    expect(container.querySelector('mark')).toBeNull()
  })
})
