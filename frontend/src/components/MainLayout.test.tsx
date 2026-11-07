// Copyright (C) 2026 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import MainLayout from './MainLayout'

let role: 'admin' | 'member' = 'admin'
vi.mock('@/contexts/useAuth', () => ({
  useAuth: () => ({
    user: { id: 1, username: 'alice', role, is_active: true, created_at: '', must_change_password: false },
    logout: vi.fn(),
  }),
}))

describe('MainLayout settings link', () => {
  it('opens Account from the gear for admins', () => {
    role = 'admin'
    render(<MemoryRouter><MainLayout /></MemoryRouter>)
    expect(screen.getByRole('link', { name: 'Settings' })).toHaveAttribute('href', '/account')
  })

  it('opens Account from the gear for members', () => {
    role = 'member'
    render(<MemoryRouter><MainLayout /></MemoryRouter>)
    expect(screen.getByRole('link', { name: 'Settings' })).toHaveAttribute('href', '/account')
  })

  it('has no separate Account link for either role', () => {
    for (const r of ['admin', 'member'] as const) {
      role = r
      const { unmount } = render(<MemoryRouter><MainLayout /></MemoryRouter>)
      expect(screen.queryByRole('link', { name: 'Account' })).not.toBeInTheDocument()
      unmount()
    }
  })

  it('does not show the old Admin wording', () => {
    role = 'admin'
    render(<MemoryRouter><MainLayout /></MemoryRouter>)
    expect(screen.queryByText('Admin')).not.toBeInTheDocument()
  })
})

describe('MainLayout header controls', () => {
  it('shows the username and a named Logout button to every role', () => {
    for (const r of ['admin', 'member'] as const) {
      role = r
      const { unmount } = render(<MemoryRouter><MainLayout /></MemoryRouter>)
      expect(screen.getByText('alice')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Logout' })).toBeInTheDocument()
      unmount()
    }
  })
})
