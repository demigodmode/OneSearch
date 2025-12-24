// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

/**
 * API client for OneSearch backend
 * All API calls go through these typed functions
 */

import type {
  Source,
  SourceCreate,
  SourceUpdate,
  SearchQuery,
  SearchResponse,
  SourceStatus,
  HealthResponse,
  ReindexResponse,
  APIError,
} from '@/types/api'

// ============================================================================
// Configuration
// ============================================================================

const API_BASE = '/api'

/**
 * Custom error class for API errors
 */
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public detail?: string
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

/**
 * Generic fetch wrapper with error handling
 */
async function apiFetch<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE}${endpoint}`

  const response = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  })

  if (!response.ok) {
    let detail: string | undefined
    try {
      const errorData = (await response.json()) as APIError
      detail = errorData.detail
    } catch {
      // Response body not JSON
    }
    throw new ApiError(
      detail || `API error: ${response.status} ${response.statusText}`,
      response.status,
      detail
    )
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return undefined as T
  }

  return response.json() as Promise<T>
}

// ============================================================================
// Health & Status
// ============================================================================

/**
 * Check API health status
 */
export async function getHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>('/health')
}

/**
 * Get indexing status for all sources
 */
export async function getStatus(): Promise<SourceStatus[]> {
  return apiFetch<SourceStatus[]>('/status')
}

// ============================================================================
// Sources CRUD
// ============================================================================

/**
 * Get all configured sources
 */
export async function getSources(): Promise<Source[]> {
  return apiFetch<Source[]>('/sources')
}

/**
 * Get a single source by ID
 */
export async function getSource(id: string): Promise<Source> {
  return apiFetch<Source>(`/sources/${encodeURIComponent(id)}`)
}

/**
 * Create a new source
 */
export async function createSource(data: SourceCreate): Promise<Source> {
  return apiFetch<Source>('/sources', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

/**
 * Update an existing source
 */
export async function updateSource(
  id: string,
  data: SourceUpdate
): Promise<Source> {
  return apiFetch<Source>(`/sources/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
}

/**
 * Delete a source
 */
export async function deleteSource(id: string): Promise<void> {
  return apiFetch<void>(`/sources/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })
}

/**
 * Trigger reindex for a source
 */
export async function reindexSource(id: string): Promise<ReindexResponse> {
  return apiFetch<ReindexResponse>(
    `/sources/${encodeURIComponent(id)}/reindex`,
    {
      method: 'POST',
    }
  )
}

// ============================================================================
// Search
// ============================================================================

/**
 * Execute a search query
 */
export async function searchDocuments(
  query: SearchQuery
): Promise<SearchResponse> {
  return apiFetch<SearchResponse>('/search', {
    method: 'POST',
    body: JSON.stringify(query),
  })
}

// ============================================================================
// Query Keys for TanStack Query
// ============================================================================

/**
 * Query key factory for consistent cache keys
 */
export const queryKeys = {
  health: ['health'] as const,
  status: ['status'] as const,
  sources: ['sources'] as const,
  source: (id: string) => ['sources', id] as const,
  search: (query: SearchQuery) => ['search', query] as const,
}
