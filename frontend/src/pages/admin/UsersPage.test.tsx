// Copyright (C) 2026 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import UsersPage from './UsersPage'
import type { AdminUser } from '@/types/api'

const api = vi.hoisted(() => ({ listUsers: vi.fn(), createUser: vi.fn() }))
vi.mock('@/lib/api', async (importOriginal) => ({ ...(await importOriginal<typeof import('@/lib/api')>()), ...api }))

const alice: AdminUser = { id: 1, username: 'alice', role: 'admin', is_active: true, must_change_password: false, created_at: '2026-01-02T10:00:00Z', created_by: null, last_login_at: '2026-01-03T10:00:00Z' }
const bob: AdminUser = { id: 2, username: 'bob', role: 'member', is_active: false, must_change_password: true, created_at: '2026-01-04T10:00:00Z', created_by: 'alice', last_login_at: null }
const carol: AdminUser = { id: 3, username: 'carol', role: 'admin', is_active: true, must_change_password: true, created_at: '2026-01-05T10:00:00Z', created_by: 'alice', last_login_at: null }

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <UsersPage />
    </QueryClientProvider>,
  )
}

describe('UsersPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.listUsers.mockResolvedValue([alice, bob])
  })

  it('lists users and shows Never when there is no last login', async () => {
    renderPage()
    const bobRow = within(await screen.findByRole('row', { name: /bob/ }))
    expect(bobRow.getByText('Disabled')).toBeInTheDocument()
    expect(bobRow.getByText('Never')).toBeInTheDocument()
    expect(bobRow.getByText('alice')).toBeInTheDocument()
    expect(within(screen.getByRole('row', { name: /^alice/ })).getByText('Active')).toBeInTheDocument()
  })

  it('creates a user, closes the form and refreshes the list', async () => {
    api.listUsers.mockResolvedValueOnce([alice, bob]).mockResolvedValueOnce([alice, bob, carol])
    api.createUser.mockResolvedValue(carol)
    renderPage()
    await screen.findByText('bob')

    await userEvent.click(screen.getByRole('button', { name: 'Create user' }))
    await userEvent.type(screen.getByLabelText('Username'), 'carol')
    fireEvent.change(screen.getByLabelText('Role'), { target: { value: 'admin' } })
    await userEvent.type(screen.getByLabelText('Temporary password'), 'temp-pass-1')
    await userEvent.click(screen.getByRole('button', { name: 'Create user' }))

    await waitFor(() => expect(api.createUser).toHaveBeenCalledWith({ username: 'carol', password: 'temp-pass-1', role: 'admin' }))
    expect(await screen.findByRole('row', { name: /^carol/ })).toBeInTheDocument()
    expect(api.listUsers).toHaveBeenCalledTimes(2)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('shows the duplicate username error and keeps the form open', async () => {
    const { ApiError } = await import('@/lib/api')
    api.createUser.mockRejectedValue(new ApiError('Username already exists', 409, 'Username already exists'))
    renderPage()
    await screen.findByText('bob')

    await userEvent.click(screen.getByRole('button', { name: 'Create user' }))
    await userEvent.type(screen.getByLabelText('Username'), 'alice')
    await userEvent.type(screen.getByLabelText('Temporary password'), 'temp-pass-1')
    await userEvent.click(screen.getByRole('button', { name: 'Create user' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Username already exists')
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })
})
