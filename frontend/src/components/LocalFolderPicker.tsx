// Copyright (C) 2026 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { Button } from '@/components/ui/button'
import { FolderBrowser } from '@/components/FolderBrowser'
import { useLocalSourceRoots } from '@/hooks/useApi'
import { browseLocalDirectory } from '@/lib/api'

export function LocalFolderPicker({ onSelect }: { onSelect: (path: string) => void }) {
  const { data, isLoading, isError, refetch } = useLocalSourceRoots()

  // loading: render nothing rather than flash the hint on every form open
  if (isLoading) return null
  if (isError) {
    return (
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span>Couldn't load source roots. You can still type a path.</span>
        <Button type="button" size="sm" variant="secondary" onClick={() => refetch()}>Retry</Button>
      </div>
    )
  }
  if (!data) return null
  if (!data.browse_available) {
    return <p className="text-xs text-muted-foreground">Set ALLOWED_SOURCE_PATHS to browse folders here.</p>
  }
  return (
    <div className="space-y-2">
      <FolderBrowser roots={data.roots} available pathStyle="posix" browse={browseLocalDirectory} onSelect={onSelect} />
    </div>
  )
}
