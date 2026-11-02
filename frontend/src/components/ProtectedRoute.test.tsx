// Copyright (C) 2026 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import ProtectedRoute from './ProtectedRoute'
import AdminLayout from './AdminLayout'

let auth = { user: null as null | { role: 'admin' | 'member' }, isAuthenticated: true, isLoading: false, setupRequired: false }
vi.mock('@/contexts/useAuth', () => ({ useAuth: () => ({ ...auth, logout: vi.fn() }) }))
vi.mock('@/hooks/useApi', () => ({ useAppSettings: () => ({ data: { remote_agents_enabled: false } }) }))

function renderAdminRoute(path = '/admin/sources') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/" element={<div>Search page</div>} />
        <Route
          path="/admin"
          element={<ProtectedRoute requireAdmin><AdminLayout /></ProtectedRoute>}
        >
          <Route path="sources" element={<div>Sources content</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

describe('ProtectedRoute requireAdmin', () => {
  it('sends a member to search', () => {
    auth = { user: { role: 'member' }, isAuthenticated: true, isLoading: false, setupRequired: false }
    renderAdminRoute()
    expect(screen.getByText('Search page')).toBeInTheDocument()
    expect(screen.queryByText('Sources content')).not.toBeInTheDocument()
  })

  it('renders the admin layout for an admin', () => {
    auth = { user: { role: 'admin' }, isAuthenticated: true, isLoading: false, setupRequired: false }
    renderAdminRoute()
    expect(screen.getByText('Back to Search')).toBeInTheDocument()
    expect(screen.getByText('Sources content')).toBeInTheDocument()
  })

  it('does not redirect while the user is still loading', () => {
    auth = { user: null, isAuthenticated: false, isLoading: true, setupRequired: false }
    renderAdminRoute()
    expect(screen.getByText('Loading...')).toBeInTheDocument()
    expect(screen.queryByText('Search page')).not.toBeInTheDocument()
    expect(screen.queryByText('Sources content')).not.toBeInTheDocument()
  })
})
