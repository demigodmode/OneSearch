// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { useState } from 'react'
import { AlertCircle, ChevronRight, Loader2 } from 'lucide-react'
import { useHealth, useStatus } from '@/hooks/useApi'
import type { SourceStatus, FailedFile } from '@/types/api'
import { cn, formatRelativeTime } from '@/lib/utils'

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

// Get source status (with safe defaults for error entries)
function getSourceHealthStatus(source: SourceStatus): 'healthy' | 'warning' | 'error' {
  const failed = source.failed ?? 0
  const successful = source.successful ?? 0
  if (failed > 0 && failed > successful * 0.1) return 'error'
  if (failed > 0) return 'warning'
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
        healthStatus === 'warning' ? 'border-warning/50' :
        'border-border'
      )}
      style={{ animationDelay: `${200 + index * 75}ms`, animationFillMode: 'forwards' }}
    >
      <div
        className={cn(
          "p-4 transition-colors",
          hasFailedFiles
            ? "cursor-pointer hover:bg-secondary/20"
            : "cursor-default"
        )}
        onClick={() => hasFailedFiles && setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {hasFailedFiles && (
              <ChevronRight
                className="h-4 w-4 text-muted-foreground transition-transform duration-300"
                style={{ transform: isExpanded ? 'rotate(90deg)' : 'rotate(0deg)' }}
              />
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
                {source.scan_schedule && source.next_scan_at && (
                  <span className="ml-2">
                    &middot; Next scan {formatRelativeTime(source.next_scan_at)}
                  </span>
                )}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-6 text-sm">
            <div className="text-right">
              <p className="font-mono text-foreground">{(source.total_files ?? 0).toLocaleString()}</p>
              <p className="text-xs text-muted-foreground">total</p>
            </div>
            <div className="text-right">
              <p className="font-mono text-success">{(source.successful ?? 0).toLocaleString()}</p>
              <p className="text-xs text-muted-foreground">indexed</p>
            </div>
            {(source.skipped ?? 0) > 0 && (
              <div className="text-right">
                <p className="font-mono text-muted-foreground">{source.skipped.toLocaleString()}</p>
                <p className="text-xs text-muted-foreground">skipped</p>
              </div>
            )}
            {(source.failed ?? 0) > 0 && (
              <div className="text-right">
                <p className="font-mono text-warning">{source.failed}</p>
                <p className="text-xs text-muted-foreground">failed</p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Animated expand area for failed files */}
      {hasFailedFiles && source.failed_files && (
        <div
          className="grid transition-all duration-300 overflow-hidden"
          style={{
            gridTemplateRows: isExpanded ? '1fr' : '0fr',
            transitionTimingFunction: 'cubic-bezier(0.16, 1, 0.3, 1)',
          }}
        >
          <div className="overflow-hidden">
            <div className="px-4 pb-4">
              <FailedFilesList files={source.failed_files} />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default function StatusPage() {
  const { data: healthData, isLoading: isLoadingHealth, error: healthError } = useHealth()
  const { data: statusData, isLoading: isLoadingStatus, error: statusError } = useStatus()

  const isLoading = isLoadingHealth || isLoadingStatus
  const hasError = healthError || statusError

  // Calculate aggregate stats (with safe defaults for error entries)
  const sources = statusData?.sources || []
  const totalDocs = sources.reduce((sum, s) => sum + (s.successful ?? 0), 0)
  const totalFailed = sources.reduce((sum, s) => sum + (s.failed ?? 0), 0)
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
        <div className="flex gap-4 mb-8">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="h-4 w-20 bg-secondary rounded animate-pulse" />
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

      {/* System status — compact summary */}
      <div
        className="flex flex-wrap items-center gap-x-5 gap-y-2 mb-8 text-sm animate-fade-in-up animate-initial"
        style={{ animationDelay: '0ms', animationFillMode: 'forwards' }}
      >
        <div className="flex items-center gap-2">
          <div className={cn(
            'status-dot',
            overallHealth === 'healthy' ? 'status-dot-success status-dot-live' : 'status-dot-warning'
          )} />
          <span className="text-muted-foreground">API</span>
          <span className="text-foreground capitalize">{overallHealth}</span>
        </div>
        <div className="flex items-center gap-2">
          <div className={cn(
            'status-dot',
            meilisearchStatus === 'available' ? 'status-dot-success status-dot-live' : 'status-dot-error'
          )} />
          <span className="text-muted-foreground">Search</span>
          <span className="text-foreground">{meilisearchStatus === 'available' ? 'connected' : meilisearchStatus}</span>
        </div>
        <span className="text-muted-foreground/40 hidden sm:inline">|</span>
        <span className="text-muted-foreground">{totalDocs.toLocaleString()} docs</span>
        <span className="text-muted-foreground/40 hidden sm:inline">·</span>
        <span className="text-muted-foreground">{sources.length} {sources.length === 1 ? 'source' : 'sources'}</span>
        <span className="text-muted-foreground/40 hidden sm:inline">·</span>
        <span className="text-muted-foreground">indexed {formatDate(lastIndexed)}</span>
        {totalFailed > 0 && (
          <>
            <span className="text-muted-foreground/40 hidden sm:inline">·</span>
            <span className="text-warning">{totalFailed} failed</span>
          </>
        )}
        {healthData?.version && (
          <span className="sm:ml-auto text-muted-foreground font-mono text-xs">
            v{healthData.version}
          </span>
        )}
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
