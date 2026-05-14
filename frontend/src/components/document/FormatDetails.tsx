// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { useEffect, useState } from 'react'
import {
  AlertCircle,
  BookOpen,
  Camera,
  FileArchive,
  Film,
  List,
  Loader2,
} from 'lucide-react'

import { getDocumentPreviewBlob } from '@/lib/api'
import type { Document as SearchDocument } from '@/types/api'
import { MetadataCards } from './MetadataCards'
import { metadataString } from './metadata'

function ImagePreviewPanel({ document }: { document: SearchDocument }) {
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    let objectUrl: string | null = null

    getDocumentPreviewBlob(document.id)
      .then((blob) => {
        if (cancelled) return
        objectUrl = URL.createObjectURL(blob)
        setPreviewUrl(objectUrl)
      })
      .catch((err) => {
        if (cancelled) return
        setPreviewError(err instanceof Error ? err.message : 'Preview unavailable')
      })

    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [document.id])

  return (
    <div className="bg-card border border-border rounded-lg overflow-hidden">
      <div className="p-1 bg-secondary/50 border-b border-border">
        <span className="text-xs text-muted-foreground px-3">Preview</span>
      </div>
      <div className="min-h-64 flex items-center justify-center bg-background/60 p-4">
        {previewUrl ? (
          <img
            src={previewUrl}
            alt={document.title || document.basename}
            className="max-h-[70vh] max-w-full rounded-lg object-contain shadow-lg"
            onError={() => {
              setPreviewUrl(null)
              setPreviewError('Preview could not be displayed')
            }}
          />
        ) : (
          <div className="text-center text-muted-foreground py-10">
            {previewError ? (
              <>
                <AlertCircle className="h-10 w-10 mx-auto mb-3 opacity-70" />
                <p>{previewError}</p>
              </>
            ) : (
              <>
                <Loader2 className="h-10 w-10 mx-auto mb-3 animate-spin text-brand" />
                <p>Loading preview...</p>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function PhotoMetadata({ document }: { document: SearchDocument }) {
  const metadata = document.metadata || {}
  const dimensions = metadata.width && metadata.height ? `${metadata.width} × ${metadata.height}` : null
  const camera = [metadataString(metadata, 'camera_make'), metadataString(metadata, 'camera_model')]
    .filter(Boolean)
    .join(' ')

  return (
    <MetadataCards
      title="Photo metadata"
      icon={<Camera className="h-4 w-4" />}
      items={[
        { label: 'Camera', value: camera || null },
        { label: 'Date taken', value: metadataString(metadata, 'date_taken') },
        { label: 'Lens', value: metadataString(metadata, 'lens_model') },
        { label: 'ISO', value: metadataString(metadata, 'iso') },
        { label: 'Aperture', value: metadataString(metadata, 'aperture') },
        { label: 'Exposure', value: metadataString(metadata, 'exposure_time') },
        { label: 'Focal length', value: metadataString(metadata, 'focal_length') },
        { label: 'Dimensions', value: dimensions },
        { label: 'Format', value: metadataString(metadata, 'image_format') },
      ]}
    />
  )
}

function ComicDetails({ document }: { document: SearchDocument }) {
  const metadata = document.metadata || {}
  const pages = Array.isArray(metadata.page_files) ? metadata.page_files.map(String) : []

  return (
    <div className="space-y-4">
      <MetadataCards
        title="Comic metadata"
        icon={<FileArchive className="h-4 w-4" />}
        items={[
          { label: 'Title', value: metadataString(metadata, 'title') || document.title || null },
          { label: 'Series', value: metadataString(metadata, 'series') },
          { label: 'Issue', value: metadataString(metadata, 'number') },
          { label: 'Writer', value: metadataString(metadata, 'writer') },
          { label: 'Publisher', value: metadataString(metadata, 'publisher') },
          { label: 'Year', value: metadataString(metadata, 'year') },
          { label: 'Pages', value: metadataString(metadata, 'page_count') },
          { label: 'Summary', value: metadataString(metadata, 'summary') },
        ]}
      />

      {pages.length > 0 && (
        <div className="bg-card border border-border rounded-lg p-4">
          <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground mb-3">
            <List className="h-4 w-4" />
            <span>Page files</span>
          </div>
          <ol className="space-y-1 text-sm font-mono text-foreground max-h-64 overflow-auto">
            {pages.map((page, index) => (
              <li key={`${page}-${index}`} className="truncate text-muted-foreground">
                <span className="text-brand mr-2">{index + 1}.</span>{page}
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  )
}

function MediaDetails({ document }: { document: SearchDocument }) {
  const metadata = document.metadata || {}
  const dimensions = metadata.width && metadata.height ? `${metadata.width} × ${metadata.height}` : null

  return (
    <MetadataCards
      title="Media metadata"
      icon={<Film className="h-4 w-4" />}
      items={[
        { label: 'Title', value: metadataString(metadata, 'title') || document.title || null },
        { label: 'Artist', value: metadataString(metadata, 'artist') },
        { label: 'Album', value: metadataString(metadata, 'album') },
        { label: 'Date', value: metadataString(metadata, 'date') },
        { label: 'Duration', value: metadataString(metadata, 'duration') || metadataString(metadata, 'duration_seconds') },
        { label: 'Format', value: metadataString(metadata, 'format') || metadataString(metadata, 'format_name') },
        { label: 'Bitrate', value: metadataString(metadata, 'bitrate') || metadataString(metadata, 'bit_rate') },
        { label: 'Video codec', value: metadataString(metadata, 'video_codec') },
        { label: 'Audio codec', value: metadataString(metadata, 'audio_codec') },
        { label: 'Dimensions', value: dimensions },
        { label: 'Frame rate', value: metadataString(metadata, 'frame_rate') },
        { label: 'Sample rate', value: metadataString(metadata, 'sample_rate') },
        { label: 'Channels', value: metadataString(metadata, 'channels') },
      ]}
    />
  )
}

export function FormatDetails({ document }: { document: SearchDocument }) {
  if (document.type === 'image' || document.type === 'raw_image') {
    return (
      <div className="space-y-4 mb-6">
        <ImagePreviewPanel key={document.id} document={document} />
        <PhotoMetadata document={document} />
      </div>
    )
  }

  if (document.type === 'comic') {
    return <div className="mb-6"><ComicDetails document={document} /></div>
  }

  if (document.type === 'media') {
    return <div className="mb-6"><MediaDetails document={document} /></div>
  }

  if (['epub', 'rtf', 'subtitle'].includes(document.type)) {
    return (
      <div className="bg-card border border-border rounded-lg p-4 mb-6">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <BookOpen className="h-4 w-4 text-brand" />
          <span>This {document.type} is indexed as searchable text below.</span>
        </div>
      </div>
    )
  }

  return null
}
