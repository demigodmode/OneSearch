// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { useState } from 'react'
import { Database, Plus, FolderOpen, RefreshCw, Pencil, Trash2, Loader2, AlertCircle, Clock } from 'lucide-react'
import { useSources, useCreateSource, useUpdateSource, useDeleteSource, useReindexSource } from '@/hooks/useApi'
import type { Source, SourceCreate, SourceUpdate } from '@/types/api'
import { cn, formatRelativeTime } from '@/lib/utils'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Alert, AlertDescription } from '@/components/ui/alert'

// Human-readable schedule labels
function formatSchedule(schedule?: string | null): string {
  if (!schedule) return 'Manual'
  switch (schedule) {
    case '@hourly': return 'Hourly'
    case '@daily': return 'Daily'
    case '@weekly': return 'Weekly'
    default: return schedule
  }
}

// Format date for display
function formatDate(isoString: string): string {
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

// Source form component
function SourceForm({
  source,
  onSubmit,
  onCancel,
  isLoading,
  error,
}: {
  source?: Source
  onSubmit: (data: SourceCreate | SourceUpdate) => void
  onCancel: () => void
  isLoading: boolean
  error?: Error | null
}) {
  const [name, setName] = useState(source?.name || '')
  const [rootPath, setRootPath] = useState(source?.root_path || '')
  const [includePatterns, setIncludePatterns] = useState(
    source?.include_patterns?.join(', ') || ''
  )
  const [excludePatterns, setExcludePatterns] = useState(
    source?.exclude_patterns?.join(', ') || ''
  )

  // Schedule state
  const getInitialScheduleMode = () => {
    const s = source?.scan_schedule
    if (!s) return 'manual'
    if (['@hourly', '@daily', '@weekly'].includes(s)) return s
    return 'custom'
  }
  const [scheduleMode, setScheduleMode] = useState(getInitialScheduleMode)
  const [customCron, setCustomCron] = useState(
    source?.scan_schedule && !['@hourly', '@daily', '@weekly'].includes(source.scan_schedule)
      ? source.scan_schedule
      : ''
  )

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()

    let scan_schedule: string | null = null
    if (scheduleMode === 'custom') {
      scan_schedule = customCron.trim() || null
    } else if (scheduleMode !== 'manual') {
      scan_schedule = scheduleMode // @hourly, @daily, @weekly
    }

    const data: SourceCreate | SourceUpdate = {
      name: name.trim(),
      root_path: rootPath.trim(),
      include_patterns: includePatterns ? includePatterns.split(',').map(p => p.trim()).filter(Boolean) : [],
      exclude_patterns: excludePatterns ? excludePatterns.split(',').map(p => p.trim()).filter(Boolean) : [],
      scan_schedule,
    }

    onSubmit(data)
  }

  const isEdit = !!source

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            {error.message || 'An error occurred'}
          </AlertDescription>
        </Alert>
      )}

      <div className="space-y-2">
        <Label htmlFor="name">Name</Label>
        <Input
          id="name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="My Documents"
          required
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="root_path">Root Path</Label>
        <Input
          id="root_path"
          value={rootPath}
          onChange={(e) => setRootPath(e.target.value)}
          placeholder="/data/documents"
          className="font-mono text-sm"
          required
        />
        <p className="text-xs text-muted-foreground">
          Container path to the directory (e.g., /data/nas)
        </p>
      </div>

      <div className="space-y-2">
        <Label htmlFor="include_patterns">Include Patterns (optional)</Label>
        <Input
          id="include_patterns"
          value={includePatterns}
          onChange={(e) => setIncludePatterns(e.target.value)}
          placeholder="**/*.pdf, **/*.md, **/*.txt"
          className="font-mono text-sm"
        />
        <p className="text-xs text-muted-foreground">
          Comma-separated glob patterns
        </p>
      </div>

      <div className="space-y-2">
        <Label htmlFor="exclude_patterns">Exclude Patterns (optional)</Label>
        <Input
          id="exclude_patterns"
          value={excludePatterns}
          onChange={(e) => setExcludePatterns(e.target.value)}
          placeholder="**/node_modules/**, **/.git/**"
          className="font-mono text-sm"
        />
        <p className="text-xs text-muted-foreground">
          Comma-separated glob patterns
        </p>
      </div>

      <div className="space-y-2">
        <Label htmlFor="scan_schedule">Scan Schedule</Label>
        <select
          id="scan_schedule"
          value={scheduleMode}
          onChange={(e) => setScheduleMode(e.target.value)}
          className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <option value="manual">Manual only</option>
          <option value="@hourly">Every hour</option>
          <option value="@daily">Daily (2:00 AM)</option>
          <option value="@weekly">Weekly (Sunday 2:00 AM)</option>
          <option value="custom">Custom cron...</option>
        </select>
        {scheduleMode === 'custom' && (
          <Input
            value={customCron}
            onChange={(e) => setCustomCron(e.target.value)}
            placeholder="0 */6 * * *"
            className="font-mono text-sm"
          />
        )}
        <p className="text-xs text-muted-foreground">
          How often to automatically re-scan this source
        </p>
      </div>

      <DialogFooter>
        <Button type="button" variant="outline" onClick={onCancel} disabled={isLoading}>
          Cancel
        </Button>
        <Button type="submit" disabled={isLoading || !name.trim() || !rootPath.trim()}>
          {isLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
          {isEdit ? 'Save Changes' : 'Add Source'}
        </Button>
      </DialogFooter>
    </form>
  )
}

// Delete confirmation dialog
function DeleteConfirmDialog({
  source,
  open,
  onOpenChange,
  onConfirm,
  isLoading,
}: {
  source: Source | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onConfirm: () => void
  isLoading: boolean
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete Source</DialogTitle>
          <DialogDescription>
            Are you sure you want to delete "{source?.name}"? This will remove all indexed documents from this source.
            This action cannot be undone.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isLoading}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={onConfirm} disabled={isLoading}>
            {isLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Delete
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default function SourcesPage() {
  const [isAddDialogOpen, setIsAddDialogOpen] = useState(false)
  const [editingSource, setEditingSource] = useState<Source | null>(null)
  const [deletingSource, setDeletingSource] = useState<Source | null>(null)
  const [reindexingId, setReindexingId] = useState<string | null>(null)

  // Queries and mutations
  const { data: sources, isLoading: isLoadingSources, error: sourcesError } = useSources()
  const createMutation = useCreateSource()
  const updateMutation = useUpdateSource()
  const deleteMutation = useDeleteSource()
  const reindexMutation = useReindexSource()

  const handleCreate = (data: SourceCreate) => {
    createMutation.mutate(data, {
      onSuccess: () => {
        setIsAddDialogOpen(false)
      },
    })
  }

  const handleUpdate = (data: SourceUpdate) => {
    if (!editingSource) return
    updateMutation.mutate(
      { id: editingSource.id, data },
      {
        onSuccess: () => {
          setEditingSource(null)
        },
      }
    )
  }

  const handleDelete = () => {
    if (!deletingSource) return
    deleteMutation.mutate(deletingSource.id, {
      onSuccess: () => {
        setDeletingSource(null)
      },
    })
  }

  const handleReindex = (id: string) => {
    setReindexingId(id)
    reindexMutation.mutate({ id }, {
      onSettled: () => {
        setReindexingId(null)
      },
    })
  }

  const hasSources = sources && sources.length > 0

  if (isLoadingSources) {
    return (
      <div className="animate-fade-in">
        <div className="flex items-center justify-between mb-8">
          <div>
            <div className="h-8 w-32 bg-secondary rounded animate-pulse" />
            <div className="h-4 w-48 bg-secondary rounded animate-pulse mt-2" />
          </div>
        </div>
        <div className="bg-card border border-border rounded-lg p-8">
          <div className="space-y-4">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-16 bg-secondary rounded animate-pulse" />
            ))}
          </div>
        </div>
      </div>
    )
  }

  if (sourcesError) {
    return (
      <div className="animate-fade-in">
        <div className="bg-card border border-border rounded-lg p-8 text-center">
          <AlertCircle className="h-12 w-12 text-destructive mx-auto mb-4" />
          <h3 className="text-lg font-medium text-foreground mb-2">Failed to load sources</h3>
          <p className="text-muted-foreground">
            {sourcesError instanceof Error ? sourcesError.message : 'An error occurred'}
          </p>
        </div>
      </div>
    )
  }

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
          onClick={() => { createMutation.reset(); setIsAddDialogOpen(true) }}
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
                <th className="text-left px-4 py-3 text-xs font-medium text-muted-foreground uppercase tracking-wider hidden lg:table-cell">
                  Schedule
                </th>
                <th className="text-right px-4 py-3 text-xs font-medium text-muted-foreground uppercase tracking-wider hidden sm:table-cell">
                  Last Updated
                </th>
                <th className="text-right px-4 py-3 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {sources?.map((source, index) => (
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
                        <p className="text-xs text-muted-foreground font-mono md:hidden truncate max-w-[200px]">
                          {source.root_path}
                        </p>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-4 hidden md:table-cell">
                    <code className="text-sm text-muted-foreground font-mono">{source.root_path}</code>
                  </td>
                  <td className="px-4 py-4 hidden lg:table-cell">
                    <div className="flex items-center gap-1.5">
                      <Clock className="h-3.5 w-3.5 text-muted-foreground" />
                      <span className="text-sm text-muted-foreground">{formatSchedule(source.scan_schedule)}</span>
                    </div>
                    {source.next_scan_at && (
                      <span className="text-xs text-muted-foreground/70 ml-5">
                        Next: {formatRelativeTime(source.next_scan_at)}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-4 text-right hidden sm:table-cell">
                    <span className="text-sm text-muted-foreground">{formatDate(source.updated_at)}</span>
                  </td>
                  <td className="px-4 py-4 text-right">
                    <div className="flex items-center justify-end gap-1">
                      <button
                        className={cn(
                          "p-2 rounded-lg transition-colors",
                          reindexingId === source.id
                            ? "text-cyan bg-cyan/10"
                            : "text-muted-foreground hover:text-cyan hover:bg-cyan/10"
                        )}
                        title="Reindex"
                        onClick={() => handleReindex(source.id)}
                        disabled={reindexingId === source.id}
                      >
                        <RefreshCw className={cn("h-4 w-4", reindexingId === source.id && "animate-spin")} />
                      </button>
                      <button
                        className="p-2 text-muted-foreground hover:text-foreground hover:bg-secondary rounded-lg transition-colors"
                        title="Edit"
                        onClick={() => { updateMutation.reset(); setEditingSource(source) }}
                      >
                        <Pencil className="h-4 w-4" />
                      </button>
                      <button
                        className="p-2 text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded-lg transition-colors"
                        title="Delete"
                        onClick={() => setDeletingSource(source)}
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
              onClick={() => { createMutation.reset(); setIsAddDialogOpen(true) }}
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

      {/* Add Source Dialog */}
      <Dialog open={isAddDialogOpen} onOpenChange={setIsAddDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add Source</DialogTitle>
            <DialogDescription>
              Add a new directory to index. The path should be accessible from inside the Docker container.
            </DialogDescription>
          </DialogHeader>
          <SourceForm
            onSubmit={(data) => handleCreate(data as SourceCreate)}
            onCancel={() => setIsAddDialogOpen(false)}
            isLoading={createMutation.isPending}
            error={createMutation.error}
          />
        </DialogContent>
      </Dialog>

      {/* Edit Source Dialog */}
      <Dialog open={!!editingSource} onOpenChange={(open) => !open && setEditingSource(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit Source</DialogTitle>
            <DialogDescription>
              Update the source configuration. Changes will apply on the next reindex.
            </DialogDescription>
          </DialogHeader>
          {editingSource && (
            <SourceForm
              source={editingSource}
              onSubmit={handleUpdate}
              onCancel={() => setEditingSource(null)}
              isLoading={updateMutation.isPending}
              error={updateMutation.error}
            />
          )}
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <DeleteConfirmDialog
        source={deletingSource}
        open={!!deletingSource}
        onOpenChange={(open) => !open && setDeletingSource(null)}
        onConfirm={handleDelete}
        isLoading={deleteMutation.isPending}
      />
    </div>
  )
}
