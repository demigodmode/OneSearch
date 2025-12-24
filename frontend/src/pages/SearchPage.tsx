// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { useState } from 'react'
import { Search } from 'lucide-react'

export default function SearchPage() {
  const [query, setQuery] = useState('')

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    // TODO: Implement search with TanStack Query
    console.log('Searching for:', query)
  }

  return (
    <div className="max-w-4xl mx-auto px-4 py-16">
      {/* Hero section */}
      <div className="text-center mb-12">
        <h1 className="text-4xl font-bold text-gray-900 dark:text-white mb-4">
          Search Your Files
        </h1>
        <p className="text-lg text-gray-600 dark:text-gray-400">
          Find documents across all your indexed sources
        </p>
      </div>

      {/* Search box */}
      <form onSubmit={handleSearch} className="mb-8">
        <div className="relative">
          <Search className="absolute left-4 top-1/2 -translate-y-1/2 h-5 w-5 text-gray-400" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search documents... (Ctrl+K)"
            className="w-full pl-12 pr-4 py-4 text-lg border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-500 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
          />
          <kbd className="absolute right-4 top-1/2 -translate-y-1/2 hidden sm:inline-flex items-center gap-1 px-2 py-1 text-xs text-gray-500 bg-gray-100 dark:bg-gray-700 rounded">
            <span className="text-xs">Ctrl</span>
            <span>K</span>
          </kbd>
        </div>
      </form>

      {/* Placeholder for filters and results */}
      <div className="text-center text-gray-500 dark:text-gray-400 py-12">
        <p>Enter a search query to find documents</p>
        <p className="text-sm mt-2">
          Filters and results will appear here
        </p>
      </div>
    </div>
  )
}
