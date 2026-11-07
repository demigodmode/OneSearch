// Copyright (C) 2026 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { PasswordChangeForm } from '@/components/PasswordChangeForm'
import { ApiTokensSection } from '@/components/account/ApiTokensSection'

export default function AccountPage() {
  return (
    <div className="animate-fade-in">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-foreground tracking-tight">Account</h1>
        <p className="text-sm text-muted-foreground mt-1">Manage your sign-in</p>
      </div>

      <div className="space-y-8">
        <section className="bg-card border border-border rounded-lg p-6 max-w-lg">
          <h2 className="text-sm font-semibold text-foreground uppercase tracking-wider mb-4">Change password</h2>
          <PasswordChangeForm submitLabel="Change password" />
        </section>

        <ApiTokensSection />
      </div>
    </div>
  )
}
