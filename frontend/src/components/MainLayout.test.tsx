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

describe('MainLayout admin link', () => {
  it('shows Admin to admins', () => {
    role = 'admin'
    render(<MemoryRouter><MainLayout /></MemoryRouter>)
    expect(screen.getByText('Admin')).toBeInTheDocument()
  })

  it('hides Admin from members', () => {
    role = 'member'
    render(<MemoryRouter><MainLayout /></MemoryRouter>)
    expect(screen.queryByText('Admin')).not.toBeInTheDocument()
  })
})
