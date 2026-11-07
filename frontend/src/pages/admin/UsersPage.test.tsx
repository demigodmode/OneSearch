// Copyright (C) 2026 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import UsersPage from './UsersPage'
import type { AdminUser, ApiToken, User } from '@/types/api'

const api = vi.hoisted(() => ({
  listUsers: vi.fn(),
  createUser: vi.fn(),
  updateUser: vi.fn(),
  resetUserPassword: vi.fn(),
  deleteUser: vi.fn(),
  listUserTokens: vi.fn(),
  revokeUserToken: vi.fn(),
}))
vi.mock('@/lib/api', async (importOriginal) => ({ ...(await importOriginal<typeof import('@/lib/api')>()), ...api }))

const signedIn = vi.hoisted(() => ({ user: null as User | null }))
vi.mock('@/contexts/useAuth', () => ({ useAuth: () => ({ user: signedIn.user, logout: vi.fn() }) }))

const alice: AdminUser = { id: 1, username: 'alice', role: 'admin', is_active: true, must_change_password: false, created_at: '2026-01-02T10:00:00Z', created_by: null, last_login_at: '2026-01-03T10:00:00Z' }
const bob: AdminUser = { id: 2, username: 'bob', role: 'member', is_active: false, must_change_password: true, created_at: '2026-01-04T10:00:00Z', created_by: 'alice', last_login_at: null }
const carol: AdminUser = { id: 3, username: 'carol', role: 'admin', is_active: true, must_change_password: true, created_at: '2026-01-05T10:00:00Z', created_by: 'alice', last_login_at: null }
const laptop: ApiToken = { id: 7, name: 'Laptop', scope: 'search', display_prefix: 'os_AbCd', created_at: '2026-01-02T10:00:00Z', expires_at: null, last_used_at: null, revoked: false, revoked_at: null, status: 'active' }

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <UsersPage />
    </QueryClientProvider>,
  )
}

async function openActions(username: string) {
  await userEvent.click(screen.getByRole('button', { name: `Actions for ${username}` }))
}

describe('UsersPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    signedIn.user = { id: 1, username: 'alice', is_active: true, created_at: '2026-01-02T10:00:00Z', role: 'admin', must_change_password: false }
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

  it('has no actions on your own row', async () => {
    renderPage()
    await screen.findByText('bob')

    expect(screen.queryByRole('button', { name: 'Actions for alice' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Actions for bob' })).toBeInTheDocument()
  })

  it('opens the actions with Enter and returns focus to the trigger on Escape', async () => {
    renderPage()
    await screen.findByText('bob')

    const trigger = screen.getByRole('button', { name: 'Actions for bob' })
    trigger.focus()
    await userEvent.keyboard('{Enter}')
    expect(await screen.findByRole('menuitem', { name: 'Make admin' })).toBeInTheDocument()

    await userEvent.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument())
    expect(trigger).toHaveFocus()
  })

  it('moves into the actions with ArrowDown', async () => {
    renderPage()
    await screen.findByText('bob')

    screen.getByRole('button', { name: 'Actions for bob' }).focus()
    await userEvent.keyboard('{ArrowDown}')
    expect(await screen.findByRole('menuitem', { name: 'Make admin' })).toHaveFocus()
  })

  it('makes a member an admin and refreshes the list', async () => {
    api.listUsers.mockResolvedValueOnce([alice, bob]).mockResolvedValueOnce([alice, { ...bob, role: 'admin' }])
    api.updateUser.mockResolvedValue({ ...bob, role: 'admin' })
    renderPage()
    await screen.findByText('bob')

    await openActions('bob')
    await userEvent.click(screen.getByRole('menuitem', { name: 'Make admin' }))

    await waitFor(() => expect(api.updateUser).toHaveBeenCalledWith(2, { role: 'admin' }))
    await waitFor(() => expect(api.listUsers).toHaveBeenCalledTimes(2))
  })

  it('makes an admin a member', async () => {
    api.listUsers.mockResolvedValue([alice, carol])
    api.updateUser.mockResolvedValue({ ...carol, role: 'member' })
    renderPage()
    await screen.findByText('carol')

    await openActions('carol')
    await userEvent.click(screen.getByRole('menuitem', { name: 'Make member' }))

    await waitFor(() => expect(api.updateUser).toHaveBeenCalledWith(3, { role: 'member' }))
  })

  it('enables a disabled user', async () => {
    api.listUsers.mockResolvedValueOnce([alice, bob]).mockResolvedValueOnce([alice, { ...bob, is_active: true }])
    api.updateUser.mockResolvedValue({ ...bob, is_active: true })
    renderPage()
    await screen.findByText('bob')

    await openActions('bob')
    await userEvent.click(screen.getByRole('menuitem', { name: 'Enable' }))

    await waitFor(() => expect(api.updateUser).toHaveBeenCalledWith(2, { is_active: true }))
    await waitFor(() => expect(api.listUsers).toHaveBeenCalledTimes(2))
  })

  it('disables an active user', async () => {
    api.listUsers.mockResolvedValue([alice, carol])
    api.updateUser.mockResolvedValue({ ...carol, is_active: false })
    renderPage()
    await screen.findByText('carol')

    await openActions('carol')
    await userEvent.click(screen.getByRole('menuitem', { name: 'Disable' }))

    await waitFor(() => expect(api.updateUser).toHaveBeenCalledWith(3, { is_active: false }))
  })

  it('shows the last-admin error from the API when a change is refused', async () => {
    const { ApiError } = await import('@/lib/api')
    const detail = 'There has to be at least one active admin'
    api.listUsers.mockResolvedValue([alice, carol])
    api.updateUser.mockRejectedValue(new ApiError(detail, 409, detail))
    renderPage()
    await screen.findByText('carol')

    await openActions('carol')
    await userEvent.click(screen.getByRole('menuitem', { name: 'Disable' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(detail)
  })

  it('resets a password from a dialog and refreshes the list', async () => {
    api.listUsers.mockResolvedValueOnce([alice, carol]).mockResolvedValueOnce([alice, carol])
    api.resetUserPassword.mockResolvedValue(carol)
    renderPage()
    await screen.findByText('carol')

    await openActions('carol')
    await userEvent.click(screen.getByRole('menuitem', { name: 'Reset password' }))

    const dialog = screen.getByRole('dialog', { name: 'Reset password' })
    expect(within(dialog).getByText('At least 8 characters')).toBeInTheDocument()
    await userEvent.type(within(dialog).getByLabelText('New temporary password'), 'temp-reset-2')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Reset password' }))

    await waitFor(() => expect(api.resetUserPassword).toHaveBeenCalledWith(3, { password: 'temp-reset-2' }))
    await waitFor(() => expect(api.listUsers).toHaveBeenCalledTimes(2))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('rejects a short temporary password before sending it', async () => {
    api.listUsers.mockResolvedValue([alice, carol])
    renderPage()
    await screen.findByText('carol')

    await openActions('carol')
    await userEvent.click(screen.getByRole('menuitem', { name: 'Reset password' }))
    const dialog = screen.getByRole('dialog', { name: 'Reset password' })
    await userEvent.type(within(dialog).getByLabelText('New temporary password'), 'short')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Reset password' }))

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Password must be at least 8 characters')
    expect(api.resetUserPassword).not.toHaveBeenCalled()
  })

  it('deletes a user after confirming and refreshes the list', async () => {
    api.listUsers.mockResolvedValueOnce([alice, bob]).mockResolvedValueOnce([alice])
    api.deleteUser.mockResolvedValue(undefined)
    renderPage()
    await screen.findByText('bob')

    await openActions('bob')
    await userEvent.click(screen.getByRole('menuitem', { name: 'Delete' }))

    const dialog = screen.getByRole('dialog', { name: 'Delete bob?' })
    expect(within(dialog).getByText("This can't be undone. Disabling keeps their history.")).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Delete user' }))

    await waitFor(() => expect(api.deleteUser).toHaveBeenCalledWith(2))
    await waitFor(() => expect(api.listUsers).toHaveBeenCalledTimes(2))
    expect(screen.queryByRole('row', { name: /bob/ })).not.toBeInTheDocument()
  })

  it('does not delete when the confirm dialog is cancelled', async () => {
    renderPage()
    await screen.findByText('bob')

    await openActions('bob')
    await userEvent.click(screen.getByRole('menuitem', { name: 'Delete' }))
    await userEvent.click(within(screen.getByRole('dialog', { name: 'Delete bob?' })).getByRole('button', { name: 'Cancel' }))

    expect(api.deleteUser).not.toHaveBeenCalled()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('shows the API error inside the delete dialog', async () => {
    const { ApiError } = await import('@/lib/api')
    const detail = 'There has to be at least one active admin'
    api.listUsers.mockResolvedValue([alice, carol])
    api.deleteUser.mockRejectedValue(new ApiError(detail, 409, detail))
    renderPage()
    await screen.findByText('carol')

    await openActions('carol')
    await userEvent.click(screen.getByRole('menuitem', { name: 'Delete' }))
    await userEvent.click(within(screen.getByRole('dialog', { name: 'Delete carol?' })).getByRole('button', { name: 'Delete user' }))

    expect(await within(screen.getByRole('dialog', { name: 'Delete carol?' })).findByRole('alert')).toHaveTextContent(detail)
  })

  it('keeps the username in the dialog while it animates closed', async () => {
    // jsdom has no CSS animations. Report an exit animation once the dialog is closed,
    // so Radix keeps it mounted until animationend fires, like a browser would.
    const realGetComputedStyle = window.getComputedStyle
    const styles = vi.spyOn(window, 'getComputedStyle').mockImplementation((el, pseudo) => {
      const style = realGetComputedStyle(el, pseudo)
      if (el instanceof HTMLElement && el.hasAttribute('data-state')) {
        Object.defineProperty(style, 'animationName', { get: () => (el.getAttribute('data-state') === 'closed' ? 'exit' : 'none') })
      }
      return style
    })
    try {
      api.listUsers.mockResolvedValue([alice, bob])
      renderPage()
      await screen.findByText('bob')

      await openActions('bob')
      await userEvent.click(screen.getByRole('menuitem', { name: 'Delete' }))
      const dialog = screen.getByRole('dialog', { name: 'Delete bob?' })
      await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))

      expect(screen.getByRole('heading', { name: 'Delete bob?' })).toBeInTheDocument()
      const animationEnd = Object.assign(new Event('animationend'), { animationName: 'exit' })
      dialog.dispatchEvent(animationEnd)
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    } finally {
      styles.mockRestore()
    }
  })

  it("opens the tokens dialog from the row menu and lists that user's tokens", async () => {
    api.listUsers.mockResolvedValue([alice, bob])
    api.listUserTokens.mockResolvedValue([laptop])
    renderPage()
    await screen.findByText('bob')

    await openActions('bob')
    await userEvent.click(screen.getByRole('menuitem', { name: 'Tokens' }))

    const dialog = within(await screen.findByRole('dialog', { name: "bob's API tokens" }))
    expect(api.listUserTokens).toHaveBeenCalledWith(2)
    const row = within(await dialog.findByRole('row', { name: /Laptop/ }))
    expect(row.getAllByText('Never')).toHaveLength(2)
    expect(row.getByRole('button', { name: 'Revoke' })).toBeInTheDocument()
  })

  it('shows the empty state when the user has no tokens', async () => {
    api.listUsers.mockResolvedValue([alice, bob])
    api.listUserTokens.mockResolvedValue([])
    renderPage()
    await screen.findByText('bob')

    await openActions('bob')
    await userEvent.click(screen.getByRole('menuitem', { name: 'Tokens' }))

    expect(await screen.findByText('bob has no API tokens.')).toBeInTheDocument()
  })

  it("revokes a user's token after confirming and refreshes their list", async () => {
    api.listUsers.mockResolvedValue([alice, bob])
    api.listUserTokens
      .mockResolvedValueOnce([laptop])
      .mockResolvedValue([{ ...laptop, revoked: true, revoked_at: '2026-11-06T09:00:00Z', status: 'revoked' }])
    api.revokeUserToken.mockResolvedValue(undefined)
    renderPage()
    await screen.findByText('bob')

    await openActions('bob')
    await userEvent.click(screen.getByRole('menuitem', { name: 'Tokens' }))
    await userEvent.click(within(await screen.findByRole('row', { name: /Laptop/ })).getByRole('button', { name: 'Revoke' }))
    const confirm = within(screen.getByRole('dialog', { name: 'Revoke Laptop?' }))
    expect(confirm.getByText('Anything using this token will stop working straight away.')).toBeInTheDocument()
    await userEvent.click(confirm.getByRole('button', { name: 'Revoke token' }))

    await waitFor(() => expect(api.revokeUserToken).toHaveBeenCalledWith(2, 7))
    const row = within(await screen.findByRole('row', { name: /Laptop/ }))
    expect(row.getByText(/^Revoked /)).toBeInTheDocument()
    expect(row.queryByRole('button', { name: 'Revoke' })).not.toBeInTheDocument()
    expect(api.listUserTokens).toHaveBeenCalledTimes(2)
  })
})
