// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

// languages are registered on PrismLight in DocumentPage.tsx; code renders unhighlighted if that hasn't loaded
import { PrismLight as SyntaxHighlighter, type SyntaxHighlighterProps } from 'react-syntax-highlighter'
import { createElement } from 'react-syntax-highlighter'
import type { ReactNode } from 'react'
import { useCodeTheme } from '@/hooks/useCodeTheme'
import type { TextMatch } from './queryHighlight'

type Renderer = NonNullable<SyntaxHighlighterProps['renderer']>
type PrismNode = Parameters<Renderer>[0]['rows'][number]

function isLineNumber(node: PrismNode) {
  const classes = node.properties?.className
  return classes?.includes('react-syntax-highlighter-line-number') || classes?.includes('linenumber')
}

function sourceText(node: PrismNode): string {
  if (node.type === 'text') return String(node.value ?? '')
  if (isLineNumber(node)) return ''
  return node.children?.map(sourceText).join('') ?? ''
}

function mergeTouchingRanges(ranges: TextMatch[]) {
  return ranges.reduce<TextMatch[]>((merged, range) => {
    const previous = merged[merged.length - 1]
    if (previous && range.start <= previous.end) previous.end = Math.max(previous.end, range.end)
    else merged.push({ ...range })
    return merged
  }, [])
}

function highlightRenderer(content: string, ranges: TextMatch[]): Renderer {
  return ({ rows, stylesheet, useInlineStyles }) => {
    const rowText = rows.map(sourceText)
    const separator = rowText.join('') === content ? '' : rowText.join('\n') === content ? '\n' : undefined
    if (separator === undefined) {
      return rows.map((node, index) => createElement({ node, stylesheet, useInlineStyles, key: `code-segment-${index}` }))
    }
    let offset = 0
    let rangeIndex = 0
    const visit = (node: PrismNode): PrismNode => {
      if (node.type === 'text') {
        const value = String(node.value ?? '')
        const start = offset
        offset += value.length
        while (rangeIndex < ranges.length && ranges[rangeIndex].end <= start) rangeIndex += 1
        const first = rangeIndex
        let last = rangeIndex
        while (last < ranges.length && ranges[last].start < offset) last += 1
        if (first === last) return node
        const children: PrismNode[] = []
        let cursor = 0
        for (let index = first; index < last; index += 1) {
          const range = ranges[index]
          const from = Math.max(0, range.start - start)
          const to = Math.min(value.length, range.end - start)
          if (from > cursor) children.push({ type: 'text', value: value.slice(cursor, from) })
          children.push({ type: 'element', tagName: 'mark', properties: { className: ['rounded', 'bg-brand/30', 'px-0.5', 'text-foreground'] }, children: [{ type: 'text', value: value.slice(from, to) }] })
          cursor = to
        }
        if (cursor < value.length) children.push({ type: 'text', value: value.slice(cursor) })
        rangeIndex = first
        return { type: 'element', tagName: 'span', properties: { className: [] }, children }
      }
      if (isLineNumber(node)) return node
      return { ...node, children: node.children?.map(visit) }
    }
    return rows.map((node, index) => {
      const rendered = visit(node)
      if (index < rows.length - 1) offset += separator.length
      return createElement({ node: rendered, stylesheet, useInlineStyles, key: `code-segment-${index}` }) as ReactNode
    })
  }
}

export function CodeRenderer({
  content,
  language,
  startingLineNumber = 1,
  highlightRanges = [],
  showLineNumbers = true,
  wrapLines = true,
  className = 'rounded-lg !bg-card border border-border text-sm',
  preTag,
}: {
  content: string
  language: string
  startingLineNumber?: number
  highlightRanges?: TextMatch[]
  showLineNumbers?: boolean
  wrapLines?: boolean
  className?: string
  preTag?: 'div'
}) {
  const codeTheme = useCodeTheme()

  return (
    <SyntaxHighlighter
      style={codeTheme}
      language={language}
      showLineNumbers={showLineNumbers}
      startingLineNumber={startingLineNumber}
      wrapLines={wrapLines}
      lineNumberStyle={{ color: 'hsl(var(--muted-foreground))', paddingRight: '1em', minWidth: '3em' }}
      className={className}
      PreTag={preTag}
      renderer={highlightRanges.length ? highlightRenderer(content, mergeTouchingRanges(highlightRanges)) : undefined}
    >
      {content}
    </SyntaxHighlighter>
  )
}
