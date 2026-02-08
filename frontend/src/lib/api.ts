// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

/**
 * API client for OneSearch backend
 * All API calls go through these typed functions
 */

import type {
  Document,
  Source,
  SourceCreate,
  SourceUpdate,
  SearchQuery,
  SearchResponse,
  StatusResponse,
  HealthResponse,
  ReindexResponse,
  APIError,
  AuthStatusResponse,
  SetupRequest,
  LoginRequest,
  AuthResponse,
  User,
} from '@/types/api'

// ============================================================================
// Configuration
// ============================================================================

const API_BASE = '/api'

// Token storage key
const TOKEN_KEY = 'onesearch_token'

/**
 * Get stored auth token
 */
export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

/**
 * Store auth token
 */
export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

/**
 * Clear auth token
 */
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

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
  options: RequestInit = {},
  includeAuth: boolean = true
): Promise<T> {
  const url = `${API_BASE}${endpoint}`

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  }

  // Add auth header if token exists and includeAuth is true
  if (includeAuth) {
    const token = getToken()
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }
  }

  const response = await fetch(url, {
    ...options,
    headers,
  })

  if (!response.ok) {
    // Expired or invalid token — clear and redirect to login
    if (response.status === 401 && includeAuth) {
      clearToken()
      window.location.href = '/login'
      throw new ApiError('Session expired', 401)
    }

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
export async function getStatus(): Promise<StatusResponse> {
  return apiFetch<StatusResponse>('/status')
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
 * @param id - Source ID
 * @param full - If true, wipe and rebuild entire index (for migration/corruption)
 */
export async function reindexSource(id: string, full: boolean = false): Promise<ReindexResponse> {
  const params = full ? '?full=true' : ''
  return apiFetch<ReindexResponse>(
    `/sources/${encodeURIComponent(id)}/reindex${params}`,
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

/**
 * Get a single document by ID
 */
export async function getDocument(id: string): Promise<Document> {
  return apiFetch<Document>(`/documents/${encodeURIComponent(id)}`)
}

// ============================================================================
// Authentication
// ============================================================================

/**
 * Check if setup is required (no users exist)
 */
export async function getAuthStatus(): Promise<AuthStatusResponse> {
  return apiFetch<AuthStatusResponse>('/auth/status', {}, false)
}

/**
 * Initial setup - create first admin user
 */
export async function setup(data: SetupRequest): Promise<AuthResponse> {
  return apiFetch<AuthResponse>('/auth/setup', {
    method: 'POST',
    body: JSON.stringify(data),
  }, false)
}

/**
 * Login with username and password
 */
export async function login(data: LoginRequest): Promise<AuthResponse> {
  return apiFetch<AuthResponse>('/auth/login', {
    method: 'POST',
    body: JSON.stringify(data),
  }, false)
}

/**
 * Logout current user
 */
export async function logout(): Promise<void> {
  await apiFetch<{ message: string }>('/auth/logout', {
    method: 'POST',
  })
  clearToken()
}

/**
 * Get current user info
 */
export async function getCurrentUser(): Promise<User> {
  return apiFetch<User>('/auth/me')
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
  document: (id: string) => ['documents', id] as const,
  authStatus: ['authStatus'] as const,
  currentUser: ['currentUser'] as const,
}
