// Copyright (C) 2026 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SettingsLayout from './SettingsLayout'

const { useAppSettingsMock } = vi.hoisted(() => ({
  useAppSettingsMock: vi.fn(() => ({ data: { remote_agents_enabled: false } })),
}))

let role: 'admin' | 'member' = 'admin'
vi.mock('@/contexts/useAuth', () => ({
  useAuth: () => ({
    user: { id: 1, username: 'alice', role, is_active: true, created_at: '', must_change_password: false },
    logout: vi.fn(),
  }),
}))
vi.mock('@/hooks/useApi', () => ({ useAppSettings: () => useAppSettingsMock() }))

function renderAt(path: string) {
  return render(<MemoryRouter initialEntries={[path]}><SettingsLayout /></MemoryRouter>)
}

function sidebarLabels() {
  return within(screen.getByRole('navigation')).getAllByRole('link').map((link) => link.textContent)
}

describe('SettingsLayout admin sidebar', () => {
  beforeEach(() => {
    role = 'admin'
    useAppSettingsMock.mockReturnValue({ data: { remote_agents_enabled: false } })
  })

  it('puts Account first, then the admin pages in their usual order', () => {
    useAppSettingsMock.mockReturnValue({ data: { remote_agents_enabled: true } })
    renderAt('/admin/sources')
    expect(sidebarLabels()).toEqual(['Account', 'Sources', 'Status', 'Users', 'Audit log', 'Agents', 'Settings'])
  })

  it('hides Agents while remote agents are off', () => {
    renderAt('/admin/sources')
    expect(sidebarLabels()).toEqual(['Account', 'Sources', 'Status', 'Users', 'Audit log', 'Settings'])
  })

  it('shows an Admin group label above the admin pages', () => {
    renderAt('/admin/sources')
    expect(screen.getByText('Admin')).toBeInTheDocument()
  })

  it('links Account and the admin Settings page', () => {
    renderAt('/admin/sources')
    expect(screen.getByRole('link', { name: 'Account' })).toHaveAttribute('href', '/account')
    expect(screen.getByRole('link', { name: 'Settings' })).toHaveAttribute('href', '/admin/settings')
  })

  it('links the Audit log page', () => {
    renderAt('/admin/sources')
    expect(screen.getByRole('link', { name: 'Audit log' })).toHaveAttribute('href', '/admin/audit')
  })
})

describe('SettingsLayout member sidebar', () => {
  beforeEach(() => {
    role = 'member'
    useAppSettingsMock.mockClear()
  })

  it('shows only Account and Settings', () => {
    renderAt('/settings')
    expect(sidebarLabels()).toEqual(['Account', 'Settings'])
    expect(screen.getByRole('link', { name: 'Settings' })).toHaveAttribute('href', '/settings')
  })

  it('does not show the Admin label', () => {
    renderAt('/settings')
    expect(screen.queryByText('Admin')).not.toBeInTheDocument()
  })

  it('does not load server app settings', () => {
    renderAt('/settings')
    expect(useAppSettingsMock).not.toHaveBeenCalled()
  })
})

describe('SettingsLayout header', () => {
  it('shows Settings in the breadcrumb and Back to Search for members', () => {
    role = 'member'
    renderAt('/account')
    expect(within(screen.getByRole('banner')).getByText('Settings')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to Search' })).toHaveAttribute('href', '/')
  })

  it('names Back to Search and the username and logout for admins', () => {
    role = 'admin'
    renderAt('/admin/sources')
    expect(screen.getByRole('link', { name: 'Back to Search' })).toHaveAttribute('href', '/')
    expect(screen.getByText('alice')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Logout' })).toBeInTheDocument()
  })
})
