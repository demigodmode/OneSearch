// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { Outlet, Link, useLocation } from 'react-router-dom'
import type { LucideIcon } from 'lucide-react'
import { Database, Activity, ArrowLeft, LogOut, User, Settings, Cpu, Users, ScrollText, UserCog } from 'lucide-react'
import { cn, isAdmin } from '@/lib/utils'
import { useAuth } from '@/contexts/useAuth'
import { Button } from '@/components/ui/button'
import { OneSearchLogo } from '@/components/OneSearchLogo'
import { useAppSettings } from '@/hooks/useApi'

interface NavItem {
  path: string
  label: string
  icon: LucideIcon
}

const ACCOUNT_ITEM: NavItem = { path: '/account', label: 'Account', icon: UserCog }
const MEMBER_SETTINGS_ITEM: NavItem = { path: '/settings', label: 'Settings', icon: Settings }

const adminNavItems = (remoteAgentsEnabled: boolean): NavItem[] => [
  { path: '/admin/sources', label: 'Sources', icon: Database },
  { path: '/admin/status', label: 'Status', icon: Activity },
  { path: '/admin/users', label: 'Users', icon: Users },
  { path: '/admin/audit', label: 'Audit log', icon: ScrollText },
  ...(remoteAgentsEnabled ? [{ path: '/admin/agents', label: 'Agents', icon: Cpu }] : []),
  { path: '/admin/settings', label: 'Settings', icon: Settings },
]

function SidebarLink({ item, index, pathname }: { item: NavItem; index: number; pathname: string }) {
  const Icon = item.icon
  const isActive = pathname === item.path
  return (
    <Link
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
}

// Only mounted for admins, so members never trigger the app settings request
function AdminNavItems({ pathname, firstIndex }: { pathname: string; firstIndex: number }) {
  const { data: appSettings } = useAppSettings()
  const items = adminNavItems(Boolean(appSettings?.remote_agents_enabled))

  return (
    <>
      <span className="hidden md:block px-3 pt-4 pb-1 text-xs font-medium uppercase tracking-wider text-muted-foreground/70">
        Admin
      </span>
      {items.map((item, i) => (
        <SidebarLink key={item.path} item={item} index={firstIndex + i} pathname={pathname} />
      ))}
    </>
  )
}

export default function SettingsLayout() {
  const location = useLocation()
  const { user, logout } = useAuth()
  const admin = isAdmin(user)

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-border/50 bg-background/80 backdrop-blur-md">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            {/* Logo & breadcrumb */}
            <div className="flex items-center gap-3">
              <Link to="/" className="flex items-center gap-2.5 group">
                <div className="p-1 rounded-lg bg-brand/10 group-hover:bg-brand/20 transition-colors">
                  <OneSearchLogo className="h-6 w-6" aria-hidden="true" />
                </div>
                <span className="text-lg font-semibold text-foreground tracking-tight">
                  OneSearch
                </span>
              </Link>
              <span className="text-muted-foreground/40">/</span>
              <div className="flex items-center gap-1.5 text-muted-foreground">
                <Settings className="h-4 w-4" />
                <span className="text-sm font-medium">Settings</span>
              </div>
            </div>

            {/* Right side actions */}
            <div className="flex items-center gap-2">
              <Link
                to="/"
                className="flex items-center gap-2 px-3 py-2 text-sm font-medium text-muted-foreground hover:text-foreground rounded-lg hover:bg-secondary transition-colors"
              >
                <ArrowLeft className="h-4 w-4" />
                <span className="sr-only sm:not-sr-only">Back to Search</span>
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
                    <span className="sr-only sm:not-sr-only sm:ml-2">Logout</span>
                  </Button>
                </>
              )}
            </div>
          </div>
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="flex flex-col md:flex-row gap-6 md:gap-8">
          {/* Sidebar, horizontal pills on mobile, vertical list on md+ */}
          <aside className="flex-shrink-0 md:w-56">
            <nav className="flex flex-row md:flex-col gap-1 overflow-x-auto md:overflow-x-visible pb-2 md:pb-0 border-b border-border md:border-0 mb-2 md:mb-0 scrollbar-none">
              <SidebarLink item={ACCOUNT_ITEM} index={0} pathname={location.pathname} />
              {admin ? (
                <AdminNavItems pathname={location.pathname} firstIndex={1} />
              ) : (
                <SidebarLink item={MEMBER_SETTINGS_ITEM} index={1} pathname={location.pathname} />
              )}
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
