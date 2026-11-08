// Copyright (C) 2026 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { describe, expect, it } from 'vitest'
import { describeAuditEvent } from './auditEvents'
import type { AuditEvent } from '@/types/api'

function event(overrides: Partial<AuditEvent> & Pick<AuditEvent, 'action'>): AuditEvent {
  return {
    id: 1,
    created_at: '2026-01-02T10:00:00',
    actor_user_id: 1,
    actor_username: 'admin',
    target_type: null,
    target_id: null,
    target_label: null,
    detail: null,
    ip: null,
    ...overrides,
  }
}

describe('describeAuditEvent for the new kinds of entry', () => {
  it.each([
    {
      name: 'a token created by its owner',
      entry: event({ action: 'token.created', actor_username: 'alice', target_label: 'alice', detail: { name: 'ci', expires_in_days: 30 } }),
      sentence: 'Created token ci',
    },
    {
      name: 'a token created for someone else',
      entry: event({ action: 'token.created', actor_username: 'admin', target_label: 'alice', detail: { name: 'ci' } }),
      sentence: 'Created token ci for alice',
    },
    {
      name: 'a token with no name recorded',
      entry: event({ action: 'token.created', actor_username: 'alice', target_label: 'alice' }),
      sentence: 'Created a token',
    },
    {
      name: 'a token revoked by its owner',
      entry: event({ action: 'token.revoked', actor_username: 'alice', target_label: 'alice', detail: { name: 'ci' } }),
      sentence: 'Revoked token ci',
    },
    {
      name: 'a token revoked by an admin',
      entry: event({ action: 'token.revoked', actor_username: 'admin', target_label: 'alice', detail: { name: 'ci' } }),
      sentence: "Revoked alice's token ci",
    },
    {
      name: 'a source added',
      entry: event({ action: 'source.created', target_type: 'source', target_label: 'Docs' }),
      sentence: 'Added source Docs',
    },
    {
      name: 'a source edited',
      entry: event({ action: 'source.updated', target_type: 'source', target_label: 'Docs' }),
      sentence: 'Changed source Docs',
    },
    {
      name: 'a source removed',
      entry: event({ action: 'source.deleted', target_type: 'source', target_label: 'Docs' }),
      sentence: 'Removed source Docs',
    },
    {
      name: 'a reindex',
      entry: event({ action: 'source.reindexed', target_type: 'source', target_label: 'Docs', detail: { full: false } }),
      sentence: 'Requested a reindex of Docs',
    },
    {
      name: 'a full reindex',
      entry: event({ action: 'source.reindexed', target_type: 'source', target_label: 'Docs', detail: { full: true } }),
      sentence: 'Requested a full reindex of Docs',
    },
    {
      name: 'an agent enrollment code',
      entry: event({ action: 'agent.enrollment_created' }),
      sentence: 'Created an agent enrollment code',
    },
    {
      name: 'an agent setting changed',
      entry: event({ action: 'agent.updated', target_type: 'agent', target_label: 'office-pc' }),
      sentence: 'Changed agent office-pc',
    },
    {
      name: 'an agent approved',
      entry: event({ action: 'agent.approved', target_type: 'agent', target_label: 'office-pc' }),
      sentence: 'Approved agent office-pc',
    },
    {
      name: 'an agent disabled',
      entry: event({ action: 'agent.disabled', target_type: 'agent', target_label: 'office-pc' }),
      sentence: 'Disabled agent office-pc',
    },
    {
      name: 'an agent revoked',
      entry: event({ action: 'agent.revoked', target_type: 'agent', target_label: 'office-pc' }),
      sentence: 'Revoked agent office-pc',
    },
    {
      name: 'an agent that revoked itself',
      entry: event({ action: 'agent.revoked', actor_username: null, actor_user_id: null, target_type: 'agent', target_label: 'office-pc', detail: { by: 'agent' } }),
      sentence: 'Agent office-pc revoked itself',
    },
    {
      name: 'settings changed',
      entry: event({ action: 'settings.changed', detail: { keys: ['max_pdf_file_size_mb', 'show_previews'] } }),
      sentence: 'Changed settings: max_pdf_file_size_mb, show_previews',
    },
    {
      name: 'settings changed with no keys recorded',
      entry: event({ action: 'settings.changed' }),
      sentence: 'Changed settings',
    },
  ])('describes $name', ({ entry, sentence }) => {
    expect(describeAuditEvent(entry)).toBe(sentence)
  })
})
