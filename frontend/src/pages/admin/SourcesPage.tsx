// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { Database, Plus } from 'lucide-react'

export default function SourcesPage() {
  return (
    <div>
      {/* Page header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            Sources
          </h1>
          <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
            Manage directories and locations to index
          </p>
        </div>
        <button
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
          onClick={() => {
            // TODO: Open add source modal
            console.log('Add source clicked')
          }}
        >
          <Plus className="h-4 w-4" />
          Add Source
        </button>
      </div>

      {/* Placeholder for sources table */}
      <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
        <div className="p-8 text-center">
          <Database className="h-12 w-12 text-gray-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">
            No sources configured
          </h3>
          <p className="text-gray-600 dark:text-gray-400 mb-4">
            Add a source to start indexing your files
          </p>
          <button
            className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
            onClick={() => {
              // TODO: Open add source modal
              console.log('Add source clicked')
            }}
          >
            <Plus className="h-4 w-4" />
            Add Your First Source
          </button>
        </div>
      </div>
    </div>
  )
}
