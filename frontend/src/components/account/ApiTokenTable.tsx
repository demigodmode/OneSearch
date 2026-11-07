// Copyright (C) 2026 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { formatDateTime } from '@/lib/utils'
import type { ApiToken } from '@/types/api'

interface ApiTokenTableProps {
  tokens: ApiToken[]
  onRevoke: (token: ApiToken) => void
}

function inactiveLabel(token: ApiToken): string {
  if (token.status === 'revoked') {
    return token.revoked_at ? `Revoked ${formatDateTime(token.revoked_at)}` : 'Revoked'
  }
  return token.expires_at ? `Expired ${formatDateTime(token.expires_at)}` : 'Expired'
}

export function ApiTokenTable({ tokens, onRevoke }: ApiTokenTableProps) {
  return (
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
        {tokens.map((token) => {
          const inactive = token.status !== 'active'
          return (
            <TableRow key={token.id} className={inactive ? 'text-muted-foreground opacity-60' : undefined}>
              <TableCell className="font-medium">{token.name}</TableCell>
              <TableCell>{formatDateTime(token.created_at)}</TableCell>
              {inactive ? (
                <TableCell colSpan={2}>{inactiveLabel(token)}</TableCell>
              ) : (
                <>
                  <TableCell>{token.expires_at ? formatDateTime(token.expires_at) : 'Never'}</TableCell>
                  <TableCell>{token.last_used_at ? formatDateTime(token.last_used_at) : 'Never'}</TableCell>
                </>
              )}
              <TableCell>
                {!inactive && (
                  <Button variant="ghost" size="sm" onClick={() => onRevoke(token)}>
                    Revoke
                  </Button>
                )}
              </TableCell>
            </TableRow>
          )
        })}
      </TableBody>
    </Table>
  )
}
