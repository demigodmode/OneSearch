// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { Outlet, Link } from 'react-router-dom'
import { Search, Settings, Github, LogOut, User } from 'lucide-react'
import { useAuth } from '@/contexts/AuthContext'
import { Button } from '@/components/ui/button'

export default function MainLayout() {
  const { user, logout } = useAuth()

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-border/50 bg-background/80 backdrop-blur-md">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            {/* Logo */}
            <Link to="/" className="flex items-center gap-2.5 group">
              <div className="p-1.5 rounded-lg bg-cyan/10 group-hover:bg-cyan/20 transition-colors">
                <Search className="h-5 w-5 text-cyan" />
              </div>
              <span className="text-lg font-semibold text-foreground tracking-tight">
                OneSearch
              </span>
            </Link>

            {/* Navigation */}
            <nav className="flex items-center gap-2">
              <a
                href="https://github.com/demigodmode/OneSearch"
                target="_blank"
                rel="noopener noreferrer"
                className="p-2 text-muted-foreground hover:text-foreground rounded-lg hover:bg-secondary transition-colors"
                title="GitHub"
              >
                <Github className="h-5 w-5" />
              </a>
              <Link
                to="/admin/sources"
                className="flex items-center gap-2 px-3 py-2 text-sm font-medium text-muted-foreground hover:text-foreground rounded-lg hover:bg-secondary transition-colors"
              >
                <Settings className="h-4 w-4" />
                <span className="hidden sm:inline">Admin</span>
              </Link>
              {user && (
                <>
                  <span className="hidden md:flex items-center gap-1.5 px-2 text-sm text-muted-foreground">
                    <User className="h-4 w-4" />
                    {user.username}
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={logout}
                    className="text-muted-foreground hover:text-foreground"
                  >
                    <LogOut className="h-4 w-4" />
                    <span className="hidden sm:inline ml-2">Logout</span>
                  </Button>
                </>
              )}
            </nav>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main>
        <Outlet />
      </main>

      {/* Minimal footer */}
      <footer className="border-t border-border/50 py-6 mt-auto">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <p className="text-center text-sm text-muted-foreground">
            Self-hosted search for your homelab
          </p>
        </div>
      </footer>
    </div>
  )
}
