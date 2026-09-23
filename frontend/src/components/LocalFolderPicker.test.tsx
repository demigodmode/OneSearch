import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { LocalFolderPicker } from './LocalFolderPicker'

const refetch = vi.fn()
const rootsState = {
  data: undefined as undefined | { browse_available: boolean; roots: { root_id: string; path: string; label: string }[] },
  isLoading: false,
  isError: false,
  refetch,
}
const browseLocalDirectory = vi.fn()

vi.mock('@/hooks/useApi', () => ({ useLocalSourceRoots: () => rootsState }))
vi.mock('@/lib/api', async () => ({
  ...(await vi.importActual<typeof import('@/lib/api')>('@/lib/api')),
  browseLocalDirectory: (...args: unknown[]) => browseLocalDirectory(...args),
}))

describe('LocalFolderPicker', () => {
  beforeEach(() => {
    Object.assign(rootsState, { data: undefined, isLoading: false, isError: false })
    refetch.mockClear()
    browseLocalDirectory.mockReset()
  })

  it('renders nothing while roots are loading', () => {
    rootsState.isLoading = true
    const { container } = render(<LocalFolderPicker onSelect={vi.fn()} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('offers retry when roots fail to load, without the config hint', () => {
    rootsState.isError = true
    render(<LocalFolderPicker onSelect={vi.fn()} />)
    expect(screen.getByText(/couldn't load source roots/i)).toBeInTheDocument()
    expect(screen.queryByText(/ALLOWED_SOURCE_PATHS/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(refetch).toHaveBeenCalled()
  })

  it('shows the config hint only when browsing is explicitly unavailable', () => {
    rootsState.data = { browse_available: false, roots: [] }
    render(<LocalFolderPicker onSelect={vi.fn()} />)
    expect(screen.getByText(/Set ALLOWED_SOURCE_PATHS to browse folders here/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Allowed root')).not.toBeInTheDocument()
  })

  it('browses local roots and reports the picked folder', async () => {
    rootsState.data = { browse_available: true, roots: [{ root_id: 'local-abc', path: '/data', label: '/data' }] }
    browseLocalDirectory.mockResolvedValueOnce({ root_id: 'local-abc', path: '', entries: [{ name: 'photos', path: 'photos' }], truncated: false })
    browseLocalDirectory.mockResolvedValueOnce({ root_id: 'local-abc', path: 'photos', entries: [], truncated: false })
    const onSelect = vi.fn()
    render(<LocalFolderPicker onSelect={onSelect} />)

    fireEvent.change(screen.getByLabelText('Allowed root'), { target: { value: 'local-abc' } })
    fireEvent.click(await screen.findByRole('button', { name: 'Open folder photos' }))
    expect(browseLocalDirectory).toHaveBeenLastCalledWith('local-abc', 'photos')
    expect(onSelect).toHaveBeenLastCalledWith('/data/photos')
  })
})
