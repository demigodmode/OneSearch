// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/**
 * Utility function to merge Tailwind CSS classes
 * Combines clsx for conditional classes with tailwind-merge for deduplication
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Format a future ISO date as relative time (e.g., "in 3h", "in 2d")
 */
export function formatRelativeTime(isoString?: string | null): string | null {
  if (!isoString) return null
  const date = new Date(isoString)
  const now = new Date()
  const diffMs = date.getTime() - now.getTime()
  if (diffMs < 0) return 'overdue'
  const diffMins = Math.floor(diffMs / (1000 * 60))
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60))
  if (diffMins < 60) return `in ${diffMins}m`
  if (diffHours < 24) return `in ${diffHours}h`
  const diffDays = Math.floor(diffHours / 24)
  return `in ${diffDays}d`
}

/**
 * Format byte size for display (e.g., "1.2 KB", "3.5 MB")
 */
export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/**
 * Format a unix timestamp as a relative date (e.g., "Today", "3 days ago")
 */
export function formatTimestamp(timestamp: number): string {
  const date = new Date(timestamp * 1000)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))

  if (diffDays === 0) return 'Today'
  if (diffDays === 1) return 'Yesterday'
  if (diffDays < 7) return `${diffDays} days ago`
  if (diffDays < 30) return `${Math.floor(diffDays / 7)} weeks ago`
  return date.toLocaleDateString()
}

/**
 * Format a unix timestamp as a full locale date string
 */
export function formatFullDate(timestamp: number): string {
  return new Date(timestamp * 1000).toLocaleString()
}

/**
 * Sanitize HTML snippet to prevent XSS attacks.
 * Only allows <mark> tags used by Meilisearch for highlighting search results.
 */
export function sanitizeSnippet(html: string): string {
  // First, escape all HTML to prevent XSS
  const escaped = html
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#x27;')

  // Then restore only the allowed <mark> tags from Meilisearch highlighting
  return escaped
    .replace(/&lt;mark&gt;/g, '<mark>')
    .replace(/&lt;\/mark&gt;/g, '</mark>')
}
