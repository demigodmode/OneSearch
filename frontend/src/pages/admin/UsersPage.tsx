// Copyright (C) 2026 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { useState } from 'react'
import { Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useAuth } from '@/contexts/useAuth'
import { useUpdateUser, useUsers } from '@/hooks/useApi'
import { formatDateTime } from '@/lib/utils'
import type { AdminUser, UpdateUserRequest } from '@/types/api'
import { CreateUserDialog } from '@/pages/admin/CreateUserDialog'
import { DeleteUserDialog } from '@/pages/admin/DeleteUserDialog'
import { ResetPasswordDialog } from '@/pages/admin/ResetPasswordDialog'
import { UserActionsMenu } from '@/pages/admin/UserActionsMenu'

// The one place that decides what a row's role and active toggles change to.
const roleToggle = (user: AdminUser): UpdateUserRequest => ({ role: user.role === 'admin' ? 'member' : 'admin' })
const activeToggle = (user: AdminUser): UpdateUserRequest => ({ is_active: !user.is_active })

export default function UsersPage() {
  const users = useUsers()
  const updateUser = useUpdateUser()
  const { user: me } = useAuth()
  const [createOpen, setCreateOpen] = useState(false)
  // The target stays set after a dialog closes so its title doesn't change mid-animation.
  const [resetTarget, setResetTarget] = useState<AdminUser | null>(null)
  const [resetOpen, setResetOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<AdminUser | null>(null)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [actionError, setActionError] = useState('')

  const changeUser = async (user: AdminUser, data: UpdateUserRequest) => {
    setActionError('')
    try {
      await updateUser.mutateAsync({ id: user.id, data })
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Could not update user')
    }
  }

  return (
    <div className="animate-fade-in">
      <div className="mb-8 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-foreground tracking-tight">Users</h1>
          <p className="text-sm text-muted-foreground mt-1">Accounts that can sign in to OneSearch</p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="h-4 w-4" />
          Create user
        </Button>
      </div>

      {users.isLoading && <p className="text-sm text-muted-foreground">Loading users...</p>}
      {users.error && <p role="alert" className="text-sm text-destructive">Unable to load users.</p>}
      {actionError && <p role="alert" className="mb-4 text-sm text-destructive">{actionError}</p>}

      {users.data && (
        <div className="bg-card border border-border rounded-lg">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Username</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Created by</TableHead>
                <TableHead>Created</TableHead>
                <TableHead>Last login</TableHead>
                <TableHead><span className="sr-only">Actions</span></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.data.map((user) => (
                <TableRow key={user.id}>
                  <TableCell className="font-medium">{user.username}</TableCell>
                  <TableCell>{user.role === 'admin' ? 'Admin' : 'Member'}</TableCell>
                  <TableCell>{user.is_active ? 'Active' : 'Disabled'}</TableCell>
                  <TableCell>{user.created_by ?? '—'}</TableCell>
                  <TableCell>{formatDateTime(user.created_at)}</TableCell>
                  <TableCell>{user.last_login_at ? formatDateTime(user.last_login_at) : 'Never'}</TableCell>
                  <TableCell>
                    {me && me.id !== user.id && (
                      <UserActionsMenu
                        user={user}
                        onChangeRole={() => changeUser(user, roleToggle(user))}
                        onToggleActive={() => changeUser(user, activeToggle(user))}
                        onResetPassword={() => {
                          setResetTarget(user)
                          setResetOpen(true)
                        }}
                        onDelete={() => {
                          setDeleteTarget(user)
                          setDeleteOpen(true)
                        }}
                      />
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <CreateUserDialog open={createOpen} onOpenChange={setCreateOpen} />
      <ResetPasswordDialog user={resetTarget} open={resetOpen} onOpenChange={setResetOpen} />
      <DeleteUserDialog user={deleteTarget} open={deleteOpen} onOpenChange={setDeleteOpen} />
    </div>
  )
}
