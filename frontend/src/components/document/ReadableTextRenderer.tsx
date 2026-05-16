// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { useMemo, useState, type ReactNode } from 'react'
import { ChevronLeft, ChevronRight, Search } from 'lucide-react'

const DEFAULT_PAGE_CHARS = 6000

function splitIntoPages(content: string, targetPageChars: number): string[] {
  const blocks = content
    .replace(/\r\n/g, '\n')
    .split(/\n{2,}/)
    .flatMap((part) => splitOversizedBlock(part.trim(), targetPageChars))
    .filter(Boolean)

  if (blocks.length === 0) return [content]

  const pages: string[] = []
  let current = ''

  for (const block of blocks) {
    if (current && current.length + block.length + 2 > targetPageChars) {
      pages.push(current)
      current = block
      continue
    }
    current = current ? `${current}\n\n${block}` : block
  }

  if (current) pages.push(current)
  return pages.length > 0 ? pages : [content]
}

function splitOversizedBlock(block: string, targetPageChars: number): string[] {
  if (block.length <= targetPageChars) return [block]

  const pages: string[] = []
  let current = ''

  for (const line of block.split('\n')) {
    if (line.length > targetPageChars) {
      if (current) {
        pages.push(current)
        current = ''
      }
      pages.push(...splitLongLine(line, targetPageChars))
      continue
    }

    const separator = current ? '\n' : ''
    if (current && current.length + separator.length + line.length > targetPageChars) {
      pages.push(current)
      current = line
    } else {
      current = `${current}${separator}${line}`
    }
  }

  if (current) pages.push(current)
  return pages
}

function splitLongLine(line: string, targetPageChars: number): string[] {
  const pages: string[] = []
  let remaining = line

  while (remaining.length > targetPageChars) {
    const breakpoint = Math.max(
      remaining.lastIndexOf(' ', targetPageChars),
      remaining.lastIndexOf('\t', targetPageChars)
    )
    const splitAt = breakpoint > targetPageChars * 0.6 ? breakpoint : targetPageChars
    pages.push(remaining.slice(0, splitAt).trimEnd())
    remaining = remaining.slice(splitAt).trimStart()
  }

  if (remaining) pages.push(remaining)
  return pages
}

function searchTermsForQuery(query?: string | null): string[] {
  const trimmed = query?.trim()
  if (!trimmed) return []

  return [trimmed]
}

function fallbackTermsForQuery(query?: string | null): string[] {
  const trimmed = query?.trim()
  if (!trimmed) return []

  return Array.from(new Set(trimmed.split(/\s+/).map((term) => term.trim()).filter((term) => term.length > 0)))
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function findMatches(pages: string[], query?: string | null): Array<{ pageIndex: number; start: number; end: number }> {
  const exactTerms = searchTermsForQuery(query)
  const exactMatches = collectMatches(pages, exactTerms)
  if (exactMatches.length > 0) return exactMatches

  return collectMatches(pages, fallbackTermsForQuery(query))
}

function collectMatches(pages: string[], terms: string[]): Array<{ pageIndex: number; start: number; end: number }> {
  if (terms.length === 0) return []
  const pattern = new RegExp(terms.map(escapeRegExp).join('|'), 'gi')
  const matches: Array<{ pageIndex: number; start: number; end: number }> = []

  pages.forEach((page, pageIndex) => {
    for (const match of page.matchAll(pattern)) {
      if (match.index === undefined || match[0].length === 0) continue
      matches.push({ pageIndex, start: match.index, end: match.index + match[0].length })
    }
  })

  return matches
}

function highlightedParagraph(paragraph: string, pageOffset: number, matches: Array<{ start: number; end: number }>) {
  const relevant = matches.filter((match) => match.end > pageOffset && match.start < pageOffset + paragraph.length)
  if (relevant.length === 0) return paragraph

  const parts: ReactNode[] = []
  let cursor = 0
  relevant.forEach((match, index) => {
    const start = Math.max(0, match.start - pageOffset)
    const end = Math.min(paragraph.length, match.end - pageOffset)
    if (start > cursor) parts.push(paragraph.slice(cursor, start))
    parts.push(
      <mark key={`${start}-${end}-${index}`} className="rounded bg-brand/30 px-0.5 text-foreground">
        {paragraph.slice(start, end)}
      </mark>
    )
    cursor = end
  })
  if (cursor < paragraph.length) parts.push(paragraph.slice(cursor))
  return parts
}

function pageParagraphs(page: string): Array<{ text: string; offset: number }> {
  const paragraphs: Array<{ text: string; offset: number }> = []
  let cursor = 0
  for (const text of page.split(/\n{2,}/)) {
    const offset = page.indexOf(text, cursor)
    paragraphs.push({ text, offset })
    cursor = offset + text.length
  }
  return paragraphs
}

export function ReadableTextRenderer({
  content,
  searchQuery,
  pageSizeChars = DEFAULT_PAGE_CHARS,
}: {
  content: string
  searchQuery?: string | null
  pageSizeChars?: number
}) {
  const pages = useMemo(() => splitIntoPages(content, pageSizeChars), [content, pageSizeChars])
  const matches = useMemo(() => findMatches(pages, searchQuery), [pages, searchQuery])
  const [activeMatchIndex, setActiveMatchIndex] = useState(0)
  const [pageIndex, setPageIndex] = useState(matches[0]?.pageIndex ?? 0)
  const page = pages[Math.min(pageIndex, pages.length - 1)] || ''
  const pageMatches = matches.filter((match) => match.pageIndex === pageIndex)

  const goToMatch = (nextIndex: number) => {
    const bounded = Math.max(0, Math.min(matches.length - 1, nextIndex))
    setActiveMatchIndex(bounded)
    setPageIndex(matches[bounded].pageIndex)
  }

  return (
    <div className="space-y-4">
      {(pages.length > 1 || matches.length > 0) && (
        <div className="flex flex-col gap-2 rounded-lg border border-border bg-secondary/30 px-3 py-2 text-sm sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center justify-between gap-3">
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

          {matches.length > 0 && (
            <div className="flex items-center justify-between gap-3 border-t border-border pt-2 sm:border-l sm:border-t-0 sm:pl-3 sm:pt-0">
              <span className="flex items-center gap-1 text-muted-foreground">
                <Search className="h-4 w-4 text-brand" />
                Match <span className="text-foreground">{activeMatchIndex + 1}</span> of {matches.length}
              </span>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => goToMatch(activeMatchIndex - 1)}
                  disabled={activeMatchIndex === 0}
                  className="rounded-md px-2 py-1 text-muted-foreground hover:text-foreground disabled:opacity-40 disabled:hover:text-muted-foreground"
                >
                  Prev match
                </button>
                <button
                  type="button"
                  onClick={() => goToMatch(activeMatchIndex + 1)}
                  disabled={activeMatchIndex >= matches.length - 1}
                  className="rounded-md px-2 py-1 text-muted-foreground hover:text-foreground disabled:opacity-40 disabled:hover:text-muted-foreground"
                >
                  Next match
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      <div className="prose prose-invert max-w-none rounded-lg border border-border bg-card p-5 leading-7">
        {pageParagraphs(page).map((paragraph, index) => (
          <p key={index} className="whitespace-pre-wrap">
            {highlightedParagraph(paragraph.text, paragraph.offset, pageMatches)}
          </p>
        ))}
      </div>
    </div>
  )
}
