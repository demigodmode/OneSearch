import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { BatchSourceDialog } from './BatchSourceDialog'

const createBatch = vi.fn()
const createItem = vi.fn()
const getBatch = vi.fn()
vi.mock('@/hooks/useApi', () => ({ useLocalSourceRoots: () => ({ data: { browse_available: true, roots: [{ root_id: 'docs', path: '/data', label: '/data' }] }, isLoading: false, isError: false, refetch: vi.fn() }) }))
vi.mock('@/lib/api', () => ({
  browseLocalDirectory: vi.fn().mockResolvedValue({ root_id: 'docs', path: '', entries: [{ name: 'team', path: 'team' }], truncated: false }),
  createSourceBatch: (...args: unknown[]) => createBatch(...args),
  createSourceBatchItem: (...args: unknown[]) => createItem(...args),
  getSourceBatch: (...args: unknown[]) => getBatch(...args),
  testSourcePath: vi.fn(),
}))

describe('BatchSourceDialog', () => {
  const saved = (states: ('pending' | 'created' | 'already_exists' | 'failed')[], id = '00000000-0000-4000-8000-000000000001') => ({
    id, location_type: 'local' as const, agent_id: null,
    common_settings: { schedule_type: 'cron' as const, scan_schedule: null, include_patterns: [], exclude_patterns: [], use_default_schedule: false, processing_mode: null },
    fingerprint: 'fingerprint', dismissed: false, created_at: '', updated_at: '',
    items: states.map((state, index) => ({ id: `item-${index}`, name: `Folder ${index}`, root_path: `/data/${index}`,
      state, source_id: state === 'created' || state === 'already_exists' ? `source-${index}` : null, source_deleted: false,
      duplicate_of_item_id: null, error: state === 'failed' ? 'Path unavailable' : null, updated_at: '' })),
  })
  it('reviews selected folders with editable names and common settings', async () => {
    createBatch.mockReset(); createItem.mockReset(); getBatch.mockReset()
    render(<BatchSourceDialog onClose={vi.fn()} onChanged={vi.fn()} agents={[]} remoteAgentsEnabled={false} defaultSchedule={null} />)
    fireEvent.change(screen.getByLabelText('Allowed root'), { target: { value: 'docs' } })
    fireEvent.click(await screen.findByRole('checkbox', { name: 'Select folder /data/team' }))
    fireEvent.click(screen.getByRole('button', { name: 'Review 1 folder' }))
    expect(screen.getByDisplayValue('team')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Name for /data/team'), { target: { value: 'Team Files' } })
    expect(screen.getByDisplayValue('Team Files')).toBeInTheDocument()
    expect(screen.getByLabelText('Include patterns')).toBeInTheDocument()
    const remove = screen.getByRole('button', { name: 'Remove selected folder /data/team' })
    expect(remove).toHaveClass('border', 'h-10', 'w-10')
    expect(remove).toHaveAttribute('title', 'Remove selected folder /data/team from this batch')
    expect(remove).not.toHaveTextContent('Remove')
    fireEvent.click(remove)
    expect(screen.queryByLabelText('Name for /data/team')).not.toBeInTheDocument()
    await waitFor(() => expect(createBatch).not.toHaveBeenCalled())
  })

  it('reports newly created sources once, including a recovered create, but not duplicates', async () => {
    const onSourceCreated = vi.fn()
    let current = saved(['pending', 'pending'])
    createBatch.mockReset().mockResolvedValue(current)
    createItem.mockReset().mockImplementation(async (_batchId: string, itemId: string) => {
      current = itemId === 'item-0' ? saved(['created', 'pending']) : saved(['created', 'already_exists'])
      return current.items.find((item) => item.id === itemId)
    })
    getBatch.mockReset().mockImplementation(async () => current)
    render(<BatchSourceDialog onClose={vi.fn()} onChanged={vi.fn()} onSourceCreated={onSourceCreated} agents={[]} remoteAgentsEnabled={false} defaultSchedule={null} />)
    fireEvent.change(screen.getByLabelText('Allowed root'), { target: { value: 'docs' } })
    fireEvent.click(await screen.findByRole('checkbox', { name: 'Select folder /data' }))
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select folder /data/team' }))
    fireEvent.click(screen.getByRole('button', { name: 'Review 2 folders' }))
    fireEvent.click(screen.getByRole('button', { name: 'Create 2 sources' }))
    await waitFor(() => expect(screen.getByText('1 created, 1 already existed, 0 duplicate selections, 0 need attention')).toBeInTheDocument())
    expect(onSourceCreated).toHaveBeenCalledTimes(1)
    expect(onSourceCreated).toHaveBeenCalledWith('source-0')
    expect(createItem).toHaveBeenCalledTimes(2)
  })

  it('reopens a completed batch without announcing historical creations or creating again', async () => {
    const onSourceCreated = vi.fn()
    getBatch.mockReset().mockResolvedValue(saved(['created', 'already_exists']))
    createItem.mockReset()
    render(<BatchSourceDialog resumeId="00000000-0000-4000-8000-000000000001" onClose={vi.fn()} onChanged={vi.fn()} onSourceCreated={onSourceCreated} agents={[]} remoteAgentsEnabled={false} defaultSchedule={null} />)
    expect(await screen.findByText('1 created, 1 already existed, 0 duplicate selections, 0 need attention')).toBeInTheDocument()
    expect(onSourceCreated).not.toHaveBeenCalled()
    expect(createItem).not.toHaveBeenCalled()
  })

  it('finishes a duplicate-only batch without announcing a new source or retrying it', async () => {
    const onSourceCreated = vi.fn()
    let current = saved(['pending'])
    createBatch.mockReset().mockResolvedValue(current)
    createItem.mockReset().mockImplementation(async () => { current = saved(['already_exists']); return current.items[0] })
    getBatch.mockReset().mockImplementation(async () => current)
    render(<BatchSourceDialog onClose={vi.fn()} onChanged={vi.fn()} onSourceCreated={onSourceCreated} agents={[]} remoteAgentsEnabled={false} defaultSchedule={null} />)
    fireEvent.change(screen.getByLabelText('Allowed root'), { target: { value: 'docs' } })
    fireEvent.click(await screen.findByRole('checkbox', { name: 'Select folder /data/team' }))
    fireEvent.click(screen.getByRole('button', { name: 'Review 1 folder' }))
    fireEvent.click(screen.getByRole('button', { name: 'Create 1 source' }))
    expect(await screen.findByText('0 created, 1 already existed, 0 duplicate selections, 0 need attention')).toBeInTheDocument()
    expect(screen.getByText('This exact folder already has a source; nothing new was created.')).toBeInTheDocument()
    expect(onSourceCreated).not.toHaveBeenCalled()
    expect(createItem).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('button', { name: /Retry/ })).not.toBeInTheDocument()
  })

  it('keeps a partial batch visible and announces only its created source', async () => {
    const onSourceCreated = vi.fn()
    let current = saved(['pending', 'pending'])
    createBatch.mockReset().mockResolvedValue(current)
    createItem.mockReset().mockImplementation(async (_batchId: string, itemId: string) => {
      current = itemId === 'item-0' ? saved(['created', 'pending']) : saved(['created', 'failed'])
      return current.items.find((item) => item.id === itemId)
    })
    getBatch.mockReset().mockImplementation(async () => current)
    render(<BatchSourceDialog onClose={vi.fn()} onChanged={vi.fn()} onSourceCreated={onSourceCreated} agents={[]} remoteAgentsEnabled={false} defaultSchedule={null} />)
    fireEvent.change(screen.getByLabelText('Allowed root'), { target: { value: 'docs' } })
    fireEvent.click(await screen.findByRole('checkbox', { name: 'Select folder /data' }))
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select folder /data/team' }))
    fireEvent.click(screen.getByRole('button', { name: 'Review 2 folders' }))
    fireEvent.click(screen.getByRole('button', { name: 'Create 2 sources' }))
    expect(await screen.findByText('1 created, 0 already existed, 0 duplicate selections, 1 need attention')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry Folder 1' })).toBeInTheDocument()
    expect(onSourceCreated).toHaveBeenCalledTimes(1)
    expect(createItem).toHaveBeenCalledTimes(2)
  })

  it('shares an in-flight item request when a closed dialog is reopened and resumed', async () => {
    const id = '00000000-0000-4000-8000-000000000012'
    let current = saved(['pending'], id)
    let resolveCreate!: (value: typeof current.items[number]) => void
    const pendingCreate = new Promise<typeof current.items[number]>((resolve) => { resolveCreate = resolve })
    createBatch.mockReset().mockResolvedValue(current)
    createItem.mockReset().mockReturnValue(pendingCreate)
    getBatch.mockReset().mockImplementation(async () => current)

    const first = render(<BatchSourceDialog onClose={vi.fn()} onChanged={vi.fn()} agents={[]} remoteAgentsEnabled={false} defaultSchedule={null} />)
    fireEvent.change(screen.getByLabelText('Allowed root'), { target: { value: 'docs' } })
    fireEvent.click(await screen.findByRole('checkbox', { name: 'Select folder /data/team' }))
    fireEvent.click(screen.getByRole('button', { name: 'Review 1 folder' }))
    fireEvent.click(screen.getByRole('button', { name: 'Create 1 source' }))
    await waitFor(() => expect(createItem).toHaveBeenCalledTimes(1))
    first.unmount()

    render(<BatchSourceDialog resumeId={id} onClose={vi.fn()} onChanged={vi.fn()} agents={[]} remoteAgentsEnabled={false} defaultSchedule={null} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Resume batch' }))
    expect(createItem).toHaveBeenCalledTimes(1)
    current = saved(['created'], id)
    resolveCreate(current.items[0])
    expect(await screen.findByText('1 created, 0 already existed, 0 duplicate selections, 0 need attention')).toBeInTheDocument()
    expect(createItem).toHaveBeenCalledTimes(1)
  })

  it('publishes a saved batch before a slow item request completes so it can be reopened', async () => {
    const id = '00000000-0000-4000-8000-000000000014'
    let current = saved(['pending'], id)
    let resolveCreate!: (value: typeof current.items[number]) => void
    const pendingCreate = new Promise<typeof current.items[number]>((resolve) => { resolveCreate = resolve })
    const onChanged = vi.fn()
    createBatch.mockReset().mockResolvedValue(current)
    createItem.mockReset().mockReturnValue(pendingCreate)
    getBatch.mockReset().mockImplementation(async () => current)

    const first = render(<BatchSourceDialog onClose={vi.fn()} onChanged={onChanged} agents={[]} remoteAgentsEnabled={false} defaultSchedule={null} />)
    fireEvent.change(screen.getByLabelText('Allowed root'), { target: { value: 'docs' } })
    fireEvent.click(await screen.findByRole('checkbox', { name: 'Select folder /data/team' }))
    fireEvent.click(screen.getByRole('button', { name: 'Review 1 folder' }))
    fireEvent.click(screen.getByRole('button', { name: 'Create 1 source' }))
    await waitFor(() => expect(createItem).toHaveBeenCalledTimes(1))
    expect(onChanged).toHaveBeenCalledTimes(1)
    first.unmount()

    render(<BatchSourceDialog resumeId={id} onClose={vi.fn()} onChanged={vi.fn()} agents={[]} remoteAgentsEnabled={false} defaultSchedule={null} />)
    expect(await screen.findByText('0 created, 0 already existed, 0 duplicate selections, 1 need attention')).toBeInTheDocument()
    current = saved(['created'], id)
    resolveCreate(current.items[0])
  })

  it('announces a newly discovered creation after both response and immediate reconciliation were lost', async () => {
    const id = '00000000-0000-4000-8000-000000000013'
    let current = saved(['pending'], id)
    let failReconcile = false
    let rejectCreate!: (error: Error) => void
    createItem.mockReset().mockReturnValue(new Promise((_resolve, reject) => { rejectCreate = reject }))
    getBatch.mockReset().mockImplementation(async () => {
      if (failReconcile) throw new Error('status lost')
      return current
    })
    const first = render(<BatchSourceDialog resumeId={id} onClose={vi.fn()} onChanged={vi.fn()} agents={[]} remoteAgentsEnabled={false} defaultSchedule={null} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Resume batch' }))
    await waitFor(() => expect(createItem).toHaveBeenCalledTimes(1))
    failReconcile = true
    rejectCreate(new Error('response lost'))
    expect(await screen.findByText(/Connection interrupted/)).toBeInTheDocument()
    first.unmount()

    current = saved(['created'], id)
    failReconcile = false
    const onSourceCreated = vi.fn()
    render(<BatchSourceDialog resumeId={id} onClose={vi.fn()} onChanged={vi.fn()} onSourceCreated={onSourceCreated} agents={[]} remoteAgentsEnabled={false} defaultSchedule={null} />)
    expect(await screen.findByText('1 created, 0 already existed, 0 duplicate selections, 0 need attention')).toBeInTheDocument()
    expect(onSourceCreated).toHaveBeenCalledOnce()
    expect(onSourceCreated).toHaveBeenCalledWith('source-0')
    expect(createItem).toHaveBeenCalledTimes(1)
  })

  it('selects and submits folders when randomUUID is unavailable on an HTTP LAN page', async () => {
    let nextByte = 0
    vi.stubGlobal('crypto', {
      getRandomValues: (bytes: Uint8Array) => {
        for (let index = 0; index < bytes.length; index += 1) bytes[index] = nextByte++ % 256
        return bytes
      },
    })
    try {
      createBatch.mockReset().mockResolvedValue(saved(['created', 'created']))
      createItem.mockReset()
      getBatch.mockReset().mockResolvedValue(saved(['created', 'created']))
      render(<BatchSourceDialog onClose={vi.fn()} onChanged={vi.fn()} agents={[]} remoteAgentsEnabled={false} defaultSchedule={null} />)

      fireEvent.change(screen.getByLabelText('Allowed root'), { target: { value: 'docs' } })
      fireEvent.click(await screen.findByRole('checkbox', { name: 'Select folder /data' }))
      fireEvent.click(screen.getByRole('checkbox', { name: 'Select folder /data/team' }))
      expect(screen.getByText('2 of 25 folders selected')).toBeInTheDocument()
      fireEvent.click(screen.getByRole('button', { name: 'Review 2 folders' }))
      fireEvent.click(screen.getByRole('button', { name: 'Create 2 sources' }))

      await waitFor(() => expect(createBatch).toHaveBeenCalledTimes(1))
      const request = createBatch.mock.calls[0][0]
      const ids = [request.id, ...request.items.map((item: { id: string }) => item.id)]
      expect(new Set(ids).size).toBe(3)
      for (const id of ids) expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('recovers a committed batch when the initial response is lost', async () => {
    createBatch.mockReset().mockRejectedValueOnce(new Error('response lost'))
    createItem.mockReset()
    getBatch.mockReset().mockImplementation(async () => saved(['created']))
    render(<BatchSourceDialog onClose={vi.fn()} onChanged={vi.fn()} agents={[]} remoteAgentsEnabled={false} defaultSchedule={null} />)
    fireEvent.change(screen.getByLabelText('Allowed root'), { target: { value: 'docs' } })
    fireEvent.click(await screen.findByRole('checkbox', { name: 'Select folder /data/team' }))
    fireEvent.click(screen.getByRole('button', { name: 'Review 1 folder' }))
    fireEvent.click(screen.getByRole('button', { name: 'Create 1 source' }))
    expect(await screen.findByText('1 created, 0 already existed, 0 duplicate selections, 0 need attention')).toBeInTheDocument()
    expect(createBatch).toHaveBeenCalledTimes(1)
    expect(createItem).not.toHaveBeenCalled()
  })

  it('shows six successes and two failures on reopening without starting pending work', async () => {
    getBatch.mockReset().mockResolvedValue(saved(['created', 'created', 'created', 'created', 'created', 'created', 'failed', 'failed']))
    createItem.mockReset()
    render(<BatchSourceDialog resumeId="00000000-0000-4000-8000-000000000001" onClose={vi.fn()} onChanged={vi.fn()} agents={[]} remoteAgentsEnabled={false} defaultSchedule={null} />)
    expect(await screen.findByText('6 created, 0 already existed, 0 duplicate selections, 2 need attention')).toBeInTheDocument()
    expect(createItem).not.toHaveBeenCalled()
    expect(screen.getAllByRole('button', { name: /Retry Folder/ })).toHaveLength(2)
    expect(screen.getAllByRole('link', { name: 'View source' })).toHaveLength(6)
    expect(screen.getAllByRole('link', { name: 'View source' })[0]).toHaveClass('text-brand-strong')
  })

  it('reconciles a lost create response and never offers retry for the committed item', async () => {
    let current = saved(['pending'])
    getBatch.mockReset().mockImplementation(async () => current)
    createItem.mockReset().mockImplementation(async () => { current = saved(['created']); throw new Error('response lost') })
    render(<BatchSourceDialog resumeId="00000000-0000-4000-8000-000000000001" onClose={vi.fn()} onChanged={vi.fn()} agents={[]} remoteAgentsEnabled={false} defaultSchedule={null} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Resume batch' }))
    expect(await screen.findByText('1 created, 0 already existed, 0 duplicate selections, 0 need attention')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Retry Folder/ })).not.toBeInTheDocument()
    expect(createItem).toHaveBeenCalledTimes(1)
  })
})
