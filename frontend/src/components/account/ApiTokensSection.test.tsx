// Copyright (C) 2026 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiTokensSection } from './ApiTokensSection'
import type { ApiToken, ApiTokenCreated } from '@/types/api'

const api = vi.hoisted(() => ({
  listApiTokens: vi.fn(),
  createApiToken: vi.fn(),
  revokeApiToken: vi.fn(),
}))
vi.mock('@/lib/api', async (importOriginal) => ({ ...(await importOriginal<typeof import('@/lib/api')>()), ...api }))

const laptop: ApiToken = {
  id: 1,
  name: 'Laptop',
  scope: 'search',
  display_prefix: 'os_AbCd',
  created_at: '2026-01-02T10:00:00Z',
  expires_at: null,
  last_used_at: null,
  revoked: false,
}

const SECRET = 'os_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789'

const ownClipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard')

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ApiTokensSection />
    </QueryClientProvider>,
  )
}

describe('ApiTokensSection', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.listApiTokens.mockResolvedValue([laptop])
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
      configurable: true,
    })
  })

  afterEach(() => {
    if (ownClipboard) Object.defineProperty(navigator, 'clipboard', ownClipboard)
    else Reflect.deleteProperty(navigator, 'clipboard')
    Reflect.deleteProperty(navigator, 'userAgent')
  })

  async function openShownToken(token: string) {
    api.createApiToken.mockResolvedValue({ ...laptop, id: 9, name: 'Copy me', token })
    renderSection()
    await screen.findByText('Laptop')
    await userEvent.click(screen.getByRole('button', { name: 'Create token' }))
    const form = within(screen.getByRole('dialog', { name: 'Create API token' }))
    await userEvent.type(form.getByLabelText('Name'), 'Copy me')
    await userEvent.click(form.getByRole('button', { name: 'Create token' }))
    return within(await screen.findByRole('dialog', { name: 'Copy your token' }))
  }

  it('explains what tokens are for', async () => {
    renderSection()

    expect(screen.getByText('API tokens')).toBeInTheDocument()
    expect(
      screen.getByText("Tokens let scripts and other apps search your documents. They can't change anything."),
    ).toBeInTheDocument()
    await screen.findByText('Laptop')
  })

  it('lists tokens with created, expiry and last used', async () => {
    renderSection()

    const row = within(await screen.findByRole('row', { name: /Laptop/ }))
    expect(row.getAllByText('Never')).toHaveLength(2)
    expect(row.getByRole('button', { name: 'Revoke' })).toBeInTheDocument()
  })

  it('shows an empty state when there are no tokens', async () => {
    api.listApiTokens.mockResolvedValue([])
    renderSection()

    expect(await screen.findByText("You haven't made any API tokens yet.")).toBeInTheDocument()
    expect(screen.queryByRole('row', { name: /Laptop/ })).not.toBeInTheDocument()
  })

  it('creates a token, shows the secret once, then forgets it', async () => {
    const created: ApiTokenCreated = { ...laptop, id: 2, name: 'Backup script', expires_at: '2026-12-02T10:00:00Z', token: SECRET }
    api.createApiToken.mockResolvedValue(created)
    api.listApiTokens.mockResolvedValueOnce([laptop]).mockResolvedValue([created, laptop])
    renderSection()
    await screen.findByText('Laptop')

    await userEvent.click(screen.getByRole('button', { name: 'Create token' }))
    const form = within(screen.getByRole('dialog', { name: 'Create API token' }))
    await userEvent.type(form.getByLabelText('Name'), 'Backup script')
    await userEvent.selectOptions(form.getByLabelText('Expires'), '30 days')
    await userEvent.click(form.getByRole('button', { name: 'Create token' }))

    expect(api.createApiToken).toHaveBeenCalledWith({ name: 'Backup script', expires_in_days: 30 })
    const shown = within(await screen.findByRole('dialog', { name: 'Copy your token' }))
    expect(shown.getByLabelText('Token')).toHaveValue(SECRET)
    expect(shown.getByLabelText('Token')).toHaveAttribute('readonly')
    expect(shown.getByText("You won't be able to see this token again.")).toBeInTheDocument()

    await userEvent.click(shown.getByRole('button', { name: 'Copy' }))
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(SECRET)

    await userEvent.click(shown.getByRole('button', { name: 'Done' }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Copy your token' })).not.toBeInTheDocument())
    expect(screen.queryByDisplayValue(SECRET)).not.toBeInTheDocument()
    expect(await screen.findByRole('row', { name: /Backup script/ })).toBeInTheDocument()
  })

  it('creates a token that never expires by default', async () => {
    api.createApiToken.mockResolvedValue({ ...laptop, id: 3, name: 'Forever', token: SECRET })
    renderSection()
    await screen.findByText('Laptop')

    await userEvent.click(screen.getByRole('button', { name: 'Create token' }))
    const form = within(screen.getByRole('dialog', { name: 'Create API token' }))
    expect(form.getByLabelText('Expires')).toHaveValue('never')
    await userEvent.type(form.getByLabelText('Name'), 'Forever')
    await userEvent.click(form.getByRole('button', { name: 'Create token' }))

    expect(api.createApiToken).toHaveBeenCalledWith({ name: 'Forever', expires_in_days: null })
  })

  it('offers never, 30 days, 90 days and 1 year', async () => {
    renderSection()
    await screen.findByText('Laptop')

    await userEvent.click(screen.getByRole('button', { name: 'Create token' }))
    const select = within(screen.getByRole('dialog', { name: 'Create API token' })).getByLabelText('Expires')
    const options = within(select).getAllByRole('option').map((option) => option.textContent)
    expect(options).toEqual(['Never', '30 days', '90 days', '1 year'])
  })

  it('shows the server error when creating fails and keeps the form open', async () => {
    api.createApiToken.mockRejectedValue(new Error('Something went wrong'))
    renderSection()
    await screen.findByText('Laptop')

    await userEvent.click(screen.getByRole('button', { name: 'Create token' }))
    const form = within(screen.getByRole('dialog', { name: 'Create API token' }))
    await userEvent.type(form.getByLabelText('Name'), 'Broken')
    await userEvent.click(form.getByRole('button', { name: 'Create token' }))

    expect(await form.findByRole('alert')).toHaveTextContent('Something went wrong')
    expect(screen.queryByRole('dialog', { name: 'Copy your token' })).not.toBeInTheDocument()
  })

  it('revokes a token after confirming', async () => {
    api.revokeApiToken.mockResolvedValue(undefined)
    api.listApiTokens.mockResolvedValueOnce([laptop]).mockResolvedValue([])
    renderSection()

    await userEvent.click(within(await screen.findByRole('row', { name: /Laptop/ })).getByRole('button', { name: 'Revoke' }))
    const confirm = within(screen.getByRole('dialog', { name: 'Revoke Laptop?' }))
    await userEvent.click(confirm.getByRole('button', { name: 'Revoke token' }))

    expect(api.revokeApiToken).toHaveBeenCalledWith(1)
    await waitFor(() => expect(screen.queryByRole('row', { name: /Laptop/ })).not.toBeInTheDocument())
    expect(await screen.findByText("You haven't made any API tokens yet.")).toBeInTheDocument()
  })

  it('leaves the token alone when revoke is cancelled', async () => {
    renderSection()

    await userEvent.click(within(await screen.findByRole('row', { name: /Laptop/ })).getByRole('button', { name: 'Revoke' }))
    await userEvent.click(within(screen.getByRole('dialog', { name: 'Revoke Laptop?' })).getByRole('button', { name: 'Cancel' }))

    expect(api.revokeApiToken).not.toHaveBeenCalled()
    expect(screen.getByRole('row', { name: /Laptop/ })).toBeInTheDocument()
  })

  it('says Copied after copying, then goes back to Copy', async () => {
    const shown = await openShownToken(SECRET)

    await userEvent.click(shown.getByRole('button', { name: 'Copy' }))

    expect(await shown.findByRole('button', { name: 'Copied' })).toBeInTheDocument()
    await waitFor(() => expect(shown.getByRole('button', { name: 'Copy' })).toBeInTheDocument(), { timeout: 3000 })
  })

  it('selects the token and says to copy it by hand when there is no clipboard', async () => {
    Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true })
    const shown = await openShownToken(SECRET)

    await userEvent.click(shown.getByRole('button', { name: 'Copy' }))

    expect(shown.getByRole('status')).toHaveTextContent('Press Ctrl+C to copy')
    const field = shown.getByLabelText('Token') as HTMLInputElement
    expect(field.selectionStart).toBe(0)
    expect(field.selectionEnd).toBe(SECRET.length)
  })

  it('names Cmd+C on a Mac', async () => {
    Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true })
    Object.defineProperty(navigator, 'userAgent', {
      value: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15',
      configurable: true,
    })
    const shown = await openShownToken(SECRET)

    await userEvent.click(shown.getByRole('button', { name: 'Copy' }))

    expect(shown.getByRole('status')).toHaveTextContent('Press Cmd+C to copy')
  })
})
