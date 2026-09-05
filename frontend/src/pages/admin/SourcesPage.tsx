// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { useRef, useState } from 'react'
import { Database, Plus, FolderOpen, RefreshCw, Pencil, Trash2, Loader2, AlertCircle, Clock, CheckCircle, Link2 } from 'lucide-react'
import { useSources, useCreateSource, useUpdateSource, useDeleteSource, useReindexSource, useTestSourcePath, useAppSettings, useAgents } from '@/hooks/useApi'
import type { Agent, ProcessingMode, Source, SourceCreate, SourceUpdate, SourcePathTestResponse } from '@/types/api'
import { RemotePathPicker } from '@/components/agents/RemotePathPicker'
import { cn, formatRelativeTime } from '@/lib/utils'
import { browseSourceDirectory } from '@/lib/api'
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
import { SchedulePicker, formatScheduleConfig, parseFakeIntervalCron } from '@/components/SchedulePicker'
import type { ScheduleConfig } from '@/types/api'

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
export function SourceForm({
  source,
  defaultSchedule,
  remoteAgentsEnabled,
  agents,
  onSubmit,
  onCancel,
  isLoading,
  error,
}: {
  source?: Source
  defaultSchedule?: ScheduleConfig | null
  remoteAgentsEnabled: boolean
  agents: Agent[]
  onSubmit: (data: SourceCreate | SourceUpdate) => void
  onCancel: () => void
  isLoading: boolean
  error?: Error | null
}) {
  const [name, setName] = useState(source?.name || '')
  const [rootPath, setRootPath] = useState(source?.root_path || '')
  const [locationType, setLocationType] = useState<'local' | 'agent'>(source?.location_type ?? 'local')
  const [agentId, setAgentId] = useState(source?.agent_id ?? '')
  const [processingMode, setProcessingMode] = useState<ProcessingMode | ''>(source?.processing_mode ?? '')
  const [includePatterns, setIncludePatterns] = useState(
    source?.include_patterns?.join(', ') || ''
  )
  const [excludePatterns, setExcludePatterns] = useState(
    source?.exclude_patterns?.join(', ') || ''
  )
  const [pathTestResult, setPathTestResult] = useState<SourcePathTestResponse | null>(null)
  const [pathValidationJobId, setPathValidationJobId] = useState<string | null>(null)
  const [pathTestError, setPathTestError] = useState<string | null>(null)
  const [pathTestPending, setPathTestPending] = useState(false)
  const testPathMutation = useTestSourcePath()
  const pathTestRequestId = useRef(0)
  const currentPathContext = useRef({ locationType, agentId, rootPath: rootPath.trim() })
  const invalidatePathContext = (next: { locationType: 'local' | 'agent'; agentId: string; rootPath: string }) => {
    pathTestRequestId.current += 1
    currentPathContext.current = { ...next, rootPath: next.rootPath.trim() }
    setPathTestResult(null)
    setPathValidationJobId(null)
    setPathTestError(null)
    setPathTestPending(false)
  }

  // Schedule state
  const [useDefaultSchedule, setUseDefaultSchedule] = useState(source?.use_default_schedule ?? false)
  const [scheduleConfig, setScheduleConfig] = useState<ScheduleConfig>({
    schedule_type: source?.schedule_type ?? 'cron',
    scan_schedule: source?.scan_schedule ?? null,
    interval_value: source?.interval_value ?? null,
    interval_unit: source?.interval_unit ?? null,
  })
  const fakeInterval = parseFakeIntervalCron(source?.scan_schedule)
  const [dismissedMigrationBanner, setDismissedMigrationBanner] = useState(false)
  const showMigrationBanner = !useDefaultSchedule && !dismissedMigrationBanner && scheduleConfig.schedule_type === 'cron' && !!fakeInterval

  const handleTestPath = () => {
    const candidate = rootPath.trim()
    if (!candidate) return
    const requestContext = { locationType, agentId, rootPath: candidate }
    invalidatePathContext(requestContext)
    const requestId = pathTestRequestId.current
    setPathTestPending(true)
    testPathMutation.mutate({ root_path: candidate, location_type: locationType, agent_id: agentId || null }, {
      onSuccess: (result) => {
        const current = currentPathContext.current
        if (
          pathTestRequestId.current === requestId
          && current.locationType === requestContext.locationType
          && current.agentId === requestContext.agentId
          && current.rootPath === requestContext.rootPath
          && result.path === requestContext.rootPath
        ) {
          setPathTestPending(false)
          setPathTestResult(result)
          setPathValidationJobId(
            requestContext.locationType === 'agent'
              && result.status === 'completed'
              && result.ok
              && result.job_id
              ? result.job_id
              : null
          )
        }
      },
      onError: (requestError) => {
        const current = currentPathContext.current
        if (
          pathTestRequestId.current !== requestId
          || current.locationType !== requestContext.locationType
          || current.agentId !== requestContext.agentId
          || current.rootPath !== requestContext.rootPath
        ) return
        setPathTestPending(false)
        setPathTestResult(null)
        setPathValidationJobId(null)
        setPathTestError(requestError instanceof Error ? requestError.message : 'Unable to validate this path.')
      },
    })
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()

    const data: SourceCreate | SourceUpdate = {
      name: name.trim(),
      root_path: rootPath.trim(),
      include_patterns: includePatterns ? includePatterns.split(',').map(p => p.trim()).filter(Boolean) : [],
      exclude_patterns: excludePatterns ? excludePatterns.split(',').map(p => p.trim()).filter(Boolean) : [],
      use_default_schedule: useDefaultSchedule,
      schedule_type: scheduleConfig.schedule_type,
      scan_schedule: scheduleConfig.scan_schedule ?? null,
      interval_value: scheduleConfig.interval_value ?? null,
      interval_unit: scheduleConfig.interval_unit ?? null,
    }

    const preserveDisabledRemoteBinding = Boolean(source && source.location_type === 'agent' && !remoteAgentsEnabled)
    if (!preserveDisabledRemoteBinding) {
      data.location_type = locationType
      data.agent_id = locationType === 'agent' ? agentId : null
      data.processing_mode = locationType === 'agent' ? processingMode || null : null
      data.root_path = rootPath.trim()
    } else {
      delete data.root_path
    }
    if (locationType === 'agent' && pathValidationJobId) {
      data.path_validation_job_id = pathValidationJobId
    }

    onSubmit(data)
  }

  const isEdit = !!source
  const selectedAgent = agents.find((agent) => agent.id === agentId)
  const unchangedExistingRemote = source?.location_type === 'agent' && source.agent_id === agentId && source.root_path === rootPath
  const completedRemoteValidation = pathTestResult?.status === 'completed' && pathTestResult.ok && pathTestResult.job_id === pathValidationJobId && pathTestResult.path === rootPath.trim()
  const isSubmitDisabled = isLoading || !name.trim() || !rootPath.trim() || (locationType === 'agent' && (!agentId || (!completedRemoteValidation && !unchangedExistingRemote))) || (
    !useDefaultSchedule && scheduleConfig.schedule_type === 'interval' && !scheduleConfig.interval_value
  )

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
          title="Friendly name shown in search filters and results."
          required
        />
      </div>

      <div className="space-y-2">
        {remoteAgentsEnabled && <div className="space-y-2"><Label>Location</Label><div className="flex gap-3 text-sm"><label><input type="radio" checked={locationType === 'local'} onChange={() => { invalidatePathContext({ locationType: 'local', agentId, rootPath }); setLocationType('local') }} /> Local</label><label><input type="radio" checked={locationType === 'agent'} onChange={() => { invalidatePathContext({ locationType: 'agent', agentId, rootPath }); setLocationType('agent') }} /> Remote agent</label></div></div>}
        {locationType === 'agent' && !remoteAgentsEnabled ? <p className="rounded-lg border border-border bg-secondary/30 p-3 text-sm text-muted-foreground">Remote source binding is unavailable while remote agents are disabled. This source remains attached to {selectedAgent?.name ?? agentId} at {rootPath}.</p> : locationType === 'agent' ? <><Label htmlFor="agent">Approved agent</Label><select id="agent" value={agentId} onChange={(event) => { invalidatePathContext({ locationType, agentId: event.target.value, rootPath: '' }); setAgentId(event.target.value); setRootPath(''); setProcessingMode('') }} className="w-full rounded-lg border border-border bg-background px-3 py-2"><option value="">Choose an approved agent</option>{agents.filter((agent) => ((agent.status === 'online' || agent.status === 'degraded') && agent.approved_at) || (source?.agent_id === agent.id && agent.status === 'offline')).map((agent) => <option key={agent.id} value={agent.id}>{agent.name} ({agent.status})</option>)}</select><RemotePathPicker key={agentId} agent={selectedAgent} value={rootPath} onChange={(value) => { invalidatePathContext({ locationType, agentId, rootPath: value }); setRootPath(value) }} onTest={handleTestPath} result={pathTestResult} testing={pathTestPending} onBrowse={browseSourceDirectory} />{pathTestError && <p className="text-xs text-destructive" role="alert">{pathTestError}</p>}<label className="block text-sm">Processing mode <select value={processingMode} onChange={(event) => setProcessingMode(event.target.value as ProcessingMode | '')} className="ml-2 rounded-lg border border-border bg-background px-2 py-1"><option value="">Inherit agent default ({selectedAgent?.default_processing_mode ?? '—'})</option><option value="on_agent">On agent</option><option value="on_server">On server</option></select></label></> : <>
        <Label htmlFor="root_path">Root Path</Label>
        <Input
          id="root_path"
          value={rootPath}
          onChange={(e) => { invalidatePathContext({ locationType, agentId, rootPath: e.target.value }); setRootPath(e.target.value) }}
          placeholder="/data/documents"
          title="Path inside the OneSearch container, not necessarily the host path."
          className="font-mono text-sm"
          required
        />
        <p className="text-xs text-muted-foreground">
          Use the path OneSearch can see inside the container, usually under the configured allowed source roots.
        </p>
        {pathTestResult && (
          <Alert
            variant={pathTestResult.ok ? 'default' : 'destructive'}
            role={pathTestResult.ok ? 'status' : 'alert'}
            aria-live={pathTestResult.ok ? 'polite' : 'assertive'}
            className={pathTestResult.ok ? 'border-success/50 text-foreground [&>svg]:text-success' : undefined}
          >
            {pathTestResult.ok ? <CheckCircle className="h-4 w-4" /> : <AlertCircle className="h-4 w-4" />}
            <AlertDescription>
              <p>{pathTestResult.message}</p>
              {pathTestResult.hint && <p className="mt-1 text-xs opacity-80">{pathTestResult.hint}</p>}
              <p className="mt-2 text-xs opacity-80">
                Allowed: {pathTestResult.inside_allowed_roots ? 'yes' : 'no'} · Exists: {pathTestResult.exists ? 'yes' : 'no'} · Directory: {pathTestResult.is_directory ? 'yes' : 'no'} · Readable: {pathTestResult.readable ? 'yes' : 'no'}
              </p>
            </AlertDescription>
          </Alert>
        )}
        {pathTestError && <p className="text-xs text-destructive" role="alert">{pathTestError}</p>}
        </>}
      </div>

      <div className="space-y-2">
        <Label htmlFor="include_patterns">Include Patterns (optional)</Label>
        <Input
          id="include_patterns"
          value={includePatterns}
          onChange={(e) => setIncludePatterns(e.target.value)}
          placeholder="**/*.pdf, **/*.md, **/*.txt"
          title="Optional comma-separated glob patterns. Empty means include everything not excluded."
          className="font-mono text-sm"
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="exclude_patterns">Exclude Patterns (optional)</Label>
        <Input
          id="exclude_patterns"
          value={excludePatterns}
          onChange={(e) => setExcludePatterns(e.target.value)}
          placeholder="**/node_modules/**, **/.git/**"
          title="Optional comma-separated glob patterns to skip."
          className="font-mono text-sm"
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="use_default_schedule">Scan Schedule</Label>
        <label className="flex items-center gap-2 text-sm text-foreground">
          <input
            id="use_default_schedule"
            type="checkbox"
            checked={useDefaultSchedule}
            onChange={(e) => setUseDefaultSchedule(e.target.checked)}
          />
          Use global default
        </label>

        {useDefaultSchedule ? (
          <p className="text-xs text-muted-foreground rounded-lg border border-border bg-secondary/30 p-3">
            Following the global default: <strong>{formatScheduleConfig(defaultSchedule)}</strong>.
            Change it in Settings &rarr; Scheduling.
          </p>
        ) : (
          <>
            {showMigrationBanner && fakeInterval && (
              <Alert>
                <AlertCircle className="h-4 w-4" />
                <AlertDescription className="flex items-center justify-between gap-3">
                  <span>This looks like a fixed interval — switch to true interval?</span>
                  <div className="flex gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant="secondary"
                      onClick={() => {
                        setScheduleConfig({
                          schedule_type: 'interval',
                          scan_schedule: null,
                          interval_value: Number(fakeInterval.value),
                          interval_unit: fakeInterval.unit,
                        })
                        setDismissedMigrationBanner(true)
                      }}
                    >
                      Switch
                    </Button>
                    <Button type="button" size="sm" variant="ghost" onClick={() => setDismissedMigrationBanner(true)}>
                      Dismiss
                    </Button>
                  </div>
                </AlertDescription>
              </Alert>
            )}
            <SchedulePicker value={scheduleConfig} onChange={setScheduleConfig} idPrefix="source-schedule" />
          </>
        )}
      </div>

      <DialogFooter>
        <Button type="button" variant="secondary" onClick={handleTestPath} disabled={isLoading || pathTestPending || !rootPath.trim()}>
          {pathTestPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
          Test
        </Button>
        <Button type="button" variant="outline" onClick={onCancel} disabled={isLoading}>
          Cancel
        </Button>
        <Button type="submit" disabled={isSubmitDisabled}>
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
  const [fullReindexSource, setFullReindexSource] = useState<Source | null>(null)
  const [reindexingId, setReindexingId] = useState<string | null>(null)

  // Queries and mutations
  const { data: sources, isLoading: isLoadingSources, error: sourcesError } = useSources()
  const { data: appSettings } = useAppSettings()
  const { data: agents = [] } = useAgents()
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

  const handleFullReindex = () => {
    if (!fullReindexSource) return
    setReindexingId(fullReindexSource.id)
    reindexMutation.mutate({ id: fullReindexSource.id, full: true }, {
      onSettled: () => {
        setReindexingId(null)
        setFullReindexSource(null)
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
        <Button onClick={() => { createMutation.reset(); setIsAddDialogOpen(true) }}>
          <Plus className="h-4 w-4" />
          Add Source
        </Button>
      </div>

      {hasSources ? (
        // Sources table — @container so columns show based on table width, not viewport
        <div className="@container bg-card border border-border rounded-lg overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-border bg-secondary/30">
                <th className="text-left px-4 py-3 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  Source
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-muted-foreground uppercase tracking-wider hidden @[560px]:table-cell">
                  Path
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-muted-foreground uppercase tracking-wider hidden @[800px]:table-cell">
                  Schedule
                </th>
                <th className="text-right px-4 py-3 text-xs font-medium text-muted-foreground uppercase tracking-wider hidden @[400px]:table-cell">
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
                      <div className="p-2 rounded-lg bg-brand/10">
                        <FolderOpen className="h-4 w-4 text-brand" />
                      </div>
                      <div>
                        <p className="font-medium text-foreground">{source.name}</p>
                        <p className="text-xs text-muted-foreground font-mono @[560px]:hidden truncate max-w-[200px]">
                          {source.root_path}
                        </p>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-4 hidden @[560px]:table-cell">
                    <code className="text-sm text-muted-foreground font-mono">{source.root_path}</code>
                  </td>
                  <td className="px-4 py-4 hidden @[800px]:table-cell">
                    <div className="flex items-center gap-1.5">
                      <Clock className="h-3.5 w-3.5 text-muted-foreground" />
                      <span className="text-sm text-muted-foreground">{formatScheduleConfig(source.effective_schedule)}</span>
                      {source.use_default_schedule && (
                        <span title="Following the global default (Settings → Scheduling)">
                          <Link2 className="h-3.5 w-3.5 text-brand" aria-label="Following the global default" />
                        </span>
                      )}
                    </div>
                    {source.next_scan_at && (
                      <span className="text-xs text-muted-foreground/70 ml-5">
                        Next: {formatRelativeTime(source.next_scan_at)}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-4 text-right hidden @[400px]:table-cell">
                    <span className="text-sm text-muted-foreground">{formatDate(source.updated_at)}</span>
                  </td>
                  <td className="px-4 py-4 text-right">
                    <div className="flex items-center justify-end gap-1">
                      <button
                        className={cn(
                          "min-h-[44px] min-w-[44px] flex items-center justify-center rounded-lg transition-all active:scale-95 disabled:active:scale-100",
                          reindexingId === source.id
                            ? "text-brand bg-brand/10"
                            : "text-muted-foreground hover:text-brand hover:bg-brand/10"
                        )}
                        title="Scan this source for new, changed, or removed files."
                        aria-label={`Reindex ${source.name}`}
                        onClick={() => handleReindex(source.id)}
                        disabled={reindexingId === source.id}
                      >
                        <RefreshCw className={cn("h-4 w-4 transition-transform", reindexingId === source.id && "animate-spin")} />
                      </button>
                      <button
                        className="min-h-[44px] min-w-[44px] flex items-center justify-center text-muted-foreground hover:text-brand hover:bg-brand/10 rounded-lg transition-all active:scale-95 disabled:opacity-50 disabled:active:scale-100"
                        title="Clear this source from the index and rebuild every matching file from scratch."
                        aria-label={`Full reindex ${source.name}`}
                        onClick={() => setFullReindexSource(source)}
                        disabled={reindexingId === source.id}
                      >
                        <Database className="h-4 w-4" />
                      </button>
                      <button
                        className="min-h-[44px] min-w-[44px] flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-secondary rounded-lg transition-all active:scale-95"
                        title="Edit this source path, patterns, or scan schedule."
                        aria-label={`Edit ${source.name}`}
                        onClick={() => { updateMutation.reset(); setEditingSource(source) }}
                      >
                        <Pencil className="h-4 w-4" />
                      </button>
                      <button
                        className="min-h-[44px] min-w-[44px] flex items-center justify-center text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded-lg transition-all active:scale-95"
                        title="Delete this source and remove its indexed documents."
                        aria-label={`Delete ${source.name}`}
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
            <Button onClick={() => { createMutation.reset(); setIsAddDialogOpen(true) }}>
              <Plus className="h-4 w-4" />
              Add Your First Source
            </Button>
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
            defaultSchedule={appSettings?.default_scan_schedule}
            remoteAgentsEnabled={appSettings?.remote_agents_enabled ?? false}
            agents={agents}
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
              defaultSchedule={appSettings?.default_scan_schedule}
              remoteAgentsEnabled={appSettings?.remote_agents_enabled ?? false}
              agents={agents}
              onSubmit={handleUpdate}
              onCancel={() => setEditingSource(null)}
              isLoading={updateMutation.isPending}
              error={updateMutation.error}
            />
          )}
        </DialogContent>
      </Dialog>

      {/* Full Reindex Confirmation Dialog */}
      <Dialog open={!!fullReindexSource} onOpenChange={(open) => !open && setFullReindexSource(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Full reindex source?</DialogTitle>
            <DialogDescription>
              This clears indexed metadata for {fullReindexSource?.name} and rebuilds every matching file from scratch.
              Use this after migrating to managed Meilisearch or when search index data is out of sync.
            </DialogDescription>
          </DialogHeader>
          {fullReindexSource && (
            <Alert>
              <AlertDescription>
                Confirm the path exists inside the container first: <code className="font-mono">{fullReindexSource.root_path}</code>
              </AlertDescription>
            </Alert>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setFullReindexSource(null)} disabled={reindexMutation.isPending}>
              Cancel
            </Button>
            <Button onClick={handleFullReindex} disabled={reindexMutation.isPending}>
              {reindexMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Full reindex
            </Button>
          </DialogFooter>
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
