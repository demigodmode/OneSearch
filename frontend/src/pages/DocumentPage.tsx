// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { useDocument } from '@/hooks/useApi'
import {
  ArrowLeft,
  FileText,
  FileCode,
  File,
  Copy,
  Loader2,
  AlertCircle,
  Clock,
  HardDrive,
  Calendar,
  FolderOpen,
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { useState, useEffect, useCallback } from 'react'

// Map file extensions to syntax highlighter languages
const extensionToLanguage: Record<string, string> = {
  // JavaScript/TypeScript
  js: 'javascript',
  jsx: 'jsx',
  ts: 'typescript',
  tsx: 'tsx',
  // Python
  py: 'python',
  pyw: 'python',
  // Web
  html: 'html',
  htm: 'html',
  css: 'css',
  scss: 'scss',
  sass: 'sass',
  less: 'less',
  // Data
  json: 'json',
  yaml: 'yaml',
  yml: 'yaml',
  xml: 'xml',
  // Shell
  sh: 'bash',
  bash: 'bash',
  zsh: 'bash',
  // Config
  conf: 'ini',
  cfg: 'ini',
  ini: 'ini',
  // Other languages
  java: 'java',
  c: 'c',
  cpp: 'cpp',
  cc: 'cpp',
  h: 'c',
  hpp: 'cpp',
  go: 'go',
  rs: 'rust',
  rb: 'ruby',
  php: 'php',
  sql: 'sql',
  r: 'r',
  // Markup
  md: 'markdown',
  markdown: 'markdown',
}

// Code file extensions that should use syntax highlighting
const codeExtensions = new Set(Object.keys(extensionToLanguage))

// Format file size for display
function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// Format timestamp for display
function formatDate(timestamp: number): string {
  return new Date(timestamp * 1000).toLocaleString()
}

// Get file type icon
function FileTypeIcon({ type, className }: { type: string; className?: string }) {
  switch (type) {
    case 'markdown':
      return <FileCode className={className} />
    case 'pdf':
    case 'docx':
    case 'xlsx':
    case 'pptx':
      return <FileText className={className} />
    default:
      return <File className={className} />
  }
}

// Markdown content renderer
function MarkdownRenderer({ content }: { content: string }) {
  return (
    <div className="prose prose-invert prose-cyan max-w-none">
      <ReactMarkdown
        components={{
          // Custom code block rendering with syntax highlighting
          code({ className, children, ...props }) {
            const match = /language-(\w+)/.exec(className || '')
            const isInline = !match

            return isInline ? (
              <code className="bg-secondary px-1.5 py-0.5 rounded text-cyan font-mono text-sm" {...props}>
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
                className="text-cyan hover:underline"
                {...props}
              >
                {children}
              </a>
            )
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}

// Code content renderer with syntax highlighting
function CodeRenderer({ content, language }: { content: string; language: string }) {
  return (
    <SyntaxHighlighter
      style={oneDark}
      language={language}
      showLineNumbers
      wrapLines
      lineNumberStyle={{ color: '#6b7280', paddingRight: '1em', minWidth: '3em' }}
      className="rounded-lg !bg-card border border-border text-sm"
    >
      {content}
    </SyntaxHighlighter>
  )
}

// Plain text content renderer
function PlainTextRenderer({ content }: { content: string }) {
  return (
    <pre className="bg-card border border-border rounded-lg p-4 overflow-x-auto text-sm font-mono text-foreground whitespace-pre-wrap break-words">
      {content}
    </pre>
  )
}

export default function DocumentPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [copied, setCopied] = useState(false)

  // Get search context for back navigation
  const fromQuery = searchParams.get('q')
  const fromSource = searchParams.get('source')
  const fromType = searchParams.get('type')

  const { data: document, isLoading, error } = useDocument(id || '')

  const handleBack = useCallback(() => {
    if (fromQuery) {
      const params = new URLSearchParams()
      params.set('q', fromQuery)
      if (fromSource) params.set('source', fromSource)
      if (fromType) params.set('type', fromType)
      navigate(`/?${params.toString()}`)
    } else {
      navigate('/')
    }
  }, [navigate, fromQuery, fromSource, fromType])

  const handleCopyPath = async () => {
    if (document?.path) {
      await navigator.clipboard.writeText(document.path)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  // Keyboard shortcut: Escape to go back
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        handleBack()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [handleBack])

  // Determine content renderer based on file type
  const renderContent = () => {
    if (!document) return null

    const { content, type, extension } = document

    // Empty content
    if (!content || content.trim() === '') {
      return (
        <div className="text-center py-12 text-muted-foreground">
          <FileText className="h-12 w-12 mx-auto mb-4 opacity-50" />
          <p>No text content available for this document.</p>
          {Boolean(document.metadata?.extraction_failed) && (
            <p className="text-sm mt-2">
              Extraction failed: {String(document.metadata?.extraction_error || 'Unknown error')}
            </p>
          )}
        </div>
      )
    }

    // Markdown files
    if (type === 'markdown' || extension === 'md' || extension === 'markdown') {
      return <MarkdownRenderer content={content} />
    }

    // Code files with syntax highlighting
    if (codeExtensions.has(extension)) {
      const language = extensionToLanguage[extension] || 'text'
      return <CodeRenderer content={content} language={language} />
    }

    // Plain text for everything else (pdf, docx, xlsx, pptx, txt, etc.)
    return <PlainTextRenderer content={content} />
  }

  if (isLoading) {
    return (
      <div className="min-h-[calc(100vh-4rem)] gradient-mesh flex items-center justify-center">
        <div className="text-center">
          <Loader2 className="h-12 w-12 text-cyan animate-spin mx-auto mb-4" />
          <p className="text-muted-foreground">Loading document...</p>
        </div>
      </div>
    )
  }

  if (error || !document) {
    return (
      <div className="min-h-[calc(100vh-4rem)] gradient-mesh">
        <div className="max-w-4xl mx-auto px-4 py-8">
          <button
            onClick={handleBack}
            className="flex items-center gap-2 text-muted-foreground hover:text-foreground transition-colors mb-8"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to search
          </button>

          <div className="text-center py-12">
            <AlertCircle className="h-12 w-12 text-destructive mx-auto mb-4" />
            <h2 className="text-xl font-semibold text-foreground mb-2">Document not found</h2>
            <p className="text-muted-foreground">
              {error instanceof Error ? error.message : 'The requested document could not be found.'}
            </p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-[calc(100vh-4rem)] gradient-mesh">
      <div className="max-w-5xl mx-auto px-4 py-8">
        {/* Back navigation */}
        <button
          onClick={handleBack}
          className="flex items-center gap-2 text-muted-foreground hover:text-foreground transition-colors mb-6"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to search
          <span className="text-xs text-muted-foreground ml-2">(Esc)</span>
        </button>

        {/* Document header */}
        <div className="bg-card border border-border rounded-lg p-6 mb-6">
          <div className="flex items-start gap-4">
            <div className="p-3 bg-secondary rounded-lg shrink-0">
              <FileTypeIcon type={document.type} className="h-8 w-8 text-cyan" />
            </div>

            <div className="flex-1 min-w-0">
              <h1 className="text-2xl font-bold text-foreground mb-1 truncate">
                {document.title || document.basename}
              </h1>
              <p className="text-sm text-muted-foreground font-mono truncate mb-4">
                {document.path}
              </p>

              {/* Metadata grid */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                <div className="flex items-center gap-2 text-muted-foreground">
                  <FolderOpen className="h-4 w-4" />
                  <span className="text-cyan">{document.source_name}</span>
                </div>
                <div className="flex items-center gap-2 text-muted-foreground">
                  <HardDrive className="h-4 w-4" />
                  <span>{formatSize(document.size_bytes)}</span>
                </div>
                <div className="flex items-center gap-2 text-muted-foreground">
                  <Calendar className="h-4 w-4" />
                  <span>Modified: {formatDate(document.modified_at)}</span>
                </div>
                <div className="flex items-center gap-2 text-muted-foreground">
                  <Clock className="h-4 w-4" />
                  <span>Indexed: {formatDate(document.indexed_at)}</span>
                </div>
              </div>
            </div>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-2 mt-4 pt-4 border-t border-border">
            <button
              onClick={handleCopyPath}
              className="flex items-center gap-2 px-3 py-2 text-sm text-muted-foreground hover:text-foreground hover:bg-secondary rounded-lg transition-colors"
            >
              <Copy className="h-4 w-4" />
              {copied ? 'Copied!' : 'Copy path'}
            </button>

            <div className="flex items-center gap-2 px-3 py-2 text-sm text-muted-foreground">
              <span className="uppercase font-mono bg-secondary px-2 py-0.5 rounded text-xs">
                {document.type}
              </span>
              {document.extension && document.extension !== document.type && (
                <span className="font-mono">.{document.extension}</span>
              )}
            </div>
          </div>
        </div>

        {/* Document content */}
        <div className="bg-card border border-border rounded-lg overflow-hidden">
          <div className="p-1 bg-secondary/50 border-b border-border">
            <span className="text-xs text-muted-foreground px-3">Content</span>
          </div>
          <div className="p-4 md:p-6">
            {renderContent()}
          </div>
        </div>

        {/* Metadata details (if any) */}
        {document.metadata && Object.keys(document.metadata).length > 0 && (
          <div className="mt-6 bg-card border border-border rounded-lg p-4">
            <h3 className="text-sm font-medium text-muted-foreground mb-3">Metadata</h3>
            <dl className="grid grid-cols-1 md:grid-cols-2 gap-2 text-sm">
              {Object.entries(document.metadata).map(([key, value]) => (
                <div key={key} className="flex gap-2">
                  <dt className="text-muted-foreground font-mono">{key}:</dt>
                  <dd className="text-foreground truncate">
                    {value != null && typeof value === 'object'
                      ? JSON.stringify(value)
                      : String(value ?? '')}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        )}
      </div>
    </div>
  )
}
