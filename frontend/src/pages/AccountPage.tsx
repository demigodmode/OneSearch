// Copyright (C) 2026 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { PasswordChangeForm } from '@/components/PasswordChangeForm'

export default function AccountPage() {
  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 lg:px-8 py-8 animate-fade-in">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-foreground tracking-tight">Account</h1>
        <p className="text-sm text-muted-foreground mt-1">Manage your sign-in</p>
      </div>

      <section className="bg-card border border-border rounded-lg p-6">
        <h2 className="text-sm font-semibold text-foreground uppercase tracking-wider mb-4">Change password</h2>
        <PasswordChangeForm submitLabel="Change password" />
      </section>
    </div>
  )
}
