// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { createContext, useContext, type InputHTMLAttributes } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { CodeRenderer } from './CodeRenderer'
import type { TextMatch } from './queryHighlight'
import { rehypeQueryHighlights } from './queryHighlight'

type HastLike = { type: string; value?: string; tagName?: string; children?: HastLike[] }

const TaskLabelContext = createContext<string | undefined>(undefined)

// Item text for a task checkbox name. Nested lists are left out.
function taskItemText(node: HastLike): string {
  if (node.type === 'text') return node.value ?? ''
  if (node.tagName === 'ul' || node.tagName === 'ol') return ''
  return (node.children ?? []).map(taskItemText).join('')
}

function TaskCheckbox({ checked, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  const label = useContext(TaskLabelContext)
  return (
    <input
      type="checkbox"
      checked={checked}
      readOnly
      aria-readonly="true"
      aria-label={label}
      className="accent-brand"
      {...props}
    />
  )
}

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
          // GFM task boxes come through disabled, which the browser greys out.
          // Keep them enabled so ticked ones are readable; controlled + readOnly
          // means React puts the state back if someone clicks.
          input({ node: _node, type, checked, disabled: _disabled, ...props }) {
            if (type !== 'checkbox') return <input type={type} {...props} />
            return <TaskCheckbox checked={!!checked} {...props} />
          },
          // Task items get their text as the checkbox name, since the text
          // is a sibling of the input and not a label.
          li({ node, className, children, ...props }) {
            if (!className?.includes('task-list-item')) {
              return <li className={className} {...props}>{children}</li>
            }
            const label = (node ? taskItemText(node) : '').replace(/\s+/g, ' ').trim()
            return (
              <TaskLabelContext.Provider value={label}>
                <li className={className} {...props}>{children}</li>
              </TaskLabelContext.Provider>
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
