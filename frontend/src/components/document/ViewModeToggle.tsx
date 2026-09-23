// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { cn } from '@/lib/utils'

export type ViewMode = 'rendered' | 'raw'

const modes: { value: ViewMode; label: string }[] = [
  { value: 'rendered', label: 'Rendered' },
  { value: 'raw', label: 'Raw' },
]

export function ViewModeToggle({ value, onChange }: { value: ViewMode; onChange: (mode: ViewMode) => void }) {
  return (
    <div role="group" aria-label="Content view" className="flex items-center gap-0.5 rounded-md bg-secondary p-0.5">
      {modes.map((mode) => (
        <button
          key={mode.value}
          type="button"
          aria-pressed={value === mode.value}
          onClick={() => onChange(mode.value)}
          className={cn(
            'px-2 py-0.5 text-xs rounded transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 ring-offset-secondary',
            value === mode.value ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground',
          )}
        >
          {mode.label}
        </button>
      ))}
    </div>
  )
}
