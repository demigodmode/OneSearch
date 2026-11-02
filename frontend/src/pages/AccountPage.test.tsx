// Copyright (C) 2026 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AccountPage from './AccountPage'

const auth = vi.hoisted(() => ({ changePassword: vi.fn() }))
vi.mock('@/contexts/useAuth', () => ({ useAuth: () => ({ changePassword: auth.changePassword }) }))

async function fillForm(current: string, next: string, confirm: string) {
  await userEvent.type(screen.getByLabelText('Current password'), current)
  await userEvent.type(screen.getByLabelText('New password'), next)
  await userEvent.type(screen.getByLabelText('Confirm new password'), confirm)
  await userEvent.click(screen.getByRole('button', { name: 'Change password' }))
}

describe('AccountPage change password', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('rejects a confirmation that does not match', async () => {
    render(<AccountPage />)
    await fillForm('old-password', 'new-password-1', 'new-password-2')
    expect(screen.getByRole('alert')).toHaveTextContent("Passwords don't match")
    expect(auth.changePassword).not.toHaveBeenCalled()
  })

  it('rejects a new password shorter than 8 characters', async () => {
    render(<AccountPage />)
    await fillForm('old-password', 'short', 'short')
    expect(screen.getByRole('alert')).toHaveTextContent('Password must be at least 8 characters')
    expect(auth.changePassword).not.toHaveBeenCalled()
  })

  it('shows the server error when the current password is wrong', async () => {
    auth.changePassword.mockRejectedValue(new Error('Current password is incorrect'))
    render(<AccountPage />)
    await fillForm('wrong-password', 'new-password-1', 'new-password-1')
    expect(await screen.findByRole('alert')).toHaveTextContent('Current password is incorrect')
  })

  it('confirms success', async () => {
    auth.changePassword.mockResolvedValue(undefined)
    render(<AccountPage />)
    await fillForm('old-password', 'new-password-1', 'new-password-1')
    expect(auth.changePassword).toHaveBeenCalledWith('old-password', 'new-password-1')
    expect(await screen.findByText('Password changed')).toBeInTheDocument()
  })
})
