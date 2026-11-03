// Copyright (C) 2026 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useApiTokens } from '@/hooks/useApi'
import { formatDateTime } from '@/lib/utils'
import type { ApiToken } from '@/types/api'
import { ApiTokenShownDialog, CreateApiTokenDialog, RevokeApiTokenDialog } from './ApiTokenDialogs'

export function ApiTokensSection() {
  const tokens = useApiTokens()
  const [createOpen, setCreateOpen] = useState(false)
  const [shownToken, setShownToken] = useState<string | null>(null)
  // The target stays set after the dialog closes so its title doesn't change mid-animation.
  const [revokeTarget, setRevokeTarget] = useState<ApiToken | null>(null)
  const [revokeOpen, setRevokeOpen] = useState(false)

  return (
    <section className="bg-card border border-border rounded-lg p-6">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <h2 className="text-sm font-semibold text-foreground uppercase tracking-wider">API tokens</h2>
          <p className="text-sm text-muted-foreground mt-1">
            Tokens let scripts and other apps search your documents. They can't change anything.
          </p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>Create token</Button>
      </div>

      {tokens.data && tokens.data.length === 0 && (
        <p className="text-sm text-muted-foreground">You haven't made any API tokens yet.</p>
      )}

      {tokens.data && tokens.data.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Created</TableHead>
              <TableHead>Expires</TableHead>
              <TableHead>Last used</TableHead>
              <TableHead><span className="sr-only">Actions</span></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {tokens.data.map((token) => (
              <TableRow key={token.id}>
                <TableCell className="font-medium">{token.name}</TableCell>
                <TableCell>{formatDateTime(token.created_at)}</TableCell>
                <TableCell>{token.expires_at ? formatDateTime(token.expires_at) : 'Never'}</TableCell>
                <TableCell>{token.last_used_at ? formatDateTime(token.last_used_at) : 'Never'}</TableCell>
                <TableCell>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setRevokeTarget(token)
                      setRevokeOpen(true)
                    }}
                  >
                    Revoke
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      <CreateApiTokenDialog open={createOpen} onOpenChange={setCreateOpen} onCreated={setShownToken} />
      <ApiTokenShownDialog token={shownToken} onClose={() => setShownToken(null)} />
      <RevokeApiTokenDialog token={revokeTarget} open={revokeOpen} onOpenChange={setRevokeOpen} />
    </section>
  )
}
