import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ReadableTextRenderer } from './ReadableTextRenderer'

const scrollIntoView = vi.fn()
const content = 'alpha beta\n\ngamma delta\n\nepsilon zeta'

describe('ReadableTextRenderer pager', () => {
  beforeEach(() => {
    scrollIntoView.mockClear()
    Element.prototype.scrollIntoView = scrollIntoView
  })

  it('renders the same pager above and below the text with distinct names', () => {
    render(<ReadableTextRenderer content={content} pageSizeChars={12} />)

    const top = screen.getByRole('navigation', { name: 'Pages (top)' })
    const bottom = screen.getByRole('navigation', { name: 'Pages (bottom)' })
    expect(within(top).getByRole('button', { name: /previous/i })).toBeDisabled()
    expect(within(bottom).getByRole('button', { name: /next/i })).toBeEnabled()
    expect(within(bottom).getByText(/Page/)).toHaveTextContent('Page 1 of 3')
  })

  it('does not render the bottom pager for a single page', () => {
    render(<ReadableTextRenderer content="short note" />)

    expect(screen.queryByRole('navigation', { name: 'Pages (bottom)' })).not.toBeInTheDocument()
  })

  it('moves both pagers together and scrolls to the top after a bottom click', async () => {
    const user = userEvent.setup()
    render(<ReadableTextRenderer content={content} pageSizeChars={12} />)

    await user.click(within(screen.getByRole('navigation', { name: 'Pages (bottom)' })).getByRole('button', { name: /next/i }))

    expect(within(screen.getByRole('navigation', { name: 'Pages (top)' })).getByText(/Page/)).toHaveTextContent('Page 2 of 3')
    expect(within(screen.getByRole('navigation', { name: 'Pages (bottom)' })).getByText(/Page/)).toHaveTextContent('Page 2 of 3')
    expect(screen.getByText('gamma delta')).toBeInTheDocument()
    expect(scrollIntoView).toHaveBeenCalledTimes(1)

    await user.click(within(screen.getByRole('navigation', { name: 'Pages (bottom)' })).getByRole('button', { name: /previous/i }))
    expect(screen.getByText('alpha beta')).toBeInTheDocument()
    expect(scrollIntoView).toHaveBeenCalledTimes(2)
  })

  it('does not scroll after a top click', async () => {
    const user = userEvent.setup()
    render(<ReadableTextRenderer content={content} pageSizeChars={12} />)

    await user.click(within(screen.getByRole('navigation', { name: 'Pages (top)' })).getByRole('button', { name: /next/i }))

    expect(screen.getByText('gamma delta')).toBeInTheDocument()
    expect(scrollIntoView).not.toHaveBeenCalled()
  })
})
