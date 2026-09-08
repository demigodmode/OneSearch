import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import SettingsPage from './SettingsPage'

const mutate = vi.fn()
vi.mock('@/contexts/useTheme', () => ({ useTheme: () => ({ theme: { id: 'x', brandH: 1, brandS: 1, brandL: 1 }, themeMode: 'dark', customHue: null, setPreset: vi.fn(), setCustomHue: vi.fn(), setThemeMode: vi.fn() }) }))
vi.mock('@/contexts/useSearchSettings', () => ({ useSearchSettings: () => ({ settings: {}, updateSettings: vi.fn() }) }))
vi.mock('@/hooks/useApi', () => ({ useAppSettings: () => ({ data: { remote_agents_enabled: false }, isLoading: false, error: null }), useUpdateAppSettings: () => ({ mutate, isPending: false }) }))

describe('SettingsPage remote agents', () => {
  it('persists enabling the remote-agents feature', () => {
    render(<SettingsPage />)
    fireEvent.click(screen.getByRole('button', { name: /Remote Agents/ }))
    fireEvent.click(screen.getByRole('switch', { name: /Enable remote agents/ }))
    expect(mutate).toHaveBeenCalledWith({ remote_agents_enabled: true })
  })
})
