// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { Database, Plus, FolderOpen, RefreshCw, Pencil, Trash2 } from 'lucide-react'

export default function SourcesPage() {
  // Mock data for demo
  const sources = [
    { id: 'nas-docs', name: 'NAS Documents', path: '/data/nas/documents', docCount: 1234, lastIndexed: '2 hours ago' },
    { id: 'local-notes', name: 'Local Notes', path: '/data/notes', docCount: 567, lastIndexed: '1 day ago' },
  ]

  const hasSources = sources.length > 0

  return (
    <div className="animate-fade-in">
      {/* Page header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-foreground tracking-tight">
            Sources
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Manage directories and locations to index
          </p>
        </div>
        <button
          className="flex items-center gap-2 px-4 py-2.5 bg-cyan text-cyan-foreground font-medium rounded-lg hover:bg-cyan/90 transition-colors shadow-glow-sm hover:shadow-glow"
          onClick={() => console.log('Add source clicked')}
        >
          <Plus className="h-4 w-4" />
          Add Source
        </button>
      </div>

      {hasSources ? (
        // Sources table
        <div className="bg-card border border-border rounded-lg overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-border bg-secondary/30">
                <th className="text-left px-4 py-3 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  Source
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-muted-foreground uppercase tracking-wider hidden md:table-cell">
                  Path
                </th>
                <th className="text-right px-4 py-3 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  Documents
                </th>
                <th className="text-right px-4 py-3 text-xs font-medium text-muted-foreground uppercase tracking-wider hidden sm:table-cell">
                  Last Indexed
                </th>
                <th className="text-right px-4 py-3 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {sources.map((source, index) => (
                <tr
                  key={source.id}
                  className="hover:bg-secondary/30 transition-colors animate-fade-in-up animate-initial"
                  style={{ animationDelay: `${index * 50}ms`, animationFillMode: 'forwards' }}
                >
                  <td className="px-4 py-4">
                    <div className="flex items-center gap-3">
                      <div className="p-2 rounded-lg bg-cyan/10">
                        <FolderOpen className="h-4 w-4 text-cyan" />
                      </div>
                      <div>
                        <p className="font-medium text-foreground">{source.name}</p>
                        <p className="text-xs text-muted-foreground font-mono md:hidden">{source.path}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-4 hidden md:table-cell">
                    <code className="text-sm text-muted-foreground font-mono">{source.path}</code>
                  </td>
                  <td className="px-4 py-4 text-right">
                    <span className="font-mono text-foreground">{source.docCount.toLocaleString()}</span>
                  </td>
                  <td className="px-4 py-4 text-right hidden sm:table-cell">
                    <span className="text-sm text-muted-foreground">{source.lastIndexed}</span>
                  </td>
                  <td className="px-4 py-4 text-right">
                    <div className="flex items-center justify-end gap-1">
                      <button
                        className="p-2 text-muted-foreground hover:text-cyan hover:bg-cyan/10 rounded-lg transition-colors"
                        title="Reindex"
                      >
                        <RefreshCw className="h-4 w-4" />
                      </button>
                      <button
                        className="p-2 text-muted-foreground hover:text-foreground hover:bg-secondary rounded-lg transition-colors"
                        title="Edit"
                      >
                        <Pencil className="h-4 w-4" />
                      </button>
                      <button
                        className="p-2 text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded-lg transition-colors"
                        title="Delete"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        // Empty state
        <div className="bg-card border border-border rounded-lg">
          <div className="p-12 text-center">
            <div className="inline-flex p-4 rounded-full bg-secondary mb-4">
              <Database className="h-8 w-8 text-muted-foreground" />
            </div>
            <h3 className="text-lg font-medium text-foreground mb-2">
              No sources configured
            </h3>
            <p className="text-muted-foreground mb-6 max-w-sm mx-auto">
              Add a source to start indexing your files. Sources are directories that OneSearch will scan and index.
            </p>
            <button
              className="inline-flex items-center gap-2 px-4 py-2.5 bg-cyan text-cyan-foreground font-medium rounded-lg hover:bg-cyan/90 transition-colors shadow-glow-sm hover:shadow-glow"
              onClick={() => console.log('Add source clicked')}
            >
              <Plus className="h-4 w-4" />
              Add Your First Source
            </button>
          </div>
        </div>
      )}

      {/* Help text */}
      <div className="mt-6 p-4 rounded-lg bg-secondary/30 border border-border">
        <p className="text-sm text-muted-foreground">
          <span className="font-medium text-foreground">Tip:</span> Mount your NAS shares in Docker, then add the container path as a source.
          Use <code className="px-1.5 py-0.5 bg-secondary rounded font-mono text-xs">:ro</code> for read-only mounts.
        </p>
      </div>
    </div>
  )
}
