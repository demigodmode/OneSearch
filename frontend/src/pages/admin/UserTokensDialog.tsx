// Copyright (C) 2026 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { useState } from 'react'
import { ApiTokenTable } from '@/components/account/ApiTokenTable'
import { RevokeApiTokenDialog } from '@/components/account/ApiTokenDialogs'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useRevokeUserToken, useUserTokens } from '@/hooks/useApi'
import type { AdminUser, ApiToken } from '@/types/api'

interface UserTokensDialogProps {
  user: AdminUser | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function UserTokensDialog({ user, open, onOpenChange }: UserTokensDialogProps) {
  const tokens = useUserTokens(user?.id)
  const revokeToken = useRevokeUserToken()
  // The target stays set after the dialog closes so its title doesn't change mid-animation.
  const [revokeTarget, setRevokeTarget] = useState<ApiToken | null>(null)
  const [revokeOpen, setRevokeOpen] = useState(false)

  if (!user) return null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{`${user.username}'s API tokens`}</DialogTitle>
          <DialogDescription className="sr-only">Tokens this user has made to search documents</DialogDescription>
        </DialogHeader>

        {tokens.isLoading && <p className="text-sm text-muted-foreground">Loading tokens...</p>}
        {tokens.error && <p role="alert" className="text-sm text-destructive">Unable to load tokens.</p>}

        {tokens.data && tokens.data.length === 0 && (
          <p className="text-sm text-muted-foreground">{user.username} has no API tokens.</p>
        )}

        {tokens.data && tokens.data.length > 0 && (
          <ApiTokenTable
            tokens={tokens.data}
            onRevoke={(token) => {
              setRevokeTarget(token)
              setRevokeOpen(true)
            }}
          />
        )}

        <RevokeApiTokenDialog
          token={revokeTarget}
          open={revokeOpen}
          onOpenChange={setRevokeOpen}
          onRevoke={(token) => revokeToken.mutateAsync({ userId: user.id, tokenId: token.id })}
        />
      </DialogContent>
    </Dialog>
  )
}
