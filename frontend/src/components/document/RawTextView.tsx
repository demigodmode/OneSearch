// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { AlertCircle, FileWarning, Loader2, RotateCw } from 'lucide-react'
import { useDocumentRawText } from '@/hooks/useApi'
import { formatSize } from '@/lib/utils'
import type { Document } from '@/types/api'
import { CodeRenderer } from './CodeRenderer'

type RawDocument = Pick<Document, 'id' | 'modified_at' | 'size_bytes'>

export function RawTextView({
  document,
  language,
  maxBytes,
}: {
  document: RawDocument
  language: string
  maxBytes: number
}) {
  const tooLarge = document.size_bytes > maxBytes
  const { data, isLoading, error, refetch } = useDocumentRawText(document.id, document.modified_at, !tooLarge, maxBytes)

  if (tooLarge) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        <FileWarning className="h-10 w-10 mx-auto mb-3 opacity-60" />
        <p>This file is too large to show here ({formatSize(document.size_bytes)}). Download it to see the original.</p>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 py-12 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin" />
        Loading original file…
      </div>
    )
  }

  if (error) {
    return (
      <div className="text-center py-12">
        <AlertCircle className="h-10 w-10 mx-auto mb-3 text-destructive" />
        <p className="text-foreground">{error.message}</p>
        <button
          onClick={() => refetch()}
          className="mt-4 inline-flex items-center gap-2 px-3 py-2 text-sm rounded-lg text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
        >
          <RotateCw className="h-4 w-4" />
          Retry
        </button>
      </div>
    )
  }

  return <CodeRenderer content={data ?? ''} language={language} />
}
