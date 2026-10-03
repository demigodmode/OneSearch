// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { AlertCircle, ChevronLeft, ChevronRight, FileWarning, Loader2, RotateCw } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useDocumentRawText } from '@/hooks/useApi'
import { formatSize } from '@/lib/utils'
import type { Document } from '@/types/api'
import { CodeRenderer } from './CodeRenderer'
import { buildRawTextPages } from './rawTextPages'
import { RawQueryCursor, type TextMatch } from './queryHighlight'

type RawDocument = Pick<Document, 'id' | 'modified_at' | 'size_bytes'>

export function RawTextView({
  document,
  language,
  maxBytes,
  searchQuery,
}: {
  document: RawDocument
  language: string
  maxBytes: number
  searchQuery?: string | null
}) {
  const tooLarge = document.size_bytes > maxBytes
  const { data, isLoading, error, refetch } = useDocumentRawText(document.id, document.modified_at, !tooLarge, maxBytes)
  const rawContent = data ?? ''
  const pages = useMemo(() => buildRawTextPages(rawContent), [rawContent])
  const cursor = useMemo(() => new RawQueryCursor(rawContent, searchQuery), [rawContent, searchQuery])
  const [pageState, setPageState] = useState(() => ({ documentId: document.id, modifiedAt: document.modified_at, content: rawContent, pageIndex: 0 }))
  const pageStateMatchesContent = pageState.documentId === document.id && pageState.modifiedAt === document.modified_at && pageState.content === rawContent
  if (!pageStateMatchesContent) {
    setPageState({ documentId: document.id, modifiedAt: document.modified_at, content: rawContent, pageIndex: 0 })
  }
  const pageIndex = pageStateMatchesContent ? Math.min(pageState.pageIndex, pages.length - 1) : 0
  const page = pages[Math.min(pageIndex, pages.length - 1)]
  const content = rawContent.slice(page.start, page.end)
  const plainText = pages.length > 1
  const highlights = useMemo(() => {
    let selected: TextMatch[] = []
    for (let index = 0; index <= pageIndex; index += 1) {
      const candidate = pages[index]
      if (index !== pageIndex && cursor.hasPage(index)) continue
      const ranges = cursor.rangesForPage(index, candidate.start, candidate.end)
      if (index === pageIndex) selected = ranges
    }
    return selected
  }, [cursor, pageIndex, pages])

  if (tooLarge) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        <FileWarning className="h-10 w-10 mx-auto mb-3 opacity-60" />
        <p>This file is too large to show here ({formatSize(document.size_bytes)}). Download it to see the original.</p>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 py-12 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin" />
        Loading original file…
      </div>
    )
  }

  if (error) {
    return (
      <div className="text-center py-12">
        <AlertCircle className="h-10 w-10 mx-auto mb-3 text-destructive" />
        <p className="text-foreground">{error.message}</p>
        <button
          onClick={() => refetch()}
          className="mt-4 inline-flex items-center gap-2 px-3 py-2 text-sm rounded-lg text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
        >
          <RotateCw className="h-4 w-4" />
          Retry
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {pages.length > 1 && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-secondary/30 px-3 py-2 text-sm">
          <button
            type="button"
            onClick={() => setPageState({ documentId: document.id, modifiedAt: document.modified_at, content: rawContent, pageIndex: Math.max(0, pageIndex - 1) })}
            disabled={pageIndex === 0}
            className="flex items-center gap-1 rounded-md px-2 py-1 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-foreground focus-visible:ring-offset-2 disabled:opacity-40 disabled:hover:text-muted-foreground"
          >
            <ChevronLeft className="h-4 w-4" />
            Previous
          </button>
          <span aria-live="polite" className="text-muted-foreground">
            Page <span className="text-foreground">{pageIndex + 1}</span> of {pages.length}
          </span>
          <button
            type="button"
            onClick={() => setPageState({ documentId: document.id, modifiedAt: document.modified_at, content: rawContent, pageIndex: Math.min(pages.length - 1, pageIndex + 1) })}
            disabled={pageIndex >= pages.length - 1}
            className="flex items-center gap-1 rounded-md px-2 py-1 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-foreground focus-visible:ring-offset-2 disabled:opacity-40 disabled:hover:text-muted-foreground"
          >
            Next
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      )}
      {plainText && <p className="text-sm text-muted-foreground">Showing plain text for this large file.</p>}
      {page.continuesFromPrevious && <p className="text-sm text-muted-foreground">Continued from line {page.startingLineNumber}</p>}
      <CodeRenderer content={content} language={plainText ? 'text' : language} startingLineNumber={page.startingLineNumber} highlightRanges={highlights} />
      {page.continuesOnNext && <p className="text-sm text-muted-foreground">Line {page.endingLineNumber} continues on the next page.</p>}
    </div>
  )
}
