// Copyright (C) 2026 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { useEffect, useRef, useState } from 'react'
import { FolderBrowser, type SelectedFolder, type BrowsePage, type PathStyle } from '@/components/FolderBrowser'
import { SchedulePicker } from '@/components/SchedulePicker'
import { useLocalSourceRoots } from '@/hooks/useApi'
import { browseLocalDirectory, browseSourceDirectory, createSourceBatch, createSourceBatchItem, getSourceBatch, testSourcePath, ApiError } from '@/lib/api'
import type { Agent, ProcessingMode, ScheduleConfig, SourceBatch, SourceBatchCreate, SourceBatchItem } from '@/types/api'
import { Button } from '@/components/ui/button'
import { Trash2 } from 'lucide-react'

interface ReviewFolder extends SelectedFolder { id: string; name: string }

// A dialog can close while a request is still in flight. Reopening it in this tab
// must join that request rather than issue another create for the same item.
const inFlightItemCreates = new Map<string, Promise<SourceBatchItem>>()
const uncertainBatches = new Set<string>()

function createItemOnce(key: string, send: () => Promise<SourceBatchItem>): Promise<SourceBatchItem> {
  const pending = inFlightItemCreates.get(key)
  if (pending) return pending
  const request = Promise.resolve().then(send)
  inFlightItemCreates.set(key, request)
  void request.then(() => { if (inFlightItemCreates.get(key) === request) inFlightItemCreates.delete(key) },
    () => { if (inFlightItemCreates.get(key) === request) inFlightItemCreates.delete(key) })
  return request
}

function defaultName(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean)
  return parts[parts.length - 1] || path
}

function newUuid(): string {
  // getRandomValues works on HTTP LAN pages, where randomUUID is unavailable.
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

export function BatchSourceDialog({ onClose, onChanged, onSourceCreated, agents, remoteAgentsEnabled, defaultSchedule, resumeId }: {
  onClose: () => void
  onChanged: () => void
  onSourceCreated?: (sourceId: string) => void
  agents: Agent[]
  remoteAgentsEnabled: boolean
  defaultSchedule: ScheduleConfig | null
  resumeId?: string | null
}) {
  const { data: localRoots, isLoading: loadingRoots, isError: rootsError, refetch: refetchRoots } = useLocalSourceRoots()
  const [step, setStep] = useState<'select' | 'review' | 'results'>(resumeId ? 'results' : 'select')
  const [locationType, setLocationType] = useState<'local' | 'agent'>('local')
  const [agentId, setAgentId] = useState('')
  const [selected, setSelected] = useState<ReviewFolder[]>([])
  const [schedule, setSchedule] = useState<ScheduleConfig>({ schedule_type: 'cron', scan_schedule: null, interval_value: null, interval_unit: null })
  const [useDefaultSchedule, setUseDefaultSchedule] = useState(Boolean(defaultSchedule))
  const [includePatterns, setIncludePatterns] = useState('')
  const [excludePatterns, setExcludePatterns] = useState('')
  const [processingMode, setProcessingMode] = useState<ProcessingMode | ''>('')
  const [batch, setBatch] = useState<SourceBatch | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [interrupted, setInterrupted] = useState(false)
  const proofCache = useRef(new Map<string, { jobId: string; at: number }>())
  const operation = useRef<SourceBatchCreate | null>(null)
  const observedCreated = useRef(new Set<string>())
  const sourceCreatedCallback = useRef(onSourceCreated)
  const mounted = useRef(true)

  useEffect(() => { sourceCreatedCallback.current = onSourceCreated }, [onSourceCreated])
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  useEffect(() => {
    if (!resumeId) return
    getSourceBatch(resumeId).then((saved) => {
      if (!mounted.current) return
      const createdIds = saved.items.filter((item) => item.state === 'created' && item.source_id).map((item) => item.source_id!)
      // Only an uncertain prior write needs reconciliation on reopen. Ordinary
      // historical batches do not refetch Sources on every view/close.
      if (uncertainBatches.has(resumeId)) createdIds.forEach((sourceId) => sourceCreatedCallback.current?.(sourceId))
      observedCreated.current = new Set(createdIds)
      if (saved.items.every((item) => item.state !== 'pending')) uncertainBatches.delete(resumeId)
      setBatch(saved)
    }, () => { if (mounted.current) setError('Could not load this batch. Try reopening it.') })
  }, [resumeId])

  const selectedAgent = agents.find((agent) => agent.id === agentId)
  const availableAgents = agents.filter((agent) => agent.approved_at && (agent.status === 'online' || agent.status === 'degraded'))
  const available = locationType === 'local' ? Boolean(localRoots?.browse_available) : Boolean(selectedAgent && availableAgents.includes(selectedAgent))
  const roots = locationType === 'local' ? localRoots?.roots ?? [] : selectedAgent?.allowed_roots ?? []
  const pathStyle: PathStyle = selectedAgent?.platform.toLowerCase().startsWith('win') && locationType === 'agent' ? 'windows' : 'posix'
  const browse = (rootId: string, path: string): Promise<BrowsePage> => locationType === 'local'
    ? browseLocalDirectory(rootId, path)
    : browseSourceDirectory({ agent_id: agentId, root_id: rootId, path }).then((result) => result.status === 'completed' ? result : { ...result, error: result.error || 'Directory browse did not complete.' })

  const toggle = (folder: SelectedFolder) => {
    setSelected((current) => {
      const match = current.find((item) => item.root_id === folder.root_id && item.path === folder.path)
      if (match) return current.filter((item) => item !== match)
      if (current.length >= 25) return current
      return [...current, { ...folder, id: newUuid(), name: defaultName(folder.absolute_path) }]
    })
  }
  const changeLocation = (next: 'local' | 'agent') => {
    setLocationType(next); setAgentId(''); setSelected([]); setError(null)
  }
  const recordCreated = (items: SourceBatchItem[]) => {
    for (const item of items) {
      if (item.state !== 'created' || !item.source_id || observedCreated.current.has(item.source_id)) continue
      observedCreated.current.add(item.source_id)
      sourceCreatedCallback.current?.(item.source_id)
    }
  }
  const refresh = async (id: string) => {
    const saved = await getSourceBatch(id)
    recordCreated(saved.items)
    if (saved.items.every((item) => item.state !== 'pending')) uncertainBatches.delete(id)
    if (mounted.current) setBatch(saved)
    return saved
  }
  const createOne = async (current: SourceBatch, item: SourceBatchItem): Promise<boolean> => {
    const key = `${current.id}:${item.id}`
    try {
      const result = await createItemOnce(key, async () => {
        let proof: string | null = null
        if (current.location_type === 'agent') {
          const pathKey = `${current.agent_id}\n${item.root_path}`
          const cached = proofCache.current.get(pathKey)
          if (cached && Date.now() - cached.at < 9 * 60_000) proof = cached.jobId
          else {
            try {
              const validation = await testSourcePath({ root_path: item.root_path, location_type: 'agent', agent_id: current.agent_id })
              if (validation.ok && validation.status === 'completed' && validation.job_id && validation.path === item.root_path) {
                proof = validation.job_id
                proofCache.current.set(pathKey, { jobId: proof, at: Date.now() })
              }
            } catch { /* The create endpoint records a retryable missing-proof outcome. */ }
          }
        }
        return createSourceBatchItem(current.id, item.id, proof)
      })
      recordCreated([result])
      const saved = await refresh(current.id)
      if (result.warning && mounted.current) setBatch({ ...saved, items: saved.items.map((row) => row.id === item.id ? { ...row, warning: result.warning } : row) })
      return true
    } catch {
      // A dropped response may follow a committed create. Reconcile before showing failure.
      try { await refresh(current.id) } catch { uncertainBatches.add(current.id) }
      if (mounted.current) { setInterrupted(true); setError('Connection interrupted. Check batch status before continuing.') }
      return false
    }
  }
  const run = async (current: SourceBatch, onlyItemId?: string) => {
    setBusy(true); setError(null); setInterrupted(false)
    try {
      let latest = await refresh(current.id)
      for (const item of latest.items) {
        if (!mounted.current) break
        if (onlyItemId ? item.id !== onlyItemId || item.state !== 'failed' : item.state !== 'pending') continue
        if (!await createOne(latest, item)) break
        latest = await refresh(current.id)
      }
    } catch {
      setInterrupted(true); setError('Could not reconcile this batch. Reopen it to check its saved state.')
    } finally {
      onChanged()
      if (mounted.current) setBusy(false)
    }
  }
  const submit = async () => {
    const names = selected.map((item) => item.name.trim())
    if (!names.length || names.some((name) => !name || name.length > 200)) { setError('Every folder needs a name of 1–200 characters.'); return }
    const paths = selected.map((item) => pathStyle === 'windows' ? item.absolute_path.toLowerCase() : item.absolute_path)
    if (new Set(paths).size !== paths.length) { setError('Remove duplicate selected paths before submitting.'); return }
    if (!useDefaultSchedule && schedule.schedule_type === 'interval' && !schedule.interval_value) { setError('Enter a valid scan interval.'); return }
    const patterns = (value: string) => value.split(',').map((pattern) => pattern.trim()).filter(Boolean)
    const include = patterns(includePatterns), exclude = patterns(excludePatterns)
    if (include.length > 20 || exclude.length > 20 || [...include, ...exclude].some((pattern) => pattern.length > 256)) { setError('Use at most 20 patterns per field, each at most 256 characters.'); return }
    const payload: SourceBatchCreate = operation.current ?? {
      id: newUuid(), location_type: locationType, agent_id: locationType === 'agent' ? agentId : null,
      common_settings: { ...schedule, include_patterns: include, exclude_patterns: exclude, use_default_schedule: useDefaultSchedule, processing_mode: locationType === 'agent' ? processingMode || null : null },
      items: selected.map((item, index) => ({ id: item.id, name: names[index], root_path: item.absolute_path })),
    }
    operation.current = payload // A lost initial response keeps the same operation UUID and immutable payload.
    setBusy(true); setError(null)
    let saved: SourceBatch
    try {
      saved = await createSourceBatch(payload)
    } catch (cause) {
      try {
        saved = await getSourceBatch(payload.id)
      } catch {
        if (cause instanceof ApiError && cause.status !== 404) { setError(cause.message); setBusy(false); return }
        try { saved = await createSourceBatch(payload) }
        catch { uncertainBatches.add(payload.id); setError('Submission is uncertain. Retry this same batch to recover its saved operation.'); setBusy(false); return }
      }
    }
    recordCreated(saved.items)
    setBatch(saved); setStep('results'); setBusy(false)
    // Publish the durable operation as soon as it exists. Item requests can
    // remain in flight after this dialog closes, and the saved-batches list
    // must already offer a way back into it.
    onChanged()
    await run(saved)
  }
  const counts = batch && {
    created: batch.items.filter((item) => item.state === 'created').length,
    existing: batch.items.filter((item) => item.state === 'already_exists').length,
    duplicate: batch.items.filter((item) => item.state === 'duplicate_selection').length,
    attention: batch.items.filter((item) => item.state === 'failed' || item.state === 'pending').length,
  }
  const statusStyle: Record<SourceBatchItem['state'], string> = {
    created: 'border-success/50 bg-success/10',
    already_exists: 'border-border bg-secondary/40',
    duplicate_selection: 'border-warning/50 bg-warning/10',
    failed: 'border-destructive/50 bg-destructive/10',
    pending: 'border-border bg-card',
  }
  const statusLabel: Record<SourceBatchItem['state'], string> = {
    created: 'Created', already_exists: 'Already exists', duplicate_selection: 'Duplicate selection', failed: 'Needs attention', pending: 'Pending',
  }

  return <div className="max-h-[75dvh] min-w-0 space-y-4 overflow-y-auto pr-1 text-sm">
    <ol aria-label="Batch source steps" className="grid grid-cols-3 gap-2 border-b border-border pb-4">
      {(['select', 'review', 'results'] as const).map((stage, index) => <li key={stage} aria-current={step === stage ? 'step' : undefined} className={`rounded-md px-2 py-2 text-center text-xs font-medium sm:text-sm ${step === stage ? 'bg-primary text-primary-foreground' : 'bg-secondary/50 text-muted-foreground'}`}>{index + 1}. {stage === 'select' ? 'Select' : stage === 'review' ? 'Review' : 'Results'}</li>)}
    </ol>
    {error && <p role="alert" className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-destructive-strong">{error}</p>}
    {step === 'select' && <>
      <p className="text-muted-foreground">Choose up to 25 folders. Each checked folder becomes one source; its matching subfolder files are scanned recursively.</p>
      {remoteAgentsEnabled && <fieldset className="flex gap-4"><legend>Location</legend><label><input type="radio" checked={locationType === 'local'} onChange={() => changeLocation('local')} /> Local</label><label><input type="radio" checked={locationType === 'agent'} onChange={() => changeLocation('agent')} /> Remote agent</label></fieldset>}
      {locationType === 'agent' && <label className="block">Approved agent <select aria-label="Approved agent" value={agentId} onChange={(event) => { setAgentId(event.target.value); setSelected([]) }}><option value="">Choose agent</option>{availableAgents.map((agent) => <option value={agent.id} key={agent.id}>{agent.name}</option>)}</select></label>}
      {loadingRoots && locationType === 'local' && <p role="status">Loading source roots…</p>}
      {rootsError && locationType === 'local' && <p role="alert">Could not load source roots. <Button type="button" onClick={() => refetchRoots()}>Retry</Button></p>}
      {!loadingRoots && !rootsError && locationType === 'local' && !localRoots?.browse_available && <p>No local source roots are configured for browsing.</p>}
      <FolderBrowser key={`${locationType}:${agentId}`} roots={roots} available={available} pathStyle={pathStyle} browse={browse} onSelect={() => {}} multiSelect selected={selected} onToggle={toggle} />
      <section aria-label="Selected folders" className="rounded-lg border border-border bg-secondary/20 p-3">
        <h3 className="font-semibold">Selected folders</h3>
        <p aria-live="polite" className="text-xs text-muted-foreground">{selected.length} of 25 folders selected</p>
        {selected.length > 0 ? <ul className="mt-2 space-y-1">{selected.map((item) => <li key={item.id} className="break-all rounded border border-border bg-background px-2 py-1 font-mono text-xs">{item.absolute_path}</li>)}</ul> : <p className="mt-2 text-xs text-muted-foreground">Check the folders you want to add.</p>}
      </section>
      <div className="flex flex-col-reverse gap-2 border-t border-border pt-3 sm:flex-row sm:justify-end"><Button type="button" variant="outline" onClick={onClose}>Close</Button><Button type="button" disabled={!selected.length} onClick={() => { setError(null); setStep('review') }}>Review {selected.length} folder{selected.length === 1 ? '' : 's'}</Button></div>
    </>}
    {step === 'review' && <>
      <div><h3 className="text-base font-semibold">Review selected folders</h3><p className="text-muted-foreground">Give each source a name, then apply settings shared by this batch.</p></div>
      <div className="space-y-3">{selected.map((item) => <section key={item.id} className="space-y-3 rounded-lg border border-border bg-card p-3 shadow-sm"><div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between"><p className="min-w-0 break-all rounded bg-secondary/40 px-2 py-1 font-mono text-xs">{item.absolute_path}</p><Button type="button" size="icon" variant="outline" aria-label={`Remove selected folder ${item.absolute_path}`} title={`Remove selected folder ${item.absolute_path} from this batch`} className="shrink-0 self-start border-destructive-strong/60 text-destructive-strong hover:bg-destructive/10 hover:text-destructive-strong" onClick={() => setSelected((current) => current.filter((row) => row.id !== item.id))}><Trash2 aria-hidden="true" /></Button></div><label className="block space-y-1 font-medium">Name <input aria-label={`Name for ${item.absolute_path}`} className="w-full rounded-md border border-input bg-background p-2 font-normal focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" maxLength={200} value={item.name} onChange={(event) => setSelected((current) => current.map((row) => row.id === item.id ? { ...row, name: event.target.value } : row))} /></label></section>)}</div>
      <section className="space-y-3 rounded-lg border border-border bg-secondary/20 p-3" aria-label="Shared settings"><h3 className="font-semibold">Shared settings</h3>
        <label className="block space-y-1">Include patterns <input aria-label="Include patterns" className="w-full rounded-md border border-input bg-background p-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" value={includePatterns} onChange={(event) => setIncludePatterns(event.target.value)} placeholder="Comma separated" /></label>
        <label className="block space-y-1">Exclude patterns <input aria-label="Exclude patterns" className="w-full rounded-md border border-input bg-background p-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" value={excludePatterns} onChange={(event) => setExcludePatterns(event.target.value)} placeholder="Comma separated" /></label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={useDefaultSchedule} onChange={(event) => setUseDefaultSchedule(event.target.checked)} /> Use default scan schedule</label>
        {!useDefaultSchedule && <SchedulePicker value={schedule} onChange={setSchedule} idPrefix="batch-schedule" />}
        {locationType === 'agent' && <label className="block">Processing mode <select aria-label="Processing mode" value={processingMode} onChange={(event) => setProcessingMode(event.target.value as ProcessingMode | '')}><option value="">Inherit agent default</option><option value="on_agent">On agent</option><option value="on_server">On server</option></select></label>}
      </section>
      <div className="flex flex-col-reverse gap-2 border-t border-border pt-3 sm:flex-row sm:justify-end"><Button type="button" variant="outline" onClick={() => setStep('select')}>Back to folders</Button><Button type="button" disabled={busy || !selected.length} onClick={submit}>{busy ? 'Submitting…' : `Create ${selected.length} source${selected.length === 1 ? '' : 's'}`}</Button></div>
    </>}
    {step === 'results' && <>
      {!batch ? <p role="status">Loading saved batch…</p> : <>
        <div className="rounded-lg border border-border bg-secondary/20 p-3" aria-live="polite"><h3 className="font-semibold">Batch results</h3><p>{counts?.created} created, {counts?.existing} already existed, {counts?.duplicate} duplicate selections, {counts?.attention} need attention</p></div>
        <ul className="space-y-2">{batch.items.map((item) => <li id={`batch-item-${item.id}`} key={item.id} className={`space-y-2 rounded-lg border p-3 ${statusStyle[item.state]}`}><div className="flex flex-wrap items-center gap-2"><p className="break-all font-semibold">{item.name}</p><span className="rounded-full border border-current/30 px-2 py-0.5 text-xs font-medium">{statusLabel[item.state]}</span></div><p className="break-all font-mono text-xs text-muted-foreground">{item.root_path}</p>
          {item.error && <p role="alert">{item.error}</p>}{item.warning && <p role="status">{item.warning}</p>}
          {item.duplicate_of_item_id && <p>Same location as <a className="underline" href={`#batch-item-${item.duplicate_of_item_id}`}>row {batch.items.findIndex((row) => row.id === item.duplicate_of_item_id) + 1}</a>.</p>}
          {item.source_deleted && <p>Source was deleted.</p>}
          {item.state === 'already_exists' && <p className="text-xs text-muted-foreground">This exact folder already has a source; nothing new was created.</p>}
          {item.source_id && !item.source_deleted && <a className="text-brand-strong underline" href={`#source-${encodeURIComponent(item.source_id)}`} onClick={onClose}>View source</a>}
          {item.state === 'failed' && <Button type="button" disabled={busy} onClick={() => run(batch, item.id)}>Retry {item.name}</Button>}
        </li>)}</ul>
        {batch.items.some((item) => item.state === 'pending') && <Button type="button" disabled={busy} onClick={() => run(batch)}>Resume batch</Button>}
        {interrupted && <Button type="button" variant="outline" onClick={async () => {
          try { await refresh(batch.id); onChanged(); setInterrupted(false) }
          catch { setError('Could not check saved status. Try reopening this batch.') }
        }}>Check saved status</Button>}
      </>}
    </>}
    {step === 'results' && <div className="flex justify-end border-t border-border pt-3"><Button type="button" onClick={onClose}>Done</Button></div>}
  </div>
}
