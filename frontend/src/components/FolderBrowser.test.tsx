import { act, fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { FolderBrowser, type BrowsePage } from './FolderBrowser'

const roots = [{ root_id: 'r1', path: '/data' }, { root_id: 'r2', path: '/media' }]
const page = (path: string, names: string[] = [], truncated = false, root_id = 'r1'): BrowsePage => ({
  root_id, path, truncated, entries: names.map((name) => ({ name, path: path ? `${path}/${name}` : name })),
})

describe('FolderBrowser', () => {
  it('browses a root, opens a child, and goes back to the parent', async () => {
    const browse = vi.fn()
      .mockResolvedValueOnce(page('', ['photos']))
      .mockResolvedValueOnce(page('photos', ['2024']))
      .mockResolvedValueOnce(page('', ['photos']))
    const onSelect = vi.fn()
    render(<FolderBrowser roots={roots} available pathStyle="posix" browse={browse} onSelect={onSelect} />)

    fireEvent.change(screen.getByLabelText('Allowed root'), { target: { value: 'r1' } })
    expect(onSelect).toHaveBeenLastCalledWith('/data')
    fireEvent.click(await screen.findByRole('button', { name: 'Open folder photos' }))
    expect(onSelect).toHaveBeenLastCalledWith('/data/photos')
    expect(browse).toHaveBeenLastCalledWith('r1', 'photos')
    fireEvent.click(await screen.findByRole('button', { name: 'Parent folder' }))
    expect(browse).toHaveBeenLastCalledWith('r1', '')
    expect(onSelect).toHaveBeenLastCalledWith('/data')
  })

  it('shows the error with retry, then empty and truncated states', async () => {
    const browse = vi.fn()
      .mockRejectedValueOnce(new Error("This folder can't be listed."))
      .mockResolvedValueOnce(page('', [], true))
    render(<FolderBrowser roots={roots} available pathStyle="posix" browse={browse} onSelect={vi.fn()} />)

    fireEvent.change(screen.getByLabelText('Allowed root'), { target: { value: 'r1' } })
    expect(await screen.findByRole('alert')).toHaveTextContent("This folder can't be listed.")
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText(/No subfolders here/)).toBeInTheDocument()
    expect(screen.getByText(/Only the first 500 folders/)).toBeInTheDocument()
  })

  it('ignores a response for a different root or path than requested', async () => {
    const browse = vi.fn().mockResolvedValueOnce(page('', ['wrong'], false, 'r2'))
    render(<FolderBrowser roots={roots} available pathStyle="posix" browse={browse} onSelect={vi.fn()} />)

    fireEvent.change(screen.getByLabelText('Allowed root'), { target: { value: 'r1' } })
    await act(async () => {})
    expect(screen.queryByRole('button', { name: 'Open folder wrong' })).not.toBeInTheDocument()
  })

  it('ignores an error whose root or path does not match the request, but shows a matching one', async () => {
    const browse = vi.fn().mockResolvedValueOnce({ ...page('', []), path: 'elsewhere', error: 'stale failure' })
    render(<FolderBrowser roots={roots} available pathStyle="posix" browse={browse} onSelect={vi.fn()} />)

    fireEvent.change(screen.getByLabelText('Allowed root'), { target: { value: 'r1' } })
    await act(async () => {})
    expect(screen.queryByText('stale failure')).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('uses Windows separators when asked', async () => {
    const browse = vi.fn().mockResolvedValueOnce(page('', ['Team'])).mockResolvedValueOnce(page('Team'))
    const onSelect = vi.fn()
    render(<FolderBrowser roots={[{ root_id: 'r1', path: 'C:\\Shares' }]} available pathStyle="windows" browse={browse} onSelect={onSelect} />)

    fireEvent.change(screen.getByLabelText('Allowed root'), { target: { value: 'r1' } })
    fireEvent.click(await screen.findByRole('button', { name: 'Open folder Team' }))
    expect(onSelect).toHaveBeenLastCalledWith('C:\\Shares\\Team')
  })

  it('disables the root select when unavailable', () => {
    render(<FolderBrowser roots={roots} available={false} pathStyle="posix" browse={vi.fn()} onSelect={vi.fn()} />)
    expect(screen.getByLabelText('Allowed root')).toBeDisabled()
  })

  it('renders children between the root select and the browse panel', async () => {
    const browse = vi.fn().mockResolvedValueOnce(page('', ['photos']))
    render(
      <FolderBrowser roots={roots} available pathStyle="posix" browse={browse} onSelect={vi.fn()}>
        <input aria-label="Manual path" />
      </FolderBrowser>
    )
    fireEvent.change(screen.getByLabelText('Allowed root'), { target: { value: 'r1' } })
    await screen.findByRole('button', { name: 'Open folder photos' })
    const order = Array.from(document.body.querySelectorAll('select, input, button')).map((el) => el.tagName + (el.getAttribute('aria-label') || ''))
    const selectIndex = order.findIndex((entry) => entry.startsWith('SELECT'))
    const manualInputIndex = order.findIndex((entry) => entry === 'INPUTManual path')
    const panelButtonIndex = order.findIndex((entry) => entry.includes('Open folder photos'))
    expect(selectIndex).toBeLessThan(manualInputIndex)
    expect(manualInputIndex).toBeLessThan(panelButtonIndex)
  })
})
