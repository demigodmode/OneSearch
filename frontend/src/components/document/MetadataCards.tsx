// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import type { ReactNode } from 'react'

export function MetadataCards({
  title,
  icon,
  items,
}: {
  title: string
  icon: ReactNode
  items: Array<{ label: string; value: string | null }>
}) {
  const visibleItems = items.filter((item) => item.value)
  if (visibleItems.length === 0) return null

  return (
    <div className="bg-card border border-border rounded-lg p-4">
      <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground mb-3">
        {icon}
        <span>{title}</span>
      </div>
      <dl className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
        {visibleItems.map((item) => (
          <div key={item.label}>
            <dt className="text-muted-foreground text-xs uppercase tracking-wide">{item.label}</dt>
            <dd className="text-foreground mt-0.5 break-words">{item.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}
