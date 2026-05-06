// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

export interface SearchSettings {
  resultsPerPage: 10 | 20 | 25 | 50
  sortOrder: 'relevance' | 'modified_at:desc' | 'modified_at:asc' | 'size_bytes:desc' | 'basename:asc'
  snippetLength: 'short' | 'medium' | 'long'
  density: 'compact' | 'comfortable' | 'spacious'
  showPath: boolean
  showSize: boolean
  showDate: boolean
}

export const SNIPPET_LENGTH_MAP: Record<SearchSettings['snippetLength'], number> = {
  short: 100,
  medium: 300,
  long: 500,
}

export const DEFAULT_SETTINGS: SearchSettings = {
  resultsPerPage: 20,
  sortOrder: 'relevance',
  snippetLength: 'medium',
  density: 'comfortable',
  showPath: true,
  showSize: true,
  showDate: true,
}
