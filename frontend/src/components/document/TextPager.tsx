// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { ChevronLeft, ChevronRight } from 'lucide-react'

export function TextPager({
  label,
  pageIndex,
  pageCount,
  onPageChange,
}: {
  label: string
  pageIndex: number
  pageCount: number
  onPageChange: (pageIndex: number) => void
}) {
  return (
    <nav aria-label={label} className="flex flex-wrap items-center justify-between gap-3">
      <button
        type="button"
        onClick={() => onPageChange(Math.max(0, pageIndex - 1))}
        disabled={pageIndex === 0}
        className="flex items-center gap-1 rounded-md px-2 py-1 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-foreground focus-visible:ring-offset-2 disabled:opacity-40 disabled:hover:text-muted-foreground"
      >
        <ChevronLeft className="h-4 w-4" />
        Previous
      </button>
      <span aria-live="polite" className="text-muted-foreground">
        Page <span className="text-foreground">{pageIndex + 1}</span> of {pageCount}
      </span>
      <button
        type="button"
        onClick={() => onPageChange(Math.min(pageCount - 1, pageIndex + 1))}
        disabled={pageIndex >= pageCount - 1}
        className="flex items-center gap-1 rounded-md px-2 py-1 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-foreground focus-visible:ring-offset-2 disabled:opacity-40 disabled:hover:text-muted-foreground"
      >
        Next
        <ChevronRight className="h-4 w-4" />
      </button>
    </nav>
  )
}
