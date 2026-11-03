// Copyright (C) 2026 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useAuditEvents } from '@/hooks/useApi'
import { AUDIT_ACTION_PREFIXES, AUDIT_ACTIONS, describeAuditEvent } from '@/lib/auditEvents'
import { formatDateTime } from '@/lib/utils'
import type { AuditEvent, AuditQuery } from '@/types/api'

// Option values are the action names the API filters on. Prefixes end with a dot and match every action under them.
const EVENT_OPTIONS = [
  { value: 'all', label: 'All' },
  { value: AUDIT_ACTIONS.LOGIN, label: 'Sign-ins' },
  { value: AUDIT_ACTIONS.LOGIN_FAILED, label: 'Failed sign-ins' },
  { value: AUDIT_ACTION_PREFIXES.USERS, label: 'Users' },
  { value: AUDIT_ACTION_PREFIXES.TOKENS, label: 'Tokens' },
  { value: AUDIT_ACTION_PREFIXES.SOURCES, label: 'Sources' },
  { value: AUDIT_ACTION_PREFIXES.AGENTS, label: 'Agents' },
  { value: AUDIT_ACTION_PREFIXES.SETTINGS, label: 'Settings' },
]

const USER_FILTER_DELAY_MS = 300

function detailsFor(event: AuditEvent): string {
  const parts = [event.detail?.reason, event.ip ? `IP ${event.ip}` : null].filter(Boolean)
  return parts.length ? parts.join(' · ') : '—'
}

export default function AuditLogPage() {
  const [userDraft, setUserDraft] = useState('')
  const [user, setUser] = useState('')
  const [action, setAction] = useState('all')

  useEffect(() => {
    const timer = setTimeout(() => setUser(userDraft.trim()), USER_FILTER_DELAY_MS)
    return () => clearTimeout(timer)
  }, [userDraft])

  const filters: Omit<AuditQuery, 'before'> = {}
  if (user) filters.user = user
  if (action !== 'all') filters.action = action

  const audit = useAuditEvents(filters)
  const events = audit.data?.pages.flatMap((page) => page.events) ?? []

  return (
    <div className="animate-fade-in">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-foreground tracking-tight">Audit log</h1>
        <p className="text-sm text-muted-foreground mt-1">Who changed what, and every sign-in. Old entries are deleted automatically.</p>
      </div>

      <div className="mb-4 flex flex-col sm:flex-row gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="audit-user">User</Label>
          <Input
            id="audit-user"
            value={userDraft}
            onChange={(event) => setUserDraft(event.target.value)}
            placeholder="Any user"
            className="sm:w-56"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="audit-event">Event</Label>
          <select
            id="audit-event"
            value={action}
            onChange={(event) => setAction(event.target.value)}
            className="rounded-lg border border-border bg-background px-3 py-2 text-sm sm:w-56"
          >
            {EVENT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </div>
      </div>

      {audit.isLoading && <p className="text-sm text-muted-foreground">Loading audit log...</p>}
      {audit.error && <p role="alert" className="text-sm text-destructive">Unable to load the audit log.</p>}

      {audit.data && (
        <div className="bg-card border border-border rounded-lg">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>When</TableHead>
                <TableHead>Who</TableHead>
                <TableHead>What</TableHead>
                <TableHead>Details</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {events.map((event) => (
                <TableRow key={event.id}>
                  <TableCell>{formatDateTime(event.created_at)}</TableCell>
                  <TableCell>{event.actor_username ?? '—'}</TableCell>
                  <TableCell>{describeAuditEvent(event)}</TableCell>
                  <TableCell className="text-muted-foreground">{detailsFor(event)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {events.length === 0 && (
            <p className="p-4 text-sm text-muted-foreground">No audit entries match these filters.</p>
          )}
        </div>
      )}

      {audit.hasNextPage && (
        <div className="mt-4 flex justify-center">
          <Button variant="outline" onClick={() => audit.fetchNextPage()} disabled={audit.isFetchingNextPage}>
            {audit.isFetchingNextPage ? 'Loading...' : 'Load more'}
          </Button>
        </div>
      )}
    </div>
  )
}
