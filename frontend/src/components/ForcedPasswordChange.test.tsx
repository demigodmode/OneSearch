// Copyright (C) 2026 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ProtectedRoute from './ProtectedRoute'
import { AuthProvider } from '@/contexts/AuthContext'
import type { User } from '@/types/api'

const api = vi.hoisted(() => ({
  getAuthStatus: vi.fn(),
  getToken: vi.fn(),
  getCurrentUser: vi.fn(),
  changePassword: vi.fn(),
  setToken: vi.fn(),
  clearToken: vi.fn(),
  logout: vi.fn(),
}))
vi.mock('@/lib/api', async (importOriginal) => ({ ...(await importOriginal<typeof import('@/lib/api')>()), ...api }))

const temporaryUser: User = { id: 2, username: 'bob', role: 'member', is_active: true, created_at: '2026-01-04T10:00:00Z', must_change_password: true }
const settledUser: User = { ...temporaryUser, must_change_password: false }

function renderApp() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <AuthProvider>
        <Routes>
          <Route path="/" element={<ProtectedRoute><div>Search page</div></ProtectedRoute>} />
          <Route path="/login" element={<div>Login page</div>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('forced password change', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.getAuthStatus.mockResolvedValue({ setup_required: false })
    api.getToken.mockReturnValue('old-token')
    api.getCurrentUser.mockResolvedValue(temporaryUser)
  })

  it('explains that the password is temporary', async () => {
    renderApp()
    expect(
      await screen.findByText("You're signed in with a temporary password. Choose a new one to continue."),
    ).toBeInTheDocument()
  })

  it('changes the password, stores the new token and lands on search', async () => {
    api.getCurrentUser.mockResolvedValueOnce(temporaryUser).mockResolvedValueOnce(settledUser)
    api.changePassword.mockResolvedValue({ access_token: 'new-token', token_type: 'bearer', expires_in: 3600 })
    renderApp()
    await screen.findByText('Choose a new password')

    await userEvent.type(screen.getByLabelText('Current password'), 'temp-pass-1')
    await userEvent.type(screen.getByLabelText('New password'), 'new-password-1')
    await userEvent.type(screen.getByLabelText('Confirm new password'), 'new-password-1')
    await userEvent.click(screen.getByRole('button', { name: 'Save password' }))

    expect(api.changePassword).toHaveBeenCalledWith({ current_password: 'temp-pass-1', new_password: 'new-password-1' })
    expect(api.setToken).toHaveBeenCalledWith('new-token')
    expect(await screen.findByText('Search page')).toBeInTheDocument()
  })

  it('signs out from the change password screen', async () => {
    renderApp()
    await userEvent.click(await screen.findByRole('button', { name: 'Sign out' }))
    expect(api.logout).toHaveBeenCalled()
    expect(await screen.findByText('Login page')).toBeInTheDocument()
  })
})
