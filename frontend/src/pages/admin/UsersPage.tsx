// Copyright (C) 2026 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { useState } from 'react'
import { Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useUsers } from '@/hooks/useApi'
import { formatDateTime } from '@/lib/utils'
import { CreateUserDialog } from '@/pages/admin/CreateUserDialog'

export default function UsersPage() {
  const users = useUsers()
  const [createOpen, setCreateOpen] = useState(false)

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
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <CreateUserDialog open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  )
}
