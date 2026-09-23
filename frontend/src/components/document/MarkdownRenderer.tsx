// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
// languages are registered on PrismLight in DocumentPage.tsx; fences render unhighlighted if that hasn't loaded
import { PrismLight as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'

// Markdown content renderer
export function MarkdownRenderer({ content }: { content: string }) {
  return (
    <div className="prose prose-invert max-w-none">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // Custom code block rendering with syntax highlighting
          code({ className, children, ...props }) {
            const match = /language-(\w+)/.exec(className || '')
            const isInline = !match

            return isInline ? (
              <code className="bg-secondary px-1.5 py-0.5 rounded text-brand font-mono text-sm" {...props}>
                {children}
              </code>
            ) : (
              <SyntaxHighlighter
                style={oneDark}
                language={match[1]}
                PreTag="div"
                className="rounded-lg !bg-card border border-border"
              >
                {String(children).replace(/\n$/, '')}
              </SyntaxHighlighter>
            )
          },
          // Style links
          a({ children, href, ...props }) {
            return (
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                className="text-brand hover:underline"
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
