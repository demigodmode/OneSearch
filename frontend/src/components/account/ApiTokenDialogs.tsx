// Copyright (C) 2026 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { useEffect, useRef, useState } from 'react'
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
import { useCreateApiToken, useRevokeApiToken } from '@/hooks/useApi'
import type { ApiToken } from '@/types/api'

const EXPIRY_OPTIONS = [
  { value: 'never', label: 'Never', days: null },
  { value: '30', label: '30 days', days: 30 },
  { value: '90', label: '90 days', days: 90 },
  { value: '365', label: '1 year', days: 365 },
] as const

type ExpiryValue = (typeof EXPIRY_OPTIONS)[number]['value']

const COPIED_MESSAGE_MS = 2000

interface CreateApiTokenDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated: (token: string) => void
}

export function CreateApiTokenDialog({ open, onOpenChange, onCreated }: CreateApiTokenDialogProps) {
  const createToken = useCreateApiToken()
  const [name, setName] = useState('')
  const [expiry, setExpiry] = useState<ExpiryValue>(EXPIRY_OPTIONS[0].value)
  const [error, setError] = useState('')

  const reset = () => {
    setName('')
    setExpiry(EXPIRY_OPTIONS[0].value)
    setError('')
  }

  const handleOpenChange = (next: boolean) => {
    if (!next) reset()
    onOpenChange(next)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    const trimmed = name.trim()
    if (!trimmed) {
      setError('Give the token a name')
      return
    }

    try {
      const days = EXPIRY_OPTIONS.find((option) => option.value === expiry)?.days ?? null
      const created = await createToken.mutateAsync({ name: trimmed, expires_in_days: days })
      handleOpenChange(false)
      onCreated(created.token)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create token')
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create API token</DialogTitle>
          <DialogDescription>
            The token can search and open your documents, nothing else.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <p role="alert" className="text-sm text-destructive">{error}</p>
          )}

          <div className="space-y-2">
            <Label htmlFor="api-token-name">Name</Label>
            <Input
              id="api-token-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Backup script"
              autoComplete="off"
              required
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="api-token-expiry">Expires</Label>
            <select
              id="api-token-expiry"
              value={expiry}
              onChange={(e) => setExpiry(e.target.value as ExpiryValue)}
              className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            >
              {EXPIRY_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </div>

          <DialogFooter>
            <Button type="submit" disabled={createToken.isPending}>
              Create token
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

interface ApiTokenShownDialogProps {
  token: string | null
  onClose: () => void
}

export function ApiTokenShownDialog({ token, onClose }: ApiTokenShownDialogProps) {
  const fieldRef = useRef<HTMLInputElement>(null)
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'manual'>('idle')

  useEffect(() => {
    if (copyState !== 'copied') return
    const timer = setTimeout(() => setCopyState('idle'), COPIED_MESSAGE_MS)
    return () => clearTimeout(timer)
  }, [copyState])

  const selectForManualCopy = () => {
    fieldRef.current?.select()
    setCopyState('manual')
  }

  const copy = async () => {
    // Plain HTTP has no clipboard API, so the user copies the selected text themselves.
    if (!navigator.clipboard) {
      selectForManualCopy()
      return
    }
    try {
      await navigator.clipboard.writeText(token ?? '')
      setCopyState('copied')
    } catch {
      selectForManualCopy()
    }
  }

  const close = () => {
    setCopyState('idle')
    onClose()
  }

  const copyShortcut = /Mac|iPhone|iPad/.test(navigator.userAgent) ? 'Cmd' : 'Ctrl'

  return (
    <Dialog open={token !== null} onOpenChange={(next) => { if (!next) close() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Copy your token</DialogTitle>
          <DialogDescription>
            You won't be able to see this token again.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          <Label htmlFor="api-token-value">Token</Label>
          <Input
            id="api-token-value"
            ref={fieldRef}
            value={token ?? ''}
            readOnly
            className="font-mono text-xs"
          />
          {copyState === 'manual' && (
            <p role="status" className="text-sm text-muted-foreground">Press {copyShortcut}+C to copy</p>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={copy}>
            {copyState === 'copied' ? 'Copied' : 'Copy'}
          </Button>
          <Button onClick={close}>Done</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

interface RevokeApiTokenDialogProps {
  token: ApiToken | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function RevokeApiTokenDialog({ token, open, onOpenChange }: RevokeApiTokenDialogProps) {
  const revokeToken = useRevokeApiToken()
  const [error, setError] = useState('')

  const handleOpenChange = (next: boolean) => {
    if (!next) setError('')
    onOpenChange(next)
  }

  const handleConfirm = async () => {
    if (!token) return
    setError('')
    try {
      await revokeToken.mutateAsync(token.id)
      handleOpenChange(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not revoke token')
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Revoke {token?.name}?</DialogTitle>
          <DialogDescription>Anything using this token will stop working straight away.</DialogDescription>
        </DialogHeader>

        {error && (
          <p role="alert" className="text-sm text-destructive">{error}</p>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => handleOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={handleConfirm} disabled={revokeToken.isPending}>
            Revoke token
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
