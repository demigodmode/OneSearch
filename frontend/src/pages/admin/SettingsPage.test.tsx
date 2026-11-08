import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SettingsPage from './SettingsPage'

const { useAppSettingsMock } = vi.hoisted(() => ({
  useAppSettingsMock: vi.fn(() => ({ data: { remote_agents_enabled: false, audit_retention_days: 90 }, isLoading: false, error: null })),
}))

const mutate = vi.fn()
let role: 'admin' | 'member' = 'admin'
vi.mock('@/contexts/useAuth', () => ({
  useAuth: () => ({
    user: { id: 1, username: 'alice', role, is_active: true, created_at: '', must_change_password: false },
    logout: vi.fn(),
  }),
}))
vi.mock('@/contexts/useTheme', () => ({ useTheme: () => ({ theme: { id: 'x', brandH: 1, brandS: 1, brandL: 1 }, themeMode: 'dark', customHue: null, setPreset: vi.fn(), setCustomHue: vi.fn(), setThemeMode: vi.fn() }) }))
vi.mock('@/contexts/useSearchSettings', async () => {
  const { DEFAULT_SETTINGS } = await import('@/contexts/searchSettings')
  return { useSearchSettings: () => ({ settings: DEFAULT_SETTINGS, updateSettings: vi.fn() }) }
})
vi.mock('@/hooks/useApi', () => ({ useAppSettings: () => useAppSettingsMock(), useUpdateAppSettings: () => ({ mutate, isPending: false }) }))

beforeEach(() => {
  role = 'admin'
  useAppSettingsMock.mockClear()
})

describe('SettingsPage remote agents', () => {
  it('persists enabling the remote-agents feature', () => {
    render(<SettingsPage />)
    fireEvent.click(screen.getByRole('button', { name: /Remote Agents/ }))
    fireEvent.click(screen.getByRole('switch', { name: /Enable remote agents/ }))
    expect(mutate).toHaveBeenCalledWith({ remote_agents_enabled: true })
  })
})

describe('SettingsPage audit log retention', () => {
  beforeEach(() => {
    mutate.mockClear()
  })

  it('saves a new retention period in days', () => {
    render(<SettingsPage />)
    fireEvent.click(screen.getByRole('button', { name: 'Audit log' }))
    const input = screen.getByLabelText('Keep audit log for (days)')
    expect(input).toHaveValue(90)

    fireEvent.change(input, { target: { value: '30' } })
    fireEvent.blur(input)

    expect(mutate).toHaveBeenCalledWith({ audit_retention_days: 30 })
  })

  it.each(['0', '3651', '2.5'])('does not save %s days', (value) => {
    render(<SettingsPage />)
    fireEvent.click(screen.getByRole('button', { name: 'Audit log' }))
    const input = screen.getByLabelText('Keep audit log for (days)')

    fireEvent.change(input, { target: { value } })
    fireEvent.blur(input)

    expect(mutate).not.toHaveBeenCalled()
    expect(input).toHaveValue(90)
  })
})

describe('SettingsPage for members', () => {
  beforeEach(() => {
    role = 'member'
  })

  it('shows only the per-browser panels', () => {
    render(<SettingsPage />)
    expect(screen.getAllByRole('button').map((button) => button.textContent)).toEqual(['Appearance', 'Search'])
  })

  it('never renders server sections', () => {
    render(<SettingsPage />)
    for (const label of ['File Previews', 'Indexing', 'Scheduling', 'Remote Agents', 'Audit log']) {
      expect(screen.queryByRole('button', { name: label })).not.toBeInTheDocument()
    }
  })

  it('does not request the server app settings', () => {
    render(<SettingsPage />)
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))
    expect(screen.getByText('Results per page')).toBeInTheDocument()
    expect(useAppSettingsMock).not.toHaveBeenCalled()
  })
})

describe('SettingsPage search results per page', () => {
  it('shows the default of 20 as selected', () => {
    render(<SettingsPage />)
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))
    expect(screen.getByRole('radio', { name: '20' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('radio', { name: '10' })).toHaveAttribute('aria-checked', 'false')
  })
})

describe('SettingsPage for admins', () => {
  it('keeps the server panels next to the per-browser ones', () => {
    render(<SettingsPage />)
    expect(screen.getByRole('button', { name: 'Indexing' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Appearance' })).toBeInTheDocument()
  })
})
