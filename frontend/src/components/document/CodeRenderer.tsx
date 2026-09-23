// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

// languages are registered on PrismLight in DocumentPage.tsx; code renders unhighlighted if that hasn't loaded
import { PrismLight as SyntaxHighlighter } from 'react-syntax-highlighter'
import { useCodeTheme } from '@/hooks/useCodeTheme'

export function CodeRenderer({ content, language }: { content: string; language: string }) {
  const codeTheme = useCodeTheme()

  return (
    <SyntaxHighlighter
      style={codeTheme}
      language={language}
      showLineNumbers
      wrapLines
      lineNumberStyle={{ color: 'hsl(var(--muted-foreground))', paddingRight: '1em', minWidth: '3em' }}
      className="rounded-lg !bg-card border border-border text-sm"
    >
      {content}
    </SyntaxHighlighter>
  )
}
