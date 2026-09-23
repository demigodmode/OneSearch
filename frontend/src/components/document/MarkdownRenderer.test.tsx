import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { MarkdownRenderer } from './MarkdownRenderer'

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
})
