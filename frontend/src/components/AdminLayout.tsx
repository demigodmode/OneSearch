// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { Outlet, Link, useLocation } from 'react-router-dom'
import { Search, Database, Activity, ArrowLeft, Terminal, LogOut, User } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useAuth } from '@/contexts/AuthContext'
import { Button } from '@/components/ui/button'

const adminNavItems = [
  { path: '/admin/sources', label: 'Sources', icon: Database },
  { path: '/admin/status', label: 'Status', icon: Activity },
]

export default function AdminLayout() {
  const location = useLocation()
  const { user, logout } = useAuth()

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-border/50 bg-background/80 backdrop-blur-md">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            {/* Logo & breadcrumb */}
            <div className="flex items-center gap-3">
              <Link to="/" className="flex items-center gap-2.5 group">
                <div className="p-1.5 rounded-lg bg-brand/10 group-hover:bg-brand/20 transition-colors">
                  <Search className="h-5 w-5 text-brand" />
                </div>
                <span className="text-lg font-semibold text-foreground tracking-tight">
                  OneSearch
                </span>
              </Link>
              <span className="text-border">/</span>
              <div className="flex items-center gap-1.5 text-muted-foreground">
                <Terminal className="h-4 w-4" />
                <span className="text-sm font-medium">Admin</span>
              </div>
            </div>

            {/* Right side actions */}
            <div className="flex items-center gap-2">
              <Link
                to="/"
                className="flex items-center gap-2 px-3 py-2 text-sm font-medium text-muted-foreground hover:text-foreground rounded-lg hover:bg-secondary transition-colors"
              >
                <ArrowLeft className="h-4 w-4" />
                <span className="hidden sm:inline">Back to Search</span>
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
            </div>
          </div>
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="flex flex-col md:flex-row gap-6 md:gap-8">
          {/* Sidebar — horizontal pills on mobile, vertical list on md+ */}
          <aside className="flex-shrink-0 md:w-56">
            <nav className="flex flex-row md:flex-col gap-1 overflow-x-auto md:overflow-x-visible pb-2 md:pb-0 border-b border-border md:border-0 mb-2 md:mb-0 scrollbar-none">
              {adminNavItems.map((item, index) => {
                const Icon = item.icon
                const isActive = location.pathname === item.path
                return (
                  <Link
                    key={item.path}
                    to={item.path}
                    className={cn(
                      'flex items-center gap-2.5 px-3 py-2.5 text-sm font-medium rounded-lg transition-all duration-200',
                      'shrink-0 md:shrink animate-fade-in-up animate-initial',
                      isActive
                        ? 'bg-brand/10 text-brand border border-brand/20'
                        : 'text-muted-foreground hover:text-foreground hover:bg-secondary'
                    )}
                    style={{ animationDelay: `${index * 50}ms`, animationFillMode: 'forwards' }}
                  >
                    <Icon className={cn('h-4 w-4 shrink-0', isActive && 'text-brand')} />
                    {item.label}
                    {isActive && (
                      <div className="hidden md:block ml-auto w-1.5 h-1.5 rounded-full bg-brand opacity-70" />
                    )}
                  </Link>
                )
              })}
            </nav>

          </aside>

          {/* Main content */}
          <main className="flex-1 min-w-0">
            <Outlet />
          </main>
        </div>
      </div>
    </div>
  )
}
