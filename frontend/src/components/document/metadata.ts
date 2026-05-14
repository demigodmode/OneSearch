// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

export function metadataString(metadata: Record<string, unknown>, key: string): string | null {
  const value = metadata[key]
  if (value === null || value === undefined || value === '') return null
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
