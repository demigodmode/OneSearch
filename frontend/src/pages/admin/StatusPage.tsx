// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { Activity, CheckCircle, AlertCircle } from 'lucide-react'

export default function StatusPage() {
  return (
    <div>
      {/* Page header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
          Status
        </h1>
        <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
          View indexing status and system health
        </p>
      </div>

      {/* Health overview */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
        <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
          <div className="flex items-center gap-3">
            <CheckCircle className="h-8 w-8 text-green-500" />
            <div>
              <p className="text-sm text-gray-600 dark:text-gray-400">API Status</p>
              <p className="text-lg font-semibold text-gray-900 dark:text-white">Healthy</p>
            </div>
          </div>
        </div>

        <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
          <div className="flex items-center gap-3">
            <CheckCircle className="h-8 w-8 text-green-500" />
            <div>
              <p className="text-sm text-gray-600 dark:text-gray-400">Meilisearch</p>
              <p className="text-lg font-semibold text-gray-900 dark:text-white">Connected</p>
            </div>
          </div>
        </div>

        <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
          <div className="flex items-center gap-3">
            <Activity className="h-8 w-8 text-blue-500" />
            <div>
              <p className="text-sm text-gray-600 dark:text-gray-400">Documents</p>
              <p className="text-lg font-semibold text-gray-900 dark:text-white">0 indexed</p>
            </div>
          </div>
        </div>
      </div>

      {/* Placeholder for per-source status */}
      <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
        <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700">
          <h2 className="text-lg font-medium text-gray-900 dark:text-white">
            Source Status
          </h2>
        </div>
        <div className="p-8 text-center">
          <AlertCircle className="h-12 w-12 text-gray-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">
            No sources configured
          </h3>
          <p className="text-gray-600 dark:text-gray-400">
            Add sources to see their indexing status here
          </p>
        </div>
      </div>
    </div>
  )
}
