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
  TOKEN_CREATED: 'token.created',
  TOKEN_REVOKED: 'token.revoked',
  SOURCE_CREATED: 'source.created',
  SOURCE_UPDATED: 'source.updated',
  SOURCE_DELETED: 'source.deleted',
  SOURCE_REINDEXED: 'source.reindexed',
  AGENT_ENROLLMENT_CREATED: 'agent.enrollment_created',
  AGENT_UPDATED: 'agent.updated',
  AGENT_APPROVED: 'agent.approved',
  AGENT_DISABLED: 'agent.disabled',
  AGENT_REVOKED: 'agent.revoked',
  SETTINGS_CHANGED: 'settings.changed',
} as const

export type AuditAction = (typeof AUDIT_ACTIONS)[keyof typeof AUDIT_ACTIONS]

// A dotted prefix matches every action under it.
export const AUDIT_ACTION_PREFIXES = {
  USERS: 'user.',
  TOKENS: 'token.',
  SOURCES: 'source.',
  AGENTS: 'agent.',
  SETTINGS: 'settings.',
} as const

type Describe = (event: AuditEvent) => string

const who = (event: AuditEvent) => event.target_label ?? 'someone'

const detailString = (event: AuditEvent, key: string): string | null => {
  const value = event.detail?.[key]
  return typeof value === 'string' && value ? value : null
}

// A token's owner is the target. Say whose it is only when someone else did it.
const tokenOwnerSuffix = (event: AuditEvent) =>
  event.target_label && event.target_label !== event.actor_username ? ` for ${event.target_label}` : ''

const tokenOwnerPossessive = (event: AuditEvent) =>
  event.target_label && event.target_label !== event.actor_username ? `${event.target_label}'s token` : 'token'

const sourceName = (event: AuditEvent) => event.target_label ?? 'a source'

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
  [AUDIT_ACTIONS.TOKEN_CREATED]: (event) => {
    const name = detailString(event, 'name')
    return name ? `Created token ${name}${tokenOwnerSuffix(event)}` : 'Created a token'
  },
  [AUDIT_ACTIONS.TOKEN_REVOKED]: (event) => {
    const name = detailString(event, 'name')
    return name ? `Revoked ${tokenOwnerPossessive(event)} ${name}` : 'Revoked a token'
  },
  [AUDIT_ACTIONS.SOURCE_CREATED]: (event) => `Added source ${sourceName(event)}`,
  [AUDIT_ACTIONS.SOURCE_UPDATED]: (event) => `Changed source ${sourceName(event)}`,
  [AUDIT_ACTIONS.SOURCE_DELETED]: (event) => `Removed source ${sourceName(event)}`,
  [AUDIT_ACTIONS.SOURCE_REINDEXED]: (event) =>
    `Requested a ${event.detail?.full === true ? 'full ' : ''}reindex of ${sourceName(event)}`,
  [AUDIT_ACTIONS.AGENT_ENROLLMENT_CREATED]: () => 'Created an agent enrollment code',
  [AUDIT_ACTIONS.AGENT_UPDATED]: (event) => `Changed agent ${who(event)}`,
  [AUDIT_ACTIONS.AGENT_APPROVED]: (event) => `Approved agent ${who(event)}`,
  [AUDIT_ACTIONS.AGENT_DISABLED]: (event) => `Disabled agent ${who(event)}`,
  [AUDIT_ACTIONS.AGENT_REVOKED]: (event) =>
    detailString(event, 'by') === 'agent'
      ? `Agent ${who(event)} revoked itself`
      : `Revoked agent ${who(event)}`,
  [AUDIT_ACTIONS.SETTINGS_CHANGED]: (event) => {
    const changed = event.detail?.keys
    const keys = Array.isArray(changed) ? changed.map(String) : []
    return keys.length ? `Changed settings: ${keys.join(', ')}` : 'Changed settings'
  },
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
