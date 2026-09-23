// Copyright (C) 2026 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

/* eslint-disable react-refresh/only-export-components */

import { useEffect, useRef, useState } from 'react'
import { ChevronUp, Folder } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { SourceBrowseEntry } from '@/types/api'

export interface BrowseRoot { root_id: string; path: string; label?: string | null }
// error: a failed browse that still echoes its root/path, so identity is checked before it's shown
export interface BrowsePage { root_id: string; path: string; entries: SourceBrowseEntry[]; truncated: boolean; error?: string | null }
export type PathStyle = 'posix' | 'windows'

export function joinRootPath(root: string, relative: string, style: PathStyle) {
  if (!relative) return root
  if (style === 'windows') {
    const nativeRelative = relative.replace(/\//g, '\\')
    if (/^[A-Za-z]:[\\/]+$/.test(root)) return `${root.replace(/\//g, '\\')}${nativeRelative}`
    return `${root.replace(/[\\/]+$/, '')}\\${nativeRelative}`
  }
  return `${root.replace(/\/+$/, '')}/${relative}`
}

export function FolderBrowser({ roots, available, pathStyle, browse, onSelect }: {
  roots: BrowseRoot[]
  available: boolean
  pathStyle: PathStyle
  browse: (rootId: string, relativePath: string) => Promise<BrowsePage>
  onSelect: (absolutePath: string) => void
}) {
  const [rootId, setRootId] = useState('')
  const [relativePath, setRelativePath] = useState('')
  const [page, setPage] = useState<BrowsePage | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const requestId = useRef(0)
  const mounted = useRef(true)
  const root = roots.find((item) => item.root_id === rootId)

  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false; requestId.current += 1 }
  }, [])

  const load = (nextRootId: string, nextRelativePath: string) => {
    if (!available || loading) return
    const id = ++requestId.current
    setRootId(nextRootId); setRelativePath(nextRelativePath); setPage(null); setError(null); setLoading(true)
    browse(nextRootId, nextRelativePath)
      .then((response) => {
        // stale or mismatched responses never replace the current view
        if (!mounted.current || requestId.current !== id || response.root_id !== nextRootId || response.path !== nextRelativePath) return
        if (response.error) { setError(response.error); return }
        setPage(response)
      })
      .catch((err: unknown) => { if (mounted.current && requestId.current === id) setError(err instanceof Error ? err.message : 'Unable to browse this directory.') })
      .finally(() => { if (mounted.current && requestId.current === id) setLoading(false) })
  }
  const selectRoot = (nextRootId: string) => {
    const nextRoot = roots.find((item) => item.root_id === nextRootId)
    if (!nextRoot) return
    onSelect(nextRoot.path); load(nextRootId, '')
  }
  const navigate = (nextRelativePath: string) => {
    if (!root) return
    onSelect(joinRootPath(root.path, nextRelativePath, pathStyle)); load(root.root_id, nextRelativePath)
  }
  const current = root ? joinRootPath(root.path, relativePath, pathStyle) : ''

  return <>
    <select aria-label="Allowed root" className="w-full rounded-lg border border-border bg-background px-3 py-2" value={rootId} onChange={(event) => selectRoot(event.target.value)} disabled={!available || loading}>
      <option value="">Choose an allowed root (or enter a path)</option>
      {roots.map((item) => <option key={item.root_id} value={item.root_id}>{item.label ?? item.path}</option>)}
    </select>
    {root && <div className="space-y-2 rounded-lg border border-border p-3" aria-live="polite">
      <p className="truncate font-mono text-xs" title={current}>Browsing: {current}</p>
      {relativePath && <Button type="button" size="sm" variant="ghost" onClick={() => navigate(relativePath.split('/').slice(0, -1).join('/'))} disabled={loading}><ChevronUp className="mr-1 h-4 w-4" />Parent folder</Button>}
      {loading && <p className="text-xs text-muted-foreground" role="status">Loading folders from {current}…</p>}
      {error && <div className="flex flex-wrap items-center gap-2 text-xs text-destructive" role="alert"><span>{error}</span><Button type="button" size="sm" variant="secondary" onClick={() => load(root.root_id, relativePath)} disabled={loading}>Retry</Button></div>}
      {!loading && !error && page?.entries.length === 0 && <p className="text-xs text-muted-foreground">No subfolders here. You can still enter a path manually.</p>}
      {page?.truncated && <p className="text-xs text-muted-foreground">Only the first 500 folders are shown. Enter a path manually for another folder.</p>}
      <div className="space-y-1">{page?.entries.map((entry) => <button key={entry.path} type="button" onClick={() => navigate(entry.path)} disabled={loading} className="flex w-full min-w-0 items-center gap-2 rounded-md px-2 py-1 text-left text-sm hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50" title={entry.name} aria-label={`Open folder ${entry.name}`}><Folder className="h-4 w-4 shrink-0" /><span className="truncate">{entry.name}</span></button>)}</div>
    </div>}
  </>
}
