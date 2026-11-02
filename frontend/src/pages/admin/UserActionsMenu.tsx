// Copyright (C) 2026 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { useEffect, useRef, useState } from 'react'
import { MoreHorizontal } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { AdminUser } from '@/types/api'

interface UserActionsMenuProps {
  user: AdminUser
  onChangeRole: () => void
  onToggleActive: () => void
  onResetPassword: () => void
  onDelete: () => void
}

const itemClass = 'flex w-full items-center rounded-sm px-2 py-1.5 text-left text-sm hover:bg-accent hover:text-accent-foreground'

export function UserActionsMenu({ user, onChangeRole, onToggleActive, onResetPassword, onDelete }: UserActionsMenuProps) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const closeOnOutsideClick = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false)
    }
    const closeOnEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', closeOnOutsideClick)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('mousedown', closeOnOutsideClick)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [open])

  const choose = (action: () => void) => {
    setOpen(false)
    action()
  }

  return (
    <div ref={ref} className="relative inline-block text-left">
      <Button
        variant="ghost"
        size="icon"
        aria-label={`Actions for ${user.username}`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <MoreHorizontal />
      </Button>
      {open && (
        <div role="menu" className="absolute right-0 z-10 mt-1 w-44 rounded-md border border-border bg-popover p-1 text-popover-foreground shadow-md">
          <button type="button" role="menuitem" className={itemClass} onClick={() => choose(onChangeRole)}>
            {user.role === 'admin' ? 'Make member' : 'Make admin'}
          </button>
          <button type="button" role="menuitem" className={itemClass} onClick={() => choose(onToggleActive)}>
            {user.is_active ? 'Disable' : 'Enable'}
          </button>
          <button type="button" role="menuitem" className={itemClass} onClick={() => choose(onResetPassword)}>
            Reset password
          </button>
          <button type="button" role="menuitem" className={`${itemClass} text-destructive`} onClick={() => choose(onDelete)}>
            Delete
          </button>
        </div>
      )}
    </div>
  )
}
