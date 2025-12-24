// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { CheckCircle, AlertCircle, Database, Clock, FileText, AlertTriangle } from 'lucide-react'
import { cn } from '@/lib/utils'

export default function StatusPage() {
  // Mock data for demo
  const health = {
    api: { status: 'healthy', label: 'API Server' },
    meilisearch: { status: 'healthy', label: 'Meilisearch' },
    database: { status: 'healthy', label: 'Database' },
  }

  const stats = {
    totalDocs: 1801,
    totalSources: 2,
    lastIndexed: '2 hours ago',
    failedFiles: 3,
  }

  const sources = [
    {
      id: 'nas-docs',
      name: 'NAS Documents',
      status: 'healthy',
      docCount: 1234,
      lastIndexed: '2 hours ago',
      failedCount: 2,
    },
    {
      id: 'local-notes',
      name: 'Local Notes',
      status: 'healthy',
      docCount: 567,
      lastIndexed: '1 day ago',
      failedCount: 1,
    },
  ]

  return (
    <div className="animate-fade-in">
      {/* Page header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-foreground tracking-tight">
          Status
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          System health and indexing metrics
        </p>
      </div>

      {/* Health overview */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
        {Object.entries(health).map(([key, item], index) => (
          <div
            key={key}
            className="bg-card border border-border rounded-lg p-4 animate-fade-in-up animate-initial"
            style={{ animationDelay: `${index * 50}ms`, animationFillMode: 'forwards' }}
          >
            <div className="flex items-center gap-3">
              <div className={cn(
                'p-2 rounded-lg',
                item.status === 'healthy' ? 'bg-green-500/10' : 'bg-destructive/10'
              )}>
                <CheckCircle className={cn(
                  'h-5 w-5',
                  item.status === 'healthy' ? 'text-green-500' : 'text-destructive'
                )} />
              </div>
              <div>
                <p className="text-sm text-muted-foreground">{item.label}</p>
                <div className="flex items-center gap-2">
                  <div className={cn(
                    'status-dot',
                    item.status === 'healthy' ? 'status-dot-success' : 'status-dot-error'
                  )} />
                  <p className="text-sm font-medium text-foreground capitalize">
                    {item.status}
                  </p>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Stats cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <div
          className="bg-card border border-border rounded-lg p-4 animate-fade-in-up animate-initial"
          style={{ animationDelay: '150ms', animationFillMode: 'forwards' }}
        >
          <div className="flex items-center gap-2 text-muted-foreground mb-2">
            <FileText className="h-4 w-4" />
            <span className="text-xs uppercase tracking-wider">Documents</span>
          </div>
          <p className="text-2xl font-bold font-mono text-foreground">
            {stats.totalDocs.toLocaleString()}
          </p>
        </div>

        <div
          className="bg-card border border-border rounded-lg p-4 animate-fade-in-up animate-initial"
          style={{ animationDelay: '200ms', animationFillMode: 'forwards' }}
        >
          <div className="flex items-center gap-2 text-muted-foreground mb-2">
            <Database className="h-4 w-4" />
            <span className="text-xs uppercase tracking-wider">Sources</span>
          </div>
          <p className="text-2xl font-bold font-mono text-foreground">
            {stats.totalSources}
          </p>
        </div>

        <div
          className="bg-card border border-border rounded-lg p-4 animate-fade-in-up animate-initial"
          style={{ animationDelay: '250ms', animationFillMode: 'forwards' }}
        >
          <div className="flex items-center gap-2 text-muted-foreground mb-2">
            <Clock className="h-4 w-4" />
            <span className="text-xs uppercase tracking-wider">Last Indexed</span>
          </div>
          <p className="text-lg font-medium text-foreground">
            {stats.lastIndexed}
          </p>
        </div>

        <div
          className="bg-card border border-border rounded-lg p-4 animate-fade-in-up animate-initial"
          style={{ animationDelay: '300ms', animationFillMode: 'forwards' }}
        >
          <div className="flex items-center gap-2 text-muted-foreground mb-2">
            <AlertTriangle className="h-4 w-4" />
            <span className="text-xs uppercase tracking-wider">Failed Files</span>
          </div>
          <p className={cn(
            'text-2xl font-bold font-mono',
            stats.failedFiles > 0 ? 'text-amber-500' : 'text-foreground'
          )}>
            {stats.failedFiles}
          </p>
        </div>
      </div>

      {/* Per-source status */}
      <div
        className="bg-card border border-border rounded-lg overflow-hidden animate-fade-in-up animate-initial"
        style={{ animationDelay: '350ms', animationFillMode: 'forwards' }}
      >
        <div className="px-4 py-3 border-b border-border bg-secondary/30">
          <h2 className="text-sm font-medium text-foreground">
            Source Status
          </h2>
        </div>

        {sources.length > 0 ? (
          <div className="divide-y divide-border">
            {sources.map((source) => (
              <div key={source.id} className="p-4 hover:bg-secondary/20 transition-colors">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className={cn(
                      'status-dot',
                      source.status === 'healthy' ? 'status-dot-success' : 'status-dot-error'
                    )} />
                    <div>
                      <p className="font-medium text-foreground">{source.name}</p>
                      <p className="text-xs text-muted-foreground">
                        Last indexed {source.lastIndexed}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-6 text-sm">
                    <div className="text-right">
                      <p className="font-mono text-foreground">{source.docCount.toLocaleString()}</p>
                      <p className="text-xs text-muted-foreground">documents</p>
                    </div>
                    {source.failedCount > 0 && (
                      <div className="text-right">
                        <p className="font-mono text-amber-500">{source.failedCount}</p>
                        <p className="text-xs text-muted-foreground">failed</p>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="p-8 text-center">
            <AlertCircle className="h-8 w-8 text-muted-foreground mx-auto mb-3" />
            <p className="text-muted-foreground">
              No sources configured
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
