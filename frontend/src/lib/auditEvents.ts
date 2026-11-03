// Copyright (C) 2026 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import type { AuditEvent } from '@/types/api'

// Must match services/audit.py AuditAction.
export const AUDIT_ACTIONS = {
  LOGIN: 'auth.login',
  LOGIN_FAILED: 'auth.login_failed',
  USER_CREATED: 'user.created',
  USER_ROLE_CHANGED: 'user.role_changed',
  USER_PASSWORD_RESET: 'user.password_reset',
  USER_PASSWORD_CHANGED: 'user.password_changed',
  USER_DISABLED: 'user.disabled',
  USER_ENABLED: 'user.enabled',
  USER_DELETED: 'user.deleted',
  SETUP_COMPLETED: 'setup.completed',
} as const

export type AuditAction = (typeof AUDIT_ACTIONS)[keyof typeof AUDIT_ACTIONS]

// A dotted prefix matches every action under it.
export const AUDIT_ACTION_PREFIXES = {
  USERS: 'user.',
} as const

type Describe = (event: AuditEvent) => string

const who = (event: AuditEvent) => event.target_label ?? 'someone'

const describers: Record<AuditAction, Describe> = {
  [AUDIT_ACTIONS.LOGIN]: () => 'Signed in',
  [AUDIT_ACTIONS.LOGIN_FAILED]: (event) =>
    event.target_label ? `Failed sign-in as ${event.target_label}` : 'Failed sign-in',
  [AUDIT_ACTIONS.USER_CREATED]: (event) => `Created user ${who(event)}`,
  [AUDIT_ACTIONS.USER_ROLE_CHANGED]: (event) => {
    const detail: Record<string, unknown> = event.detail ?? {}
    return detail.old && detail.new
      ? `Changed ${who(event)} from ${String(detail.old)} to ${String(detail.new)}`
      : `Changed ${who(event)}'s role`
  },
  [AUDIT_ACTIONS.USER_PASSWORD_RESET]: (event) => `Reset ${who(event)}'s password`,
  [AUDIT_ACTIONS.USER_PASSWORD_CHANGED]: () => 'Changed their password',
  [AUDIT_ACTIONS.USER_DISABLED]: (event) => `Disabled ${who(event)}`,
  [AUDIT_ACTIONS.USER_ENABLED]: (event) => `Enabled ${who(event)}`,
  [AUDIT_ACTIONS.USER_DELETED]: (event) => `Deleted ${who(event)}`,
  [AUDIT_ACTIONS.SETUP_COMPLETED]: () => 'Finished setup',
}

function isAuditAction(action: string): action is AuditAction {
  return (Object.values(AUDIT_ACTIONS) as string[]).includes(action)
}

/**
 * The sentence shown in the What column. Actions it doesn't know show their raw name.
 */
export function describeAuditEvent(event: AuditEvent): string {
  if (!isAuditAction(event.action)) return event.action
  return describers[event.action](event)
}
