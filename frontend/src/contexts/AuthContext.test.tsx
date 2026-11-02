// Copyright (C) 2026 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '@/contexts/AuthContext'
import { useAuth } from '@/contexts/useAuth'
import type { User } from '@/types/api'

const api = vi.hoisted(() => ({
  getAuthStatus: vi.fn(),
  getToken: vi.fn(),
  getCurrentUser: vi.fn(),
  changePassword: vi.fn(),
  setToken: vi.fn(),
  clearToken: vi.fn(),
}))
vi.mock('@/lib/api', async (importOriginal) => ({ ...(await importOriginal<typeof import('@/lib/api')>()), ...api }))

const temporaryUser: User = { id: 2, username: 'bob', role: 'member', is_active: true, created_at: '2026-01-04T10:00:00Z', must_change_password: true }

function Probe() {
  const { user, changePassword } = useAuth()
  return (
    <>
      <div>{user?.must_change_password ? 'still temporary' : 'settled'}</div>
      <button onClick={() => changePassword('temp-pass-1', 'new-password-1')}>Change</button>
    </>
  )
}

function renderProvider() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <Probe />
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('AuthProvider changePassword', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.getAuthStatus.mockResolvedValue({ setup_required: false })
    api.getToken.mockReturnValue('old-token')
    api.getCurrentUser.mockResolvedValue(temporaryUser)
  })

  it('treats the change as done when reloading the user fails afterwards', async () => {
    api.changePassword.mockResolvedValue({ access_token: 'new-token', token_type: 'bearer', expires_in: 3600 })
    renderProvider()
    await screen.findByText('still temporary')
    api.getCurrentUser.mockRejectedValue(new Error('network down'))

    await userEvent.click(screen.getByRole('button', { name: 'Change' }))

    expect(api.setToken).toHaveBeenCalledWith('new-token')
    expect(await screen.findByText('settled')).toBeInTheDocument()
  })
})
