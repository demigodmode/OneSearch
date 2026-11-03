// Copyright (C) 2026 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { MoreHorizontal } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import type { AdminUser } from '@/types/api'

interface UserActionsMenuProps {
  user: AdminUser
  onChangeRole: () => void
  onToggleActive: () => void
  onResetPassword: () => void
  onDelete: () => void
}

export function UserActionsMenu({ user, onChangeRole, onToggleActive, onResetPassword, onDelete }: UserActionsMenuProps) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={`Actions for ${user.username}`}>
          <MoreHorizontal />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-44">
        <DropdownMenuItem onSelect={onChangeRole}>
          {user.role === 'admin' ? 'Make member' : 'Make admin'}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={onToggleActive}>
          {user.is_active ? 'Disable' : 'Enable'}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={onResetPassword}>
          Reset password
        </DropdownMenuItem>
        <DropdownMenuItem className="text-destructive focus:text-destructive" onSelect={onDelete}>
          Delete
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
