// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { useState, useEffect, useRef } from 'react'
import { Search, Command, FileText, FileCode, File } from 'lucide-react'

export default function SearchPage() {
  const [query, setQuery] = useState('')
  const [isFocused, setIsFocused] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

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
    // TODO: Implement search with TanStack Query
    console.log('Searching for:', query)
  }

  return (
    <div className="min-h-[calc(100vh-4rem)] gradient-mesh">
      <div className="max-w-3xl mx-auto px-4 pt-24 pb-16">
        {/* Hero section with staggered animation */}
        <div className="text-center mb-12">
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
          className="mb-12 animate-fade-in-up animate-initial"
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
              <div className="hidden sm:flex items-center gap-1 mr-4">
                <kbd className="kbd">
                  <Command className="h-3 w-3" />
                </kbd>
                <kbd className="kbd">K</kbd>
              </div>
            </div>
          </div>
        </form>

        {/* Quick stats or hints */}
        <div
          className="animate-fade-in-up animate-initial"
          style={{ animationDelay: '300ms', animationFillMode: 'forwards' }}
        >
          {query === '' ? (
            // Empty state with file type hints
            <div className="text-center">
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
          ) : (
            // Results placeholder
            <div className="space-y-4">
              <div className="flex items-center justify-between text-sm text-muted-foreground mb-4">
                <span>Results for "<span className="text-foreground">{query}</span>"</span>
                <span>Searching...</span>
              </div>

              {/* Example result cards */}
              {[1, 2, 3].map((i) => (
                <div
                  key={i}
                  className="bg-card border border-border rounded-lg p-4 card-hover accent-border-left animate-fade-in-up animate-initial"
                  style={{ animationDelay: `${300 + i * 75}ms`, animationFillMode: 'forwards' }}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <h3 className="font-medium text-foreground truncate mb-1">
                        example-document-{i}.pdf
                      </h3>
                      <p className="text-sm text-muted-foreground font-mono truncate mb-2">
                        /nas/documents/archive/
                      </p>
                      <p className="text-sm text-muted-foreground line-clamp-2">
                        Lorem ipsum dolor sit amet, consectetur adipiscing elit.
                        Matching text would be <mark className="bg-cyan/20 text-cyan px-0.5 rounded">highlighted</mark> here.
                      </p>
                    </div>
                    <div className="flex flex-col items-end gap-1 text-xs text-muted-foreground">
                      <span className="px-2 py-0.5 bg-secondary rounded text-xs font-mono">PDF</span>
                      <span>2.4 MB</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
