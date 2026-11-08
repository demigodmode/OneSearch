// Copyright (C) 2026 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useResetUserPassword } from '@/hooks/useApi'
import { PASSWORD_LENGTH_HINT, validateNewPassword } from '@/lib/passwordPolicy'
import type { AdminUser } from '@/types/api'

interface ResetPasswordDialogProps {
  user: AdminUser | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function ResetPasswordDialog({ user, open, onOpenChange }: ResetPasswordDialogProps) {
  const resetPassword = useResetUserPassword()
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')

  const handleOpenChange = (next: boolean) => {
    if (!next) {
      setPassword('')
      setError('')
    }
    onOpenChange(next)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    if (!user) return

    const passwordError = validateNewPassword(password)
    if (passwordError) {
      setError(passwordError)
      return
    }

    try {
      await resetPassword.mutateAsync({ id: user.id, data: { password } })
      handleOpenChange(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not reset password')
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Reset password</DialogTitle>
          <DialogDescription>
            {user?.username} will be asked to choose a new password at their next sign-in. Their current sessions end.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <p role="alert" className="text-sm text-destructive">{error}</p>
          )}

          <div className="space-y-2">
            <Label htmlFor="reset-user-password">New temporary password</Label>
            <Input
              id="reset-user-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              required
            />
            <p className="text-xs text-muted-foreground">{PASSWORD_LENGTH_HINT}</p>
          </div>

          <DialogFooter>
            <Button type="submit" disabled={resetPassword.isPending}>
              Reset password
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
