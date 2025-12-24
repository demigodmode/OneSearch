// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import type React from 'react'
import { useState, useEffect, useRef } from 'react'
import { Search, Command, FileText, FileCode, File, Loader2, AlertCircle, ChevronLeft, ChevronRight } from 'lucide-react'
import { useSearch, useSources } from '@/hooks/useApi'
import type { SearchResult } from '@/types/api'
import { cn, sanitizeSnippet } from '@/lib/utils'

// Format file size for display
function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// Format timestamp for display
function formatDate(timestamp: number): string {
  const date = new Date(timestamp * 1000)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))

  if (diffDays === 0) return 'Today'
  if (diffDays === 1) return 'Yesterday'
  if (diffDays < 7) return `${diffDays} days ago`
  if (diffDays < 30) return `${Math.floor(diffDays / 7)} weeks ago`
  return date.toLocaleDateString()
}

// Get file type icon
function FileTypeIcon({ type }: { type: string }) {
  switch (type) {
    case 'markdown':
      return <FileCode className="h-4 w-4" />
    case 'pdf':
      return <FileText className="h-4 w-4" />
    default:
      return <File className="h-4 w-4" />
  }
}

// Result card component
function ResultCard({ result, index }: { result: SearchResult; index: number }) {
  return (
    <div
      className="bg-card border border-border rounded-lg p-4 card-hover accent-border-left animate-fade-in-up animate-initial"
      style={{ animationDelay: `${100 + index * 50}ms`, animationFillMode: 'forwards' }}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <h3 className="font-medium text-foreground truncate mb-1">
            {result.basename}
          </h3>
          <p className="text-sm text-muted-foreground font-mono truncate mb-2">
            {result.path}
          </p>
          {result.snippet && (
            <p
              className="text-sm text-muted-foreground line-clamp-2"
              dangerouslySetInnerHTML={{ __html: sanitizeSnippet(result.snippet) }}
            />
          )}
        </div>
        <div className="flex flex-col items-end gap-1 text-xs text-muted-foreground shrink-0">
          <div className="flex items-center gap-1.5 px-2 py-0.5 bg-secondary rounded">
            <FileTypeIcon type={result.type} />
            <span className="font-mono uppercase">{result.type}</span>
          </div>
          <span>{formatSize(result.size_bytes)}</span>
          <span>{formatDate(result.modified_at)}</span>
          <span className="text-cyan text-xs">{result.source_name}</span>
        </div>
      </div>
    </div>
  )
}

export default function SearchPage() {
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [sourceFilter, setSourceFilter] = useState<string>('')
  const [typeFilter, setTypeFilter] = useState<string>('')
  const [page, setPage] = useState(0)
  const [isFocused, setIsFocused] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const limit = 20

  // Debounce search query
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedQuery(query)
      setPage(0) // Reset to first page on new search
    }, 300)
    return () => clearTimeout(timer)
  }, [query])

  // Fetch sources for filter dropdown
  const { data: sources } = useSources()

  // Search with current filters
  const { data: searchData, isLoading, error } = useSearch({
    q: debouncedQuery,
    source_id: sourceFilter || undefined,
    type: typeFilter || undefined,
    limit,
    offset: page * limit,
  })

  // Keyboard shortcut: Ctrl+K or Cmd+K to focus search
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        inputRef.current?.focus()
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [])

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    setDebouncedQuery(query)
    setPage(0)
  }

  const totalPages = searchData ? Math.ceil(searchData.total / limit) : 0
  const hasResults = searchData && searchData.results.length > 0
  const showFilters = debouncedQuery.length > 0

  return (
    <div className="min-h-[calc(100vh-4rem)] gradient-mesh">
      <div className="max-w-4xl mx-auto px-4 pt-16 pb-16">
        {/* Hero section with staggered animation */}
        <div className="text-center mb-8">
          <h1
            className="text-5xl font-bold tracking-tight mb-4 animate-fade-in-up animate-initial"
            style={{ animationDelay: '0ms', animationFillMode: 'forwards' }}
          >
            <span className="gradient-text">OneSearch</span>
          </h1>
          <p
            className="text-lg text-muted-foreground animate-fade-in-up animate-initial"
            style={{ animationDelay: '100ms', animationFillMode: 'forwards' }}
          >
            Find anything across your homelab
          </p>
        </div>

        {/* Search box with glow effect */}
        <form
          onSubmit={handleSearch}
          className="mb-6 animate-fade-in-up animate-initial"
          style={{ animationDelay: '200ms', animationFillMode: 'forwards' }}
        >
          <div className={`search-input ${isFocused ? 'border-cyan/50' : ''}`}>
            <div className="flex items-center">
              <Search className="ml-4 h-5 w-5 text-muted-foreground" />
              <input
                ref={inputRef}
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onFocus={() => setIsFocused(true)}
                onBlur={() => setIsFocused(false)}
                placeholder="Search documents, files, notes..."
                className="flex-1 px-4 py-4 bg-transparent text-foreground placeholder-muted-foreground text-lg outline-none font-sans"
              />
              {isLoading && debouncedQuery && (
                <Loader2 className="h-5 w-5 text-cyan animate-spin mr-4" />
              )}
              <div className="hidden sm:flex items-center gap-1 mr-4">
                <kbd className="kbd">
                  <Command className="h-3 w-3" />
                </kbd>
                <kbd className="kbd">K</kbd>
              </div>
            </div>
          </div>
        </form>

        {/* Filters */}
        {showFilters && (
          <div
            className="flex flex-wrap gap-3 mb-6 animate-fade-in"
          >
            <select
              value={sourceFilter}
              onChange={(e) => { setSourceFilter(e.target.value); setPage(0) }}
              className="px-3 py-2 bg-card border border-border rounded-lg text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-cyan"
            >
              <option value="">All Sources</option>
              {sources?.map((source) => (
                <option key={source.id} value={source.id}>
                  {source.name}
                </option>
              ))}
            </select>

            <select
              value={typeFilter}
              onChange={(e) => { setTypeFilter(e.target.value); setPage(0) }}
              className="px-3 py-2 bg-card border border-border rounded-lg text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-cyan"
            >
              <option value="">All Types</option>
              <option value="text">Text</option>
              <option value="markdown">Markdown</option>
              <option value="pdf">PDF</option>
            </select>

            {(sourceFilter || typeFilter) && (
              <button
                onClick={() => { setSourceFilter(''); setTypeFilter(''); setPage(0) }}
                className="px-3 py-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
              >
                Clear filters
              </button>
            )}
          </div>
        )}

        {/* Results area */}
        <div
          className="animate-fade-in-up animate-initial"
          style={{ animationDelay: '300ms', animationFillMode: 'forwards' }}
        >
          {debouncedQuery === '' ? (
            // Empty state with file type hints
            <div className="text-center py-8">
              <p className="text-muted-foreground mb-6">
                Search across all your indexed sources
              </p>
              <div className="flex items-center justify-center gap-6 text-sm text-muted-foreground">
                <div className="flex items-center gap-2">
                  <FileText className="h-4 w-4 text-cyan" />
                  <span>Documents</span>
                </div>
                <div className="flex items-center gap-2">
                  <FileCode className="h-4 w-4 text-cyan" />
                  <span>Markdown</span>
                </div>
                <div className="flex items-center gap-2">
                  <File className="h-4 w-4 text-cyan" />
                  <span>PDFs</span>
                </div>
              </div>
            </div>
          ) : error ? (
            // Error state
            <div className="text-center py-12">
              <AlertCircle className="h-12 w-12 text-destructive mx-auto mb-4" />
              <p className="text-foreground font-medium mb-2">Search failed</p>
              <p className="text-muted-foreground text-sm">
                {error instanceof Error ? error.message : 'An unexpected error occurred'}
              </p>
            </div>
          ) : isLoading ? (
            // Loading state
            <div className="space-y-4">
              <div className="flex items-center justify-between text-sm text-muted-foreground mb-4">
                <span>Searching for "<span className="text-foreground">{debouncedQuery}</span>"...</span>
              </div>
              {[1, 2, 3].map((i) => (
                <div
                  key={i}
                  className="bg-card border border-border rounded-lg p-4 animate-pulse"
                >
                  <div className="h-5 bg-secondary rounded w-1/3 mb-2" />
                  <div className="h-4 bg-secondary rounded w-2/3 mb-2" />
                  <div className="h-4 bg-secondary rounded w-full" />
                </div>
              ))}
            </div>
          ) : hasResults ? (
            // Results
            <div className="space-y-4">
              <div className="flex items-center justify-between text-sm text-muted-foreground mb-4">
                <span>
                  {searchData.total.toLocaleString()} result{searchData.total !== 1 ? 's' : ''} for "
                  <span className="text-foreground">{debouncedQuery}</span>"
                  <span className="text-xs ml-2">({searchData.processing_time_ms}ms)</span>
                </span>
              </div>

              {searchData.results.map((result, index) => (
                <ResultCard key={result.id} result={result} index={index} />
              ))}

              {/* Pagination */}
              {totalPages > 1 && (
                <div className="flex items-center justify-center gap-4 pt-6">
                  <button
                    onClick={() => setPage(p => Math.max(0, p - 1))}
                    disabled={page === 0}
                    className={cn(
                      "flex items-center gap-1 px-3 py-2 rounded-lg text-sm transition-colors",
                      page === 0
                        ? "text-muted-foreground cursor-not-allowed"
                        : "text-foreground hover:bg-secondary"
                    )}
                  >
                    <ChevronLeft className="h-4 w-4" />
                    Previous
                  </button>

                  <span className="text-sm text-muted-foreground">
                    Page {page + 1} of {totalPages}
                  </span>

                  <button
                    onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
                    disabled={page >= totalPages - 1}
                    className={cn(
                      "flex items-center gap-1 px-3 py-2 rounded-lg text-sm transition-colors",
                      page >= totalPages - 1
                        ? "text-muted-foreground cursor-not-allowed"
                        : "text-foreground hover:bg-secondary"
                    )}
                  >
                    Next
                    <ChevronRight className="h-4 w-4" />
                  </button>
                </div>
              )}
            </div>
          ) : (
            // No results
            <div className="text-center py-12">
              <Search className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
              <p className="text-foreground font-medium mb-2">No results found</p>
              <p className="text-muted-foreground text-sm">
                Try adjusting your search or filters
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
