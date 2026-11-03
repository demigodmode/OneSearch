// Copyright (C) 2026 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AuditLogPage from './AuditLogPage'
import type { AuditEvent, AuditPage } from '@/types/api'

const api = vi.hoisted(() => ({
  listAuditEvents: vi.fn(),
}))
vi.mock('@/lib/api', async (importOriginal) => ({ ...(await importOriginal<typeof import('@/lib/api')>()), ...api }))

function event(overrides: Partial<AuditEvent> & Pick<AuditEvent, 'id' | 'action'>): AuditEvent {
  return {
    created_at: '2026-01-02T10:00:00',
    actor_user_id: 1,
    actor_username: 'alice',
    target_type: null,
    target_id: null,
    target_label: null,
    detail: null,
    ip: null,
    ...overrides,
  }
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <AuditLogPage />
    </QueryClientProvider>,
  )
}

function page(events: AuditEvent[], next: number | null = null): AuditPage {
  return { events, next_before: next }
}

describe('AuditLogPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.listAuditEvents.mockResolvedValue(page([]))
  })

  it('shows the heading, subtitle and filters', async () => {
    renderPage()

    expect(screen.getByRole('heading', { name: 'Audit log' })).toBeInTheDocument()
    expect(screen.getByText('Who changed what, and every sign-in. Kept for 90 days.')).toBeInTheDocument()
    expect(screen.getByLabelText('User')).toBeInTheDocument()
    const eventSelect = screen.getByLabelText('Event')
    expect(within(eventSelect).getAllByRole('option').map((option) => option.textContent)).toEqual([
      'All',
      'Sign-ins',
      'Failed sign-ins',
      'Users',
    ])
    await screen.findByText('No audit entries match these filters.')
  })

  it.each([
    { action: 'auth.login', entry: event({ id: 1, action: 'auth.login' }), sentence: 'Signed in' },
    {
      action: 'auth.login_failed',
      entry: event({ id: 2, action: 'auth.login_failed', actor_username: null, target_label: 'bob' }),
      sentence: 'Failed sign-in as bob',
    },
    {
      action: 'user.created',
      entry: event({ id: 3, action: 'user.created', target_label: 'bob' }),
      sentence: 'Created user bob',
    },
    {
      action: 'user.role_changed',
      entry: event({ id: 4, action: 'user.role_changed', target_label: 'bob', detail: { old: 'member', new: 'admin' } }),
      sentence: 'Changed bob from member to admin',
    },
    {
      action: 'user.password_reset',
      entry: event({ id: 5, action: 'user.password_reset', target_label: 'bob' }),
      sentence: "Reset bob's password",
    },
    {
      action: 'user.password_changed',
      entry: event({ id: 6, action: 'user.password_changed', target_label: 'alice' }),
      sentence: 'Changed their password',
    },
    { action: 'user.disabled', entry: event({ id: 7, action: 'user.disabled', target_label: 'bob' }), sentence: 'Disabled bob' },
    { action: 'user.enabled', entry: event({ id: 8, action: 'user.enabled', target_label: 'bob' }), sentence: 'Enabled bob' },
    { action: 'user.deleted', entry: event({ id: 9, action: 'user.deleted', target_label: 'bob' }), sentence: 'Deleted bob' },
    {
      action: 'setup.completed',
      entry: event({ id: 10, action: 'setup.completed', target_label: 'owner' }),
      sentence: 'Finished setup',
    },
    {
      action: 'settings.changed',
      entry: event({ id: 11, action: 'settings.changed' }),
      sentence: 'settings.changed',
    },
  ])('describes $action as a sentence', async ({ entry, sentence }) => {
    api.listAuditEvents.mockResolvedValue(page([entry]))
    renderPage()

    const row = within(await screen.findByRole('row', { name: new RegExp(sentence) }))
    expect(row.getByText(sentence)).toBeInTheDocument()
  })

  it('shows the actor, the time and the IP in the table', async () => {
    api.listAuditEvents.mockResolvedValue(
      page([event({ id: 1, action: 'auth.login_failed', actor_username: null, target_label: 'ghost', ip: '203.0.113.7' })]),
    )
    renderPage()

    const row = within(await screen.findByRole('row', { name: /Failed sign-in as ghost/ }))
    expect(row.getByText('—')).toBeInTheDocument()
    expect(row.getByText('IP 203.0.113.7')).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'When' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Who' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'What' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Details' })).toBeInTheDocument()
  })

  it('sends the user filter as a query param after a short pause', async () => {
    renderPage()
    await waitFor(() => expect(api.listAuditEvents).toHaveBeenCalled())
    api.listAuditEvents.mockClear()

    await userEvent.type(screen.getByLabelText('User'), 'bob')

    await waitFor(() => expect(api.listAuditEvents).toHaveBeenLastCalledWith({ user: 'bob' }))
  })

  it('sends the event filter as an action name or prefix', async () => {
    renderPage()
    await waitFor(() => expect(api.listAuditEvents).toHaveBeenCalled())

    fireEvent.change(screen.getByLabelText('Event'), { target: { value: 'auth.login_failed' } })
    await waitFor(() => expect(api.listAuditEvents).toHaveBeenLastCalledWith({ action: 'auth.login_failed' }))

    fireEvent.change(screen.getByLabelText('Event'), { target: { value: 'user.' } })
    await waitFor(() => expect(api.listAuditEvents).toHaveBeenLastCalledWith({ action: 'user.' }))

    fireEvent.change(screen.getByLabelText('Event'), { target: { value: 'all' } })
    await waitFor(() => expect(api.listAuditEvents).toHaveBeenLastCalledWith({}))
  })

  it('appends the next page when Load more is pressed', async () => {
    api.listAuditEvents
      .mockResolvedValueOnce(page([event({ id: 5, action: 'user.deleted', target_label: 'carol' })], 5))
      .mockResolvedValueOnce(page([event({ id: 4, action: 'user.disabled', target_label: 'bob' })], null))
    renderPage()
    await screen.findByRole('row', { name: /Deleted carol/ })

    await userEvent.click(screen.getByRole('button', { name: 'Load more' }))

    await screen.findByRole('row', { name: /Disabled bob/ })
    expect(screen.getByRole('row', { name: /Deleted carol/ })).toBeInTheDocument()
    expect(api.listAuditEvents).toHaveBeenLastCalledWith({ before: 5 })
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
  })

  it('shows an error when the log cannot be loaded', async () => {
    api.listAuditEvents.mockRejectedValue(new Error('nope'))
    renderPage()

    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load the audit log.')
  })
})
