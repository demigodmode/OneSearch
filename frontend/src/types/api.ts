// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

/**
 * TypeScript types matching backend Pydantic schemas
 * Keep in sync with backend/app/schemas.py
 */

// ============================================================================
// Document Types
// ============================================================================

/**
 * Normalized document structure from Meilisearch
 */
export interface Document {
  id: string // Format: "source_id:/path/to/file"
  source_id: string
  source_name: string
  path: string
  basename: string
  extension: string
  type: string // File type: text, markdown, pdf, etc.
  size_bytes: number
  modified_at: number // Unix timestamp
  indexed_at: number // Unix timestamp
  content: string // Extracted full text
  title?: string // Extracted or derived title
  metadata: Record<string, unknown>
}

// ============================================================================
// Source Types
// ============================================================================

/**
 * Base source properties
 */
export interface SourceBase {
  name: string
  root_path: string
  include_patterns?: string[] | null
  exclude_patterns?: string[] | null
}

/**
 * Request body for creating a new source
 */
export interface SourceCreate extends SourceBase {
  id?: string // Auto-generated if not provided
}

/**
 * Request body for updating a source (all fields optional)
 */
export interface SourceUpdate {
  name?: string
  root_path?: string
  include_patterns?: string[] | null
  exclude_patterns?: string[] | null
}

/**
 * Source response from API
 */
export interface Source extends SourceBase {
  id: string
  created_at: string // ISO datetime string
  updated_at: string // ISO datetime string
}

// ============================================================================
// Search Types
// ============================================================================

/**
 * Search query request
 */
export interface SearchQuery {
  q: string
  source_id?: string
  type?: string
  limit?: number // 1-100, default 20
  offset?: number // default 0
}

/**
 * Individual search result
 */
export interface SearchResult {
  id: string
  path: string
  basename: string
  source_name: string
  type: string
  size_bytes: number
  modified_at: number // Unix timestamp
  snippet: string // Content with <mark> highlighting
  score: number // Relevance score
}

/**
 * Search response from API
 */
export interface SearchResponse {
  results: SearchResult[]
  total: number
  limit: number
  offset: number
  processing_time_ms: number
}

// ============================================================================
// Status Types
// ============================================================================

/**
 * Per-source indexing status
 */
export interface SourceStatus {
  source_id: string
  source_name: string
  total_files: number
  indexed_files: number
  failed_files: number
  last_indexed_at?: string | null // ISO datetime string
}

/**
 * Health check response from /api/health
 */
export interface HealthResponse {
  status: 'healthy' | 'degraded'
  service: string
  version: string
  meilisearch: {
    status: string
    [key: string]: unknown
  }
  config: {
    database: string
    meilisearch_url: string
    log_level: string
  }
}

/**
 * Overall status response from /api/status
 * Note: API returns { sources: [...] }, not a bare array
 */
export interface StatusResponse {
  sources: SourceStatus[]
}

// ============================================================================
// Reindex Types
// ============================================================================

/**
 * Indexing statistics from reindex operation
 */
export interface IndexingStats {
  total_scanned: number
  new_files: number
  modified_files: number
  unchanged_files: number
  deleted_files: number
  successful: number
  failed: number
  skipped: number
}

/**
 * Reindex response from /api/sources/{id}/reindex
 */
export interface ReindexResponse {
  message: string
  stats: IndexingStats
}

// ============================================================================
// Error Types
// ============================================================================

/**
 * API error response
 */
export interface APIError {
  detail: string
}

/**
 * Validation error (422)
 */
export interface ValidationError {
  detail: Array<{
    loc: (string | number)[]
    msg: string
    type: string
  }>
}
