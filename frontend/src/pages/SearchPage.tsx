// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import type React from 'react'
import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Search, FileText, FileCode, File, Loader2, AlertCircle, ChevronLeft, ChevronRight, Eye } from 'lucide-react'
import { useSearch, useSources } from '@/hooks/useApi'
import { useSearchSettings, SNIPPET_LENGTH_MAP } from '@/contexts/SearchSettingsContext'
import type { SearchResult } from '@/types/api'
import { cn, sanitizeSnippet, formatSize, formatTimestamp } from '@/lib/utils'

const isMac = /Mac|iPod|iPhone|iPad/.test(navigator.platform)

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

function ResultCard({
  result,
  index,
  onClick,
  density,
  showPath,
  showSize,
  showDate,
  isSelected,
}: {
  result: SearchResult
  index: number
  onClick: () => void
  density: 'compact' | 'comfortable' | 'spacious'
  showPath: boolean
  showSize: boolean
  showDate: boolean
  isSelected: boolean
}) {
  const paddingClass = density === 'compact' ? 'p-2.5' : density === 'spacious' ? 'p-6' : 'p-4'

  return (
    <div
      onClick={onClick}
      className={cn(
        'bg-card border rounded-lg card-hover animate-fade-in-up animate-initial cursor-pointer group',
        paddingClass,
        isSelected ? 'border-brand/60 ring-1 ring-brand/30' : 'border-border',
      )}
      style={{ animationDelay: `${100 + index * 50}ms`, animationFillMode: 'forwards' }}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <h3 className="font-medium text-foreground truncate group-hover:text-brand transition-colors">
              {result.basename}
            </h3>
            <Eye className="h-4 w-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
          </div>
          {showPath && (
            <p className="text-sm text-muted-foreground font-mono truncate mb-2">
              {result.path}
            </p>
          )}
          {result.snippet && (
            <p
              className={cn('text-sm text-muted-foreground', density === 'compact' ? 'line-clamp-1' : 'line-clamp-2')}
              dangerouslySetInnerHTML={{ __html: sanitizeSnippet(result.snippet) }}
            />
          )}
        </div>
        <div className="flex flex-col items-end gap-1 text-xs text-muted-foreground shrink-0">
          <div className="flex items-center gap-1.5 px-2 py-0.5 bg-secondary rounded">
            <FileTypeIcon type={result.type} />
            <span className="font-mono uppercase">{result.type}</span>
          </div>
          {showSize && <span>{formatSize(result.size_bytes)}</span>}
          {showDate && <span>{formatTimestamp(result.modified_at)}</span>}
          <span className="text-brand text-xs">{result.source_name}</span>
        </div>
      </div>
    </div>
  )
}

export default function SearchPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [query, setQuery] = useState(searchParams.get('q') || '')
  const [debouncedQuery, setDebouncedQuery] = useState(searchParams.get('q') || '')
  const [sourceFilter, setSourceFilter] = useState<string>(searchParams.get('source') || '')
  const [typeFilter, setTypeFilter] = useState<string>(searchParams.get('type') || '')
  const [page, setPage] = useState(0)
  const [selectedIndex, setSelectedIndex] = useState(-1)
  const inputRef = useRef<HTMLInputElement>(null)

  const { settings } = useSearchSettings()
  const limit = settings.resultsPerPage
  const snippetLengthValue = SNIPPET_LENGTH_MAP[settings.snippetLength]

  const handleViewDocument = useCallback((documentId: string) => {
    const params = new URLSearchParams()
    if (debouncedQuery) params.set('q', debouncedQuery)
    if (sourceFilter) params.set('source', sourceFilter)
    if (typeFilter) params.set('type', typeFilter)
    const queryString = params.toString()
    navigate(`/document/${encodeURIComponent(documentId)}${queryString ? `?${queryString}` : ''}`)
  }, [debouncedQuery, sourceFilter, typeFilter, navigate])

  // Debounce search query
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedQuery(query)
      setPage(0)
      setSelectedIndex(-1)
    }, 300)
    return () => clearTimeout(timer)
  }, [query])

  const { data: sources } = useSources()

  const searchQuery = useMemo(() => ({
    q: debouncedQuery,
    source_id: sourceFilter || undefined,
    type: typeFilter || undefined,
    limit,
    offset: page * limit,
    sort: settings.sortOrder !== 'relevance' ? settings.sortOrder : undefined,
    snippet_length: snippetLengthValue,
  }), [debouncedQuery, sourceFilter, typeFilter, limit, page, settings.sortOrder, snippetLengthValue])

  const { data: searchData, isLoading, error } = useSearch(searchQuery)

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ctrl/Cmd+K to focus search
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        inputRef.current?.focus()
        return
      }

      // / to focus search (when not already in an input)
      if (e.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes((e.target as HTMLElement).tagName)) {
        e.preventDefault()
        inputRef.current?.focus()
        return
      }

      // Escape to clear/blur
      if (e.key === 'Escape' && document.activeElement === inputRef.current) {
        if (query) {
          setQuery('')
        } else {
          inputRef.current?.blur()
        }
        return
      }

      // Arrow key navigation through results
      if (!searchData?.results.length) return
      const resultCount = searchData.results.length

      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setSelectedIndex(prev => Math.min(prev + 1, resultCount - 1))
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        setSelectedIndex(prev => Math.max(prev - 1, -1))
      } else if (e.key === 'Enter' && selectedIndex >= 0) {
        e.preventDefault()
        handleViewDocument(searchData.results[selectedIndex].id)
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [query, searchData, selectedIndex, handleViewDocument])

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    setDebouncedQuery(query)
    setPage(0)
    setSelectedIndex(-1)
  }

  const totalPages = searchData ? Math.ceil(searchData.total / limit) : 0
  const hasResults = searchData && searchData.results.length > 0
  const showFilters = debouncedQuery.length > 0

  return (
    <div className="min-h-[calc(100vh-4rem)] gradient-mesh">
      <div className="max-w-4xl mx-auto px-4 pt-10 pb-16">
        {/* Search box */}
        <form
          onSubmit={handleSearch}
          className="mb-6 animate-fade-in-up animate-initial"
          style={{ animationDelay: '0ms', animationFillMode: 'forwards' }}
        >
          <div className="search-input">
            <div className="flex items-center">
              <Search className="ml-4 h-5 w-5 text-muted-foreground" />
              <input
                ref={inputRef}
                type="text"
                aria-label="Search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search documents, files, notes..."
                className="flex-1 px-4 py-4 bg-transparent text-foreground placeholder-muted-foreground text-lg outline-none font-sans"
              />
              {isLoading && debouncedQuery && (
                <Loader2 className="h-5 w-5 text-brand animate-spin mr-4" />
              )}
              <div className="hidden sm:flex items-center gap-1 mr-4">
                <kbd className="kbd">{isMac ? '⌘' : 'Ctrl'}</kbd>
                <kbd className="kbd">K</kbd>
              </div>
            </div>
          </div>
        </form>

        {/* Filters */}
        {showFilters && (
          <div
            className="flex flex-wrap gap-3 mb-6 animate-fade-in animate-initial"
            style={{ animationFillMode: 'forwards' }}
          >
            <select
              value={sourceFilter}
              onChange={(e) => { setSourceFilter(e.target.value); setPage(0) }}
              className="px-3 py-2 bg-card border border-border rounded-lg text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ring-offset-background"
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
              className="px-3 py-2 bg-card border border-border rounded-lg text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ring-offset-background"
            >
              <option value="">All Types</option>
              <option value="text">Text</option>
              <option value="markdown">Markdown</option>
              <option value="code">Code</option>
              <option value="config">Config</option>
              <option value="pdf">PDF</option>
              <option value="docx">Word (.docx)</option>
              <option value="xlsx">Excel (.xlsx)</option>
              <option value="pptx">PowerPoint (.pptx)</option>
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
          style={{ animationDelay: '150ms', animationFillMode: 'forwards' }}
        >
          {debouncedQuery === '' ? (
            // Empty state with file type hints
            <div className="text-center py-8">
              <p className="text-muted-foreground mb-6">
                Search across all your indexed sources
              </p>
              <div className="flex items-center justify-center gap-6 text-sm text-muted-foreground">
                <div className="flex items-center gap-2">
                  <FileText className="h-4 w-4 text-brand" />
                  <span>Documents</span>
                </div>
                <div className="flex items-center gap-2">
                  <FileCode className="h-4 w-4 text-brand" />
                  <span>Markdown</span>
                </div>
                <div className="flex items-center gap-2">
                  <File className="h-4 w-4 text-brand" />
                  <span>PDFs</span>
                </div>
              </div>
            </div>
          ) : error ? (
            <div className="text-center py-12">
              <AlertCircle className="h-12 w-12 text-destructive mx-auto mb-4" />
              <p className="text-foreground font-medium mb-2">Search failed</p>
              <p className="text-muted-foreground text-sm">
                {error instanceof Error ? error.message : 'An unexpected error occurred'}
              </p>
            </div>
          ) : isLoading ? (
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
            <div key={`${debouncedQuery}-${page}`} className="space-y-4 animate-fade-in animate-initial" style={{ animationFillMode: 'forwards' }}>
              <div className="flex items-center justify-between text-sm text-muted-foreground mb-4">
                <span>
                  {searchData.total.toLocaleString()} result{searchData.total !== 1 ? 's' : ''} for "
                  <span className="text-foreground">{debouncedQuery}</span>"
                  <span className="text-xs ml-2">({searchData.processing_time_ms}ms)</span>
                </span>
              </div>

              {searchData.results.map((result, index) => (
                <ResultCard
                  key={result.id}
                  result={result}
                  index={index}
                  onClick={() => handleViewDocument(result.id)}
                  density={settings.density}
                  showPath={settings.showPath}
                  showSize={settings.showSize}
                  showDate={settings.showDate}
                  isSelected={index === selectedIndex}
                />
              ))}

              {/* Pagination */}
              {totalPages > 1 && (
                <div className="flex items-center justify-center gap-4 pt-6">
                  <button
                    onClick={() => setPage(p => Math.max(0, p - 1))}
                    disabled={page === 0}
                    className={cn(
                      "flex items-center gap-1 px-3 py-2 rounded-lg text-sm transition-all active:scale-95 disabled:active:scale-100",
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
                      "flex items-center gap-1 px-3 py-2 rounded-lg text-sm transition-all active:scale-95 disabled:active:scale-100",
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
