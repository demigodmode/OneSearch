// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { CodeRenderer } from './CodeRenderer'
import type { TextMatch } from './queryHighlight'
import { rehypeQueryHighlights } from './queryHighlight'

// Markdown content renderer
export function MarkdownRenderer({ content, searchQuery }: { content: string; searchQuery?: string | null }) {
  return (
    <div className="prose prose-invert max-w-none">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={searchQuery?.trim() ? [rehypeQueryHighlights(searchQuery)] : []}
        components={{
          // Custom code block rendering with syntax highlighting
          code({ className, children, node, ...props }) {
            const match = /language-(\w+)/.exec(className || '')
            const isInline = !match

            const source = String(children).replace(/\n$/, '')
            return isInline ? (
              <code className="bg-secondary px-1.5 py-0.5 rounded text-brand-strong font-mono text-sm" {...props}>
                {children}
              </code>
            ) : (
              <CodeRenderer
                content={source}
                language={match[1]}
                className="rounded-lg !bg-card border border-border"
                preTag="div"
                showLineNumbers={false}
                wrapLines={false}
                highlightRanges={(node?.data as { queryHighlightRanges?: TextMatch[] } | undefined)?.queryHighlightRanges ?? []}
              />
            )
          },
          // Style links
          a({ children, href, ...props }) {
            return (
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                className="text-brand-strong hover:underline"
                {...props}
              >
                {children}
              </a>
            )
          },
          // Wide tables scroll instead of stretching the card
          table({ node: _node, children, ...props }) {
            return (
              <div className="overflow-x-auto">
                <table {...props}>{children}</table>
              </div>
            )
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}
