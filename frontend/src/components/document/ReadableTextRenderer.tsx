// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { useMemo, useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'

const TARGET_PAGE_CHARS = 6000

function splitIntoPages(content: string): string[] {
  const paragraphs = content
    .replace(/\r\n/g, '\n')
    .split(/\n{2,}/)
    .map((part) => part.trim())
    .filter(Boolean)

  if (paragraphs.length === 0) return [content]

  const pages: string[] = []
  let current = ''

  for (const paragraph of paragraphs) {
    if (current && current.length + paragraph.length + 2 > TARGET_PAGE_CHARS) {
      pages.push(current)
      current = paragraph
      continue
    }
    current = current ? `${current}\n\n${paragraph}` : paragraph
  }

  if (current) pages.push(current)
  return pages.length > 0 ? pages : [content]
}

export function ReadableTextRenderer({ content }: { content: string }) {
  const pages = useMemo(() => splitIntoPages(content), [content])
  const [pageIndex, setPageIndex] = useState(0)
  const page = pages[Math.min(pageIndex, pages.length - 1)] || ''

  return (
    <div className="space-y-4">
      {pages.length > 1 && (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-border bg-secondary/30 px-3 py-2 text-sm">
          <button
            type="button"
            onClick={() => setPageIndex((value) => Math.max(0, value - 1))}
            disabled={pageIndex === 0}
            className="flex items-center gap-1 rounded-md px-2 py-1 text-muted-foreground hover:text-foreground disabled:opacity-40 disabled:hover:text-muted-foreground"
          >
            <ChevronLeft className="h-4 w-4" />
            Previous
          </button>
          <span className="text-muted-foreground">
            Page <span className="text-foreground">{pageIndex + 1}</span> of {pages.length}
          </span>
          <button
            type="button"
            onClick={() => setPageIndex((value) => Math.min(pages.length - 1, value + 1))}
            disabled={pageIndex >= pages.length - 1}
            className="flex items-center gap-1 rounded-md px-2 py-1 text-muted-foreground hover:text-foreground disabled:opacity-40 disabled:hover:text-muted-foreground"
          >
            Next
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      )}

      <div className="prose prose-invert max-w-none rounded-lg border border-border bg-card p-5 leading-7">
        {page.split(/\n{2,}/).map((paragraph, index) => (
          <p key={index} className="whitespace-pre-wrap">
            {paragraph}
          </p>
        ))}
      </div>
    </div>
  )
}
