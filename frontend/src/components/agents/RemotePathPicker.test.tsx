import { act, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { RemotePathPicker } from './RemotePathPicker'
import type { Agent, SourceBrowseResponse, SourcePathTestResponse } from '@/types/api'

const agent = { id: 'agent-1', name: 'Agent', platform: 'linux', version: '1', protocol_version: 1, allowed_roots: [{ root_id: 'docs', path: '/srv/docs' }], default_processing_mode: 'on_agent', auto_update: false, status: 'online', approved_at: '2026-01-01', last_seen_at: null, disabled_at: null, created_at: '', updated_at: '', health: null, summary: { attached_sources: 0, indexed_documents: 0, pending_jobs: 0, active_jobs: 0, failed_jobs: 0, earliest_next_scan_at: null } } satisfies Agent
const completed = { path: '/srv/docs', ok: true, exists: true, is_directory: true, readable: true, inside_allowed_roots: true, allowed_roots: ['/srv/docs'], looks_like_host_path: false, message: 'Remote path is ready to use.', status: 'completed' } satisfies SourcePathTestResponse
const browse = (path: string, entries: string[] = [], truncated = false): SourceBrowseResponse => ({ job_id: `job-${path}`, status: 'completed', root_id: 'docs', path, entries: entries.map((name) => ({ name, path: path ? `${path}/${name}` : name })), truncated })

function renderPicker(onBrowse = vi.fn().mockResolvedValue(browse(''))) {
  const onChange = vi.fn()
  const view = render(<RemotePathPicker agent={agent} value="" onChange={onChange} onTest={vi.fn()} testing={false} result={completed} onBrowse={onBrowse} />)
  return { onBrowse, onChange, unmount: view.unmount }
}

function ControlledPicker({ onBrowse }: { onBrowse: (request: { agent_id: string; root_id: string; path: string }) => Promise<SourceBrowseResponse> }) {
  const [value, setValue] = useState('')
  return <RemotePathPicker agent={{ ...agent, allowed_roots: [...agent.allowed_roots, { root_id: 'media', path: '/srv/media' }] }} value={value} onChange={setValue} onTest={vi.fn()} testing={false} result={null} onBrowse={onBrowse} />
}

describe('RemotePathPicker', () => {
  it('lists a selected allowed root and opens a child then its parent without escaping the root', async () => {
    const onBrowse = vi.fn().mockResolvedValueOnce(browse('', ['Team'])).mockResolvedValueOnce(browse('Team', ['Notes'])).mockResolvedValueOnce(browse('', ['Team']))
    const { onChange } = renderPicker(onBrowse)
    fireEvent.change(screen.getByLabelText('Allowed root'), { target: { value: 'docs' } })
    expect(await screen.findByRole('button', { name: 'Open folder Team' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Open folder Team' }))
    expect(await screen.findByRole('button', { name: 'Parent folder' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Parent folder' }))
    expect(onBrowse).toHaveBeenLastCalledWith({ agent_id: 'agent-1', root_id: 'docs', path: '' })
    expect(onChange).toHaveBeenCalledWith('/srv/docs/Team')
    expect(screen.queryByRole('button', { name: 'Parent folder' })).not.toBeInTheDocument()
  })

  it('announces loading, recovery, empty and truncated browse states while retaining manual entry', async () => {
    let reject!: (reason: Error) => void
    const onBrowse = vi.fn().mockReturnValueOnce(new Promise<SourceBrowseResponse>((_, fail) => { reject = fail })).mockResolvedValueOnce(browse('', [], true))
    const { onChange } = renderPicker(onBrowse)
    fireEvent.change(screen.getByLabelText('Allowed root'), { target: { value: 'docs' } })
    expect(screen.getByText(/Loading folders/)).toBeInTheDocument()
    await act(async () => reject(new Error('agent unavailable')))
    expect(await screen.findByRole('alert')).toHaveTextContent('agent unavailable')
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText(/No subfolders here/)).toBeInTheDocument()
    expect(screen.getByText(/Only the first 500 folders/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Remote path'), { target: { value: '/srv/docs/manual' } })
    expect(onChange).toHaveBeenLastCalledWith('/srv/docs/manual')
  })

  it('ignores a stale browse result after manual path input changes', async () => {
    let resolve!: (value: SourceBrowseResponse) => void
    const onBrowse = vi.fn().mockReturnValue(new Promise<SourceBrowseResponse>((done) => { resolve = done }))
    renderPicker(onBrowse)
    fireEvent.change(screen.getByLabelText('Allowed root'), { target: { value: 'docs' } })
    fireEvent.change(screen.getByLabelText('Remote path'), { target: { value: '/srv/docs/manual' } })
    await act(async () => resolve(browse('', ['Late folder'])))
    expect(screen.queryByRole('button', { name: 'Open folder Late folder' })).not.toBeInTheDocument()
  })

  it('abandons browse controls after a genuine manual path edit', async () => {
    const onBrowse = vi.fn().mockResolvedValueOnce(browse('', ['Team'])).mockResolvedValueOnce(browse('Team', ['Notes']))
    render(<ControlledPicker onBrowse={onBrowse} />)
    fireEvent.change(screen.getByLabelText('Allowed root'), { target: { value: 'docs' } })
    fireEvent.click(await screen.findByRole('button', { name: 'Open folder Team' }))
    expect(await screen.findByRole('button', { name: 'Parent folder' })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Remote path'), { target: { value: '/other/manual' } })
    expect(screen.queryByRole('button', { name: 'Parent folder' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Open folder Notes' })).not.toBeInTheDocument()
  })

  it('uses native Windows paths for root, child, and parent navigation', async () => {
    const windows = { ...agent, platform: 'windows-amd64', allowed_roots: [{ root_id: 'docs', path: 'C:\\Data\\Docs\\' }] }
    const onChange = vi.fn()
    const onBrowse = vi.fn().mockResolvedValueOnce(browse('', ['Team'])).mockResolvedValueOnce(browse('Team', ['Notes'])).mockResolvedValueOnce(browse('', ['Team']))
    render(<RemotePathPicker agent={windows} value="" onChange={onChange} onTest={vi.fn()} testing={false} result={null} onBrowse={onBrowse} />)
    fireEvent.change(screen.getByLabelText('Allowed root'), { target: { value: 'docs' } })
    fireEvent.click(await screen.findByRole('button', { name: 'Open folder Team' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Parent folder' }))
    expect(onChange).toHaveBeenNthCalledWith(1, 'C:\\Data\\Docs\\')
    expect(onChange).toHaveBeenNthCalledWith(2, 'C:\\Data\\Docs\\Team')
    expect(onChange).toHaveBeenNthCalledWith(3, 'C:\\Data\\Docs\\')
  })

  it('clears stale loading after manual input and keeps a newer browse in control', async () => {
    let resolveFirst!: (value: SourceBrowseResponse) => void
    let resolveSecond!: (value: SourceBrowseResponse) => void
    const onBrowse = vi.fn()
      .mockReturnValueOnce(new Promise<SourceBrowseResponse>((done) => { resolveFirst = done }))
      .mockReturnValueOnce(new Promise<SourceBrowseResponse>((done) => { resolveSecond = done }))
    render(<ControlledPicker onBrowse={onBrowse} />)
    fireEvent.change(screen.getByLabelText('Allowed root'), { target: { value: 'docs' } })
    expect(screen.getByRole('status')).toHaveTextContent('Loading folders')
    fireEvent.change(screen.getByLabelText('Remote path'), { target: { value: '/srv/docs/manual' } })
    expect(screen.queryByRole('status', { name: /loading folders/i })).not.toBeInTheDocument()
    expect(screen.getByLabelText('Allowed root')).toBeEnabled()
    fireEvent.change(screen.getByLabelText('Allowed root'), { target: { value: 'media' } })
    await act(async () => resolveFirst(browse('', ['Old folder'])))
    expect(screen.getByRole('status')).toHaveTextContent('/srv/media')
    await act(async () => resolveSecond({ ...browse('', ['New folder']), root_id: 'media' }))
    expect(await screen.findByRole('button', { name: 'Open folder New folder' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Open folder Old folder' })).not.toBeInTheDocument()
  })

  it('does not update after an unmounted browse resolves', async () => {
    let resolve!: (value: SourceBrowseResponse) => void
    const error = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const view = renderPicker(vi.fn().mockReturnValue(new Promise<SourceBrowseResponse>((done) => { resolve = done })))
    fireEvent.change(screen.getByLabelText('Allowed root'), { target: { value: 'docs' } })
    view.unmount()
    await act(async () => resolve(browse('', ['Late folder'])))
    expect(error).not.toHaveBeenCalled()
    error.mockRestore()
  })

  it('keeps keyboard-accessible Unicode folder names available with their full label', async () => {
    const longName = '資料'.repeat(80)
    renderPicker(vi.fn().mockResolvedValue(browse('', [longName])))
    fireEvent.change(screen.getByLabelText('Allowed root'), { target: { value: 'docs' } })
    const folder = await screen.findByRole('button', { name: `Open folder ${longName}` })
    expect(folder).toHaveAttribute('title', longName)
  })

  it('ignores a failed browse response that belongs to a different root or path', async () => {
    const onBrowse = vi.fn().mockResolvedValueOnce({ ...browse('elsewhere'), status: 'failed', error: 'stale failure' })
    renderPicker(onBrowse)
    fireEvent.change(screen.getByLabelText('Allowed root'), { target: { value: 'docs' } })
    await act(async () => {})
    expect(screen.queryByText('stale failure')).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('renders the root select, manual input, and Test path button before the browse panel, matching the pre-refactor layout', async () => {
    const onBrowse = vi.fn().mockResolvedValue(browse('', ['Team']))
    renderPicker(onBrowse)
    fireEvent.change(screen.getByLabelText('Allowed root'), { target: { value: 'docs' } })
    await screen.findByRole('button', { name: 'Open folder Team' })
    const container = screen.getByLabelText('Allowed root').closest('div')!
    const order = Array.from(container.querySelectorAll('select, input, button')).map((el) => el.tagName + (el.getAttribute('aria-label') || el.getAttribute('id') || el.textContent))
    const selectIndex = order.findIndex((entry) => entry.startsWith('SELECT'))
    const inputIndex = order.findIndex((entry) => entry.startsWith('INPUTremote-root-path'))
    const testButtonIndex = order.findIndex((entry) => entry.includes('Test path'))
    const panelButtonIndex = order.findIndex((entry) => entry.includes('Open folder Team'))
    expect(selectIndex).toBeLessThan(inputIndex)
    expect(inputIndex).toBeLessThan(testButtonIndex)
    expect(testButtonIndex).toBeLessThan(panelButtonIndex)
  })

  it('keeps focus in the Remote path input while typing (no remount on manual edit)', async () => {
    const onBrowse = vi.fn().mockResolvedValue(browse('', ['Team']))
    renderPicker(onBrowse)
    fireEvent.change(screen.getByLabelText('Allowed root'), { target: { value: 'docs' } })
    await screen.findByRole('button', { name: 'Open folder Team' })
    const input = screen.getByLabelText('Remote path') as HTMLInputElement
    input.focus()
    expect(input).toHaveFocus()
    fireEvent.change(input, { target: { value: '/srv/docs/m' } })
    expect(input).toHaveFocus()
  })

  it('disables remote browsing and testing while offline', () => {
    render(<RemotePathPicker agent={{ ...agent, status: 'offline' }} value="/srv/docs" onChange={vi.fn()} onTest={vi.fn()} testing={false} result={null} onBrowse={vi.fn()} />)
    expect(screen.getByLabelText('Allowed root')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Test path' })).toBeDisabled()
    expect(screen.getByRole('status')).toHaveTextContent('must be online')
  })
})
