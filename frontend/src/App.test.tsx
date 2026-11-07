// Copyright (C) 2026 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import App from './App'

let role: 'admin' | 'member' = 'admin'
vi.mock('@/contexts/useAuth', () => ({
  useAuth: () => ({
    user: { id: 1, username: 'alice', role, is_active: true, created_at: '', must_change_password: false },
    isAuthenticated: true,
    isLoading: false,
    setupRequired: false,
    logout: vi.fn(),
  }),
}))
vi.mock('./contexts/AuthContext', () => ({ AuthProvider: ({ children }: { children: React.ReactNode }) => children }))
vi.mock('@/hooks/useApi', () => ({ useAppSettings: () => ({ data: { remote_agents_enabled: false } }) }))
vi.mock('./pages/SearchPage', () => ({ default: () => <p>search page</p> }))
vi.mock('./pages/AccountPage', () => ({ default: () => <p>account page</p> }))
vi.mock('./pages/admin/SettingsPage', () => ({ default: () => <p>settings page</p> }))
vi.mock('./pages/admin/SourcesPage', () => ({ default: () => <p>sources page</p> }))
vi.mock('./pages/admin/StatusPage', () => ({ default: () => <p>status page</p> }))
vi.mock('./pages/admin/AgentsPage', () => ({ default: () => <p>agents page</p> }))
vi.mock('./pages/admin/UsersPage', () => ({ default: () => <p>users page</p> }))
vi.mock('./pages/admin/AuditLogPage', () => ({ default: () => <p>audit page</p> }))

function renderAt(path: string) {
  return render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>)
}

describe('member routes', () => {
  it.each([
    ['/account', 'account page'],
    ['/settings', 'settings page'],
  ])('renders %s', (path, text) => {
    role = 'member'
    renderAt(path)
    expect(screen.getByText(text)).toBeInTheDocument()
  })

  it.each(['/admin', '/admin/sources', '/admin/users', '/admin/audit', '/admin/settings'])(
    'sends %s back to search',
    (path) => {
      role = 'member'
      renderAt(path)
      expect(screen.getByText('search page')).toBeInTheDocument()
      for (const text of ['sources page', 'status page', 'users page', 'audit page', 'settings page', 'agents page']) {
        expect(screen.queryByText(text)).not.toBeInTheDocument()
      }
    }
  )
})

describe('admin routes', () => {
  it('keeps /admin/settings working as the settings page', () => {
    role = 'admin'
    renderAt('/admin/settings')
    expect(screen.getByText('settings page')).toBeInTheDocument()
  })

  it('keeps /admin opening Sources', () => {
    role = 'admin'
    renderAt('/admin')
    expect(screen.getByText('sources page')).toBeInTheDocument()
  })

  it('renders /settings for admins too', () => {
    role = 'admin'
    renderAt('/settings')
    expect(screen.getByText('settings page')).toBeInTheDocument()
  })
})
