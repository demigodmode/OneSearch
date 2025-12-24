// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { useState } from 'react'
import { CheckCircle, AlertCircle, Database, Clock, FileText, AlertTriangle, ChevronDown, ChevronRight, Server, Loader2 } from 'lucide-react'
import { useHealth, useStatus } from '@/hooks/useApi'
import type { SourceStatus, FailedFile } from '@/types/api'
import { cn } from '@/lib/utils'

// Format date for display
function formatDate(isoString: string | null | undefined): string {
  if (!isoString) return 'Never'
  const date = new Date(isoString)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60))
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))

  if (diffHours < 1) return 'Just now'
  if (diffHours < 24) return `${diffHours} hour${diffHours !== 1 ? 's' : ''} ago`
  if (diffDays < 7) return `${diffDays} day${diffDays !== 1 ? 's' : ''} ago`
  return date.toLocaleDateString()
}

// Get source status
function getSourceHealthStatus(source: SourceStatus): 'healthy' | 'warning' | 'error' {
  if (source.failed > 0 && source.failed > source.successful * 0.1) return 'error'
  if (source.failed > 0) return 'warning'
  return 'healthy'
}

// Failed files list component
function FailedFilesList({ files }: { files: FailedFile[] }) {
  if (files.length === 0) return null

  return (
    <div className="mt-3 pt-3 border-t border-border">
      <p className="text-xs text-muted-foreground uppercase tracking-wider mb-2">
        Failed Files ({files.length})
      </p>
      <div className="space-y-2 max-h-48 overflow-y-auto scrollbar-thin">
        {files.map((file, index) => (
          <div
            key={index}
            className="text-xs bg-destructive/5 border border-destructive/20 rounded p-2"
          >
            <p className="font-mono text-foreground truncate">{file.path}</p>
            {file.error && (
              <p className="text-destructive mt-1">{file.error}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// Source status card component
function SourceStatusCard({ source, index }: { source: SourceStatus; index: number }) {
  const [isExpanded, setIsExpanded] = useState(false)
  const healthStatus = getSourceHealthStatus(source)
  const hasFailedFiles = (source.failed_files?.length ?? 0) > 0

  return (
    <div
      className={cn(
        "bg-card border rounded-lg overflow-hidden animate-fade-in-up animate-initial",
        healthStatus === 'error' ? 'border-destructive/50' :
        healthStatus === 'warning' ? 'border-amber-500/50' :
        'border-border'
      )}
      style={{ animationDelay: `${200 + index * 75}ms`, animationFillMode: 'forwards' }}
    >
      <div
        className={cn(
          "p-4 cursor-pointer hover:bg-secondary/20 transition-colors",
          hasFailedFiles && "cursor-pointer"
        )}
        onClick={() => hasFailedFiles && setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {hasFailedFiles && (
              isExpanded
                ? <ChevronDown className="h-4 w-4 text-muted-foreground" />
                : <ChevronRight className="h-4 w-4 text-muted-foreground" />
            )}
            <div className={cn(
              'status-dot',
              healthStatus === 'healthy' ? 'status-dot-success' :
              healthStatus === 'warning' ? 'status-dot-warning' :
              'status-dot-error'
            )} />
            <div>
              <p className="font-medium text-foreground">{source.source_name}</p>
              <p className="text-xs text-muted-foreground">
                Last indexed {formatDate(source.last_indexed_at)}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-6 text-sm">
            <div className="text-right">
              <p className="font-mono text-foreground">{source.total_files.toLocaleString()}</p>
              <p className="text-xs text-muted-foreground">total</p>
            </div>
            <div className="text-right">
              <p className="font-mono text-green-500">{source.successful.toLocaleString()}</p>
              <p className="text-xs text-muted-foreground">indexed</p>
            </div>
            {source.skipped > 0 && (
              <div className="text-right">
                <p className="font-mono text-muted-foreground">{source.skipped.toLocaleString()}</p>
                <p className="text-xs text-muted-foreground">skipped</p>
              </div>
            )}
            {source.failed > 0 && (
              <div className="text-right">
                <p className="font-mono text-amber-500">{source.failed}</p>
                <p className="text-xs text-muted-foreground">failed</p>
              </div>
            )}
          </div>
        </div>

        {isExpanded && hasFailedFiles && source.failed_files && (
          <FailedFilesList files={source.failed_files} />
        )}
      </div>
    </div>
  )
}

export default function StatusPage() {
  const { data: healthData, isLoading: isLoadingHealth, error: healthError } = useHealth()
  const { data: statusData, isLoading: isLoadingStatus, error: statusError } = useStatus()

  const isLoading = isLoadingHealth || isLoadingStatus
  const hasError = healthError || statusError

  // Calculate aggregate stats
  const sources = statusData?.sources || []
  const totalDocs = sources.reduce((sum, s) => sum + s.successful, 0)
  const totalFailed = sources.reduce((sum, s) => sum + s.failed, 0)
  const lastIndexed = sources.reduce((latest, s) => {
    if (!s.last_indexed_at) return latest
    if (!latest) return s.last_indexed_at
    return new Date(s.last_indexed_at) > new Date(latest) ? s.last_indexed_at : latest
  }, null as string | null)

  if (isLoading) {
    return (
      <div className="animate-fade-in">
        <div className="mb-8">
          <div className="h-8 w-24 bg-secondary rounded animate-pulse" />
          <div className="h-4 w-48 bg-secondary rounded animate-pulse mt-2" />
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
          {[1, 2, 3].map((i) => (
            <div key={i} className="bg-card border border-border rounded-lg p-4">
              <div className="h-12 bg-secondary rounded animate-pulse" />
            </div>
          ))}
        </div>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="bg-card border border-border rounded-lg p-4">
              <div className="h-16 bg-secondary rounded animate-pulse" />
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (hasError) {
    return (
      <div className="animate-fade-in">
        <div className="bg-card border border-border rounded-lg p-8 text-center">
          <AlertCircle className="h-12 w-12 text-destructive mx-auto mb-4" />
          <h3 className="text-lg font-medium text-foreground mb-2">Failed to load status</h3>
          <p className="text-muted-foreground">
            {healthError instanceof Error ? healthError.message :
             statusError instanceof Error ? statusError.message :
             'An error occurred'}
          </p>
        </div>
      </div>
    )
  }

  const overallHealth = healthData?.status || 'unknown'
  const meilisearchStatus = healthData?.meilisearch?.status || 'unknown'

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
        <div
          className="bg-card border border-border rounded-lg p-4 animate-fade-in-up animate-initial"
          style={{ animationDelay: '0ms', animationFillMode: 'forwards' }}
        >
          <div className="flex items-center gap-3">
            <div className={cn(
              'p-2 rounded-lg',
              overallHealth === 'healthy' ? 'bg-green-500/10' : 'bg-amber-500/10'
            )}>
              <Server className={cn(
                'h-5 w-5',
                overallHealth === 'healthy' ? 'text-green-500' : 'text-amber-500'
              )} />
            </div>
            <div>
              <p className="text-sm text-muted-foreground">API Server</p>
              <div className="flex items-center gap-2">
                <div className={cn(
                  'status-dot',
                  overallHealth === 'healthy' ? 'status-dot-success' : 'status-dot-warning'
                )} />
                <p className="text-sm font-medium text-foreground capitalize">
                  {overallHealth}
                </p>
              </div>
            </div>
          </div>
        </div>

        <div
          className="bg-card border border-border rounded-lg p-4 animate-fade-in-up animate-initial"
          style={{ animationDelay: '50ms', animationFillMode: 'forwards' }}
        >
          <div className="flex items-center gap-3">
            <div className={cn(
              'p-2 rounded-lg',
              meilisearchStatus === 'available' ? 'bg-green-500/10' : 'bg-destructive/10'
            )}>
              <Database className={cn(
                'h-5 w-5',
                meilisearchStatus === 'available' ? 'text-green-500' : 'text-destructive'
              )} />
            </div>
            <div>
              <p className="text-sm text-muted-foreground">Meilisearch</p>
              <div className="flex items-center gap-2">
                <div className={cn(
                  'status-dot',
                  meilisearchStatus === 'available' ? 'status-dot-success' : 'status-dot-error'
                )} />
                <p className="text-sm font-medium text-foreground capitalize">
                  {meilisearchStatus === 'available' ? 'Connected' : meilisearchStatus}
                </p>
              </div>
            </div>
          </div>
        </div>

        <div
          className="bg-card border border-border rounded-lg p-4 animate-fade-in-up animate-initial"
          style={{ animationDelay: '100ms', animationFillMode: 'forwards' }}
        >
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-cyan/10">
              <CheckCircle className="h-5 w-5 text-cyan" />
            </div>
            <div>
              <p className="text-sm text-muted-foreground">Version</p>
              <p className="text-sm font-medium text-foreground font-mono">
                {healthData?.version || 'unknown'}
              </p>
            </div>
          </div>
        </div>
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
            {totalDocs.toLocaleString()}
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
            {sources.length}
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
            {formatDate(lastIndexed)}
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
            totalFailed > 0 ? 'text-amber-500' : 'text-foreground'
          )}>
            {totalFailed}
          </p>
        </div>
      </div>

      {/* Per-source status */}
      <div className="space-y-3">
        <h2 className="text-sm font-medium text-foreground mb-4">
          Source Status
        </h2>

        {sources.length > 0 ? (
          sources.map((source, index) => (
            <SourceStatusCard key={source.source_id} source={source} index={index} />
          ))
        ) : (
          <div className="bg-card border border-border rounded-lg p-8 text-center">
            <AlertCircle className="h-8 w-8 text-muted-foreground mx-auto mb-3" />
            <p className="text-muted-foreground">
              No sources configured. Add a source to start indexing.
            </p>
          </div>
        )}
      </div>

      {/* Auto-refresh indicator */}
      <div className="mt-6 flex items-center justify-center gap-2 text-xs text-muted-foreground">
        <Loader2 className="h-3 w-3 animate-spin" />
        <span>Auto-refreshing every 30 seconds</span>
      </div>
    </div>
  )
}
