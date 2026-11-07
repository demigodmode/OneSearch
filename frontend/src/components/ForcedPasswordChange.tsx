// Copyright (C) 2026 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/contexts/useAuth'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { PasswordChangeForm } from '@/components/PasswordChangeForm'

export default function ForcedPasswordChange() {
  const { logout } = useAuth()
  const navigate = useNavigate()

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-1 text-center">
          <CardTitle className="text-2xl">Choose a new password</CardTitle>
          <CardDescription>
            You're signed in with a temporary password. Choose a new one to continue.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <PasswordChangeForm submitLabel="Save password" onChanged={() => navigate('/', { replace: true })} />
          <div className="text-center">
            <Button
              variant="ghost"
              size="sm"
              onClick={logout}
              className="text-muted-foreground hover:text-foreground"
            >
              Sign out
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
