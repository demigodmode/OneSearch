import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SettingsPage from './SettingsPage'

const mutate = vi.fn()
vi.mock('@/contexts/useTheme', () => ({ useTheme: () => ({ theme: { id: 'x', brandH: 1, brandS: 1, brandL: 1 }, themeMode: 'dark', customHue: null, setPreset: vi.fn(), setCustomHue: vi.fn(), setThemeMode: vi.fn() }) }))
vi.mock('@/contexts/useSearchSettings', () => ({ useSearchSettings: () => ({ settings: {}, updateSettings: vi.fn() }) }))
vi.mock('@/hooks/useApi', () => ({ useAppSettings: () => ({ data: { remote_agents_enabled: false, audit_retention_days: 90 }, isLoading: false, error: null }), useUpdateAppSettings: () => ({ mutate, isPending: false }) }))

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
