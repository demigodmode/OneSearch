// Copyright (C) 2026 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { useState } from 'react'
import { useAuth } from '@/contexts/useAuth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PASSWORD_LENGTH_HINT, validateNewPassword } from '@/lib/passwordPolicy'
import { AlertCircle, CheckCircle } from 'lucide-react'

interface PasswordChangeFormProps {
  submitLabel: string
  onChanged?: () => void
}

export function PasswordChangeForm({ submitLabel, onChanged }: PasswordChangeFormProps) {
  const { changePassword } = useAuth()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [changed, setChanged] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setChanged(false)

    if (newPassword !== confirmPassword) {
      setError("Passwords don't match")
      return
    }
    const passwordError = validateNewPassword(newPassword)
    if (passwordError) {
      setError(passwordError)
      return
    }

    setSubmitting(true)
    try {
      await changePassword(currentPassword, newPassword)
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      setChanged(true)
      onChanged?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not change password')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && (
        <p role="alert" className="flex items-center gap-2 text-sm text-destructive">
          <AlertCircle className="h-4 w-4" /> {error}
        </p>
      )}
      {changed && (
        <p role="status" className="flex items-center gap-2 text-sm text-success">
          <CheckCircle className="h-4 w-4" /> Password changed
        </p>
      )}

      <div className="space-y-2">
        <Label htmlFor="current-password">Current password</Label>
        <Input
          id="current-password"
          type="password"
          value={currentPassword}
          onChange={(e) => setCurrentPassword(e.target.value)}
          autoComplete="current-password"
          required
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="new-password">New password</Label>
        <Input
          id="new-password"
          type="password"
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
          autoComplete="new-password"
          required
        />
        <p className="text-xs text-muted-foreground">{PASSWORD_LENGTH_HINT}</p>
      </div>

      <div className="space-y-2">
        <Label htmlFor="confirm-new-password">Confirm new password</Label>
        <Input
          id="confirm-new-password"
          type="password"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          autoComplete="new-password"
          required
        />
      </div>

      <Button type="submit" disabled={submitting}>
        {submitLabel}
      </Button>
    </form>
  )
}
