// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

export type TextMatch = { start: number; end: number }

const markProperties = { className: ['rounded', 'bg-brand/30', 'px-0.5', 'text-foreground'] }

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

export function queryPattern(content: string, query?: string | null) {
  const trimmed = query?.trim()
  if (!trimmed) return undefined
  const exact = new RegExp(escapeRegExp(trimmed), 'i')
  const terms = exact.test(content) ? [trimmed] : Array.from(new Set(trimmed.split(/\s+/).filter(Boolean)))
  return terms.length ? new RegExp(terms.map(escapeRegExp).join('|'), 'gi') : undefined
}

type PendingMatch = TextMatch | undefined
type PageCursorState = { entryPending: PendingMatch; exitPending: PendingMatch; lastConsumedEnd: number }

export class RawQueryCursor {
  private readonly pattern: RegExp | undefined
  private readonly content: string
  private pending: PendingMatch
  private readonly pages = new Map<number, PageCursorState>()

  constructor(content: string, query?: string | null) {
    this.content = content
    this.pattern = queryPattern(content, query)
    this.pending = this.next()
  }

  hasPage(pageIndex: number) {
    return this.pages.has(pageIndex)
  }

  private next(): PendingMatch {
    if (!this.pattern) return undefined
    const match = this.pattern.exec(this.content)
    return match && match[0] ? { start: match.index, end: match.index + match[0].length } : undefined
  }

  rangesForPage(pageIndex: number, start: number, end: number): TextMatch[] {
    const cached = this.pages.get(pageIndex)
    if (cached) return this.replay(cached, start, end)

    const entryPending = this.pending
    let lastConsumedEnd = entryPending?.start ?? start
    const ranges: TextMatch[] = []
    while (this.pending) {
      const match = this.pending
      if (match.end > start && match.start < end) ranges.push({ start: Math.max(start, match.start) - start, end: Math.min(end, match.end) - start })
      if (match.end > end) break
      lastConsumedEnd = match.end
      this.pending = this.next()
    }
    this.pages.set(pageIndex, { entryPending, exitPending: this.pending, lastConsumedEnd })
    return ranges
  }

  private replay(state: PageCursorState, start: number, end: number): TextMatch[] {
    if (!state.entryPending) return []
    if (state.entryPending === state.exitPending) {
      const match = state.entryPending
      return match.end > start && match.start < end
        ? [{ start: Math.max(start, match.start) - start, end: Math.min(end, match.end) - start }]
        : []
    }
    const pattern = this.pattern ? new RegExp(this.pattern.source, this.pattern.flags) : undefined
    if (!pattern) return []
    const ranges: TextMatch[] = []
    let pending: PendingMatch = state.entryPending
    pattern.lastIndex = pending.end
    while (pending && pending.end <= state.lastConsumedEnd) {
      if (pending.end > start && pending.start < end) ranges.push({ start: Math.max(start, pending.start) - start, end: Math.min(end, pending.end) - start })
      if (pending.end === state.lastConsumedEnd) break
      const match = pattern.exec(this.content)
      pending = match && match[0] ? { start: match.index, end: match.index + match[0].length } : undefined
    }
    const exit = state.exitPending
    if (exit && exit.end > start && exit.start < end) {
      ranges.push({ start: Math.max(start, exit.start) - start, end: Math.min(end, exit.end) - start })
    }
    return ranges
  }
}

type HastNode = { type: string; tagName?: string; value?: string; children?: HastNode[]; properties?: Record<string, unknown>; data?: Record<string, unknown> }

function textLeaves(node: HastNode, leaves: HastNode[]) {
  if (node.type === 'text') leaves.push(node)
  else node.children?.forEach((child) => textLeaves(child, leaves))
}

function markLeaves(leaves: HastNode[], matches: TextMatch[]) {
  let offset = 0
  let rangeIndex = 0
  for (const leaf of leaves) {
    const value = leaf.value ?? ''
    const end = offset + value.length
    while (rangeIndex < matches.length && matches[rangeIndex].end <= offset) rangeIndex += 1
    const first = rangeIndex
    let last = rangeIndex
    while (last < matches.length && matches[last].start < end) last += 1
    if (first !== last) {
      const children: HastNode[] = []
      let cursor = 0
      for (let index = first; index < last; index += 1) {
        const match = matches[index]
        const start = Math.max(0, match.start - offset)
        const finish = Math.min(value.length, match.end - offset)
        if (start > cursor) children.push({ type: 'text', value: value.slice(cursor, start) })
        children.push({ type: 'element', tagName: 'mark', properties: markProperties, children: [{ type: 'text', value: value.slice(start, finish) }] })
        cursor = finish
      }
      if (cursor < value.length) children.push({ type: 'text', value: value.slice(cursor) })
      Object.assign(leaf, { type: 'element', tagName: 'span', properties: {}, children })
      delete leaf.value
    }
    offset = end
  }
}

const contentBlocks = new Set(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'td', 'th'])
const hardBlocks = new Set([...contentBlocks, 'ul', 'ol', 'blockquote', 'pre', 'table', 'thead', 'tbody', 'tfoot', 'tr', 'div', 'section', 'article', 'hr'])

export function rehypeQueryHighlights(query?: string | null) {
  return () => (tree: HastNode) => {
    const runs: HastNode[][] = []
    const fenced: HastNode[] = []
    const collect = (node: HastNode) => {
      if (node.type === 'raw') {
        node.type = 'text'
        runs.push([node])
        return
      }
      if (node.tagName === 'pre') {
        const code = node.children?.find((child) => child.tagName === 'code')
        if (code) fenced.push(code)
        return
      }
      if (contentBlocks.has(node.tagName ?? '')) {
        let leaves: HastNode[] = []
        const flush = () => {
          if (leaves.length) runs.push(leaves)
          leaves = []
        }
        const segment = (child: HastNode) => {
          if (child.type === 'raw') {
            child.type = 'text'
            leaves.push(child)
          } else if (child.type === 'text') leaves.push(child)
          else if (hardBlocks.has(child.tagName ?? '')) {
            flush()
            collect(child)
          } else child.children?.forEach(segment)
        }
        node.children?.forEach(segment)
        flush()
        return
      }
      node.children?.forEach(collect)
    }
    collect(tree)
    const exact = query?.trim()
    const visibleRuns = [...runs, ...fenced.map((node) => {
      const leaves: HastNode[] = []
      textLeaves(node, leaves)
      return leaves
    })]
    const hasExact = Boolean(exact && visibleRuns.some((run) => new RegExp(escapeRegExp(exact), 'i').test(run.map((leaf) => leaf.value ?? '').join(''))))
    const terms = !exact ? [] : hasExact ? [exact] : Array.from(new Set(exact.split(/\s+/).filter(Boolean)))
    if (!terms.length) return
    const pattern = new RegExp(terms.map(escapeRegExp).join('|'), 'gi')
    const matchesFor = (value: string) => {
      const matches: TextMatch[] = []
      for (let match = pattern.exec(value); match; match = pattern.exec(value)) {
        if (!match[0]) break
        matches.push({ start: match.index, end: match.index + match[0].length })
      }
      pattern.lastIndex = 0
      return matches
    }
    for (const leaves of runs) {
      const value = leaves.map((leaf) => leaf.value ?? '').join('')
      markLeaves(leaves, matchesFor(value))
    }
    for (const node of fenced) {
      const leaves: HastNode[] = []
      textLeaves(node, leaves)
      const value = leaves.map((leaf) => leaf.value ?? '').join('').replace(/\n$/, '')
      const ranges = matchesFor(value)
      node.data = { ...node.data, queryHighlightRanges: ranges }
    }
  }
}
