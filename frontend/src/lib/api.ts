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
  SourcePathTestRequest,
  SourcePathTestResponse,
  SourceBrowseRequest,
  SourceBrowseResponse,
  SearchQuery,
  SearchResponse,
  StatusResponse,
  HealthResponse,
  ReindexResponse,
  AuthStatusResponse,
  SetupRequest,
  LoginRequest,
  AuthResponse,
  User,
  AppSettings,
  AppSettingsUpdate,
  Agent, AgentDetails, AgentEnrollment, ProcessingMode,
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

// FastAPI details come in three shapes: a string, our {code, message} objects,
// or a 422 validation array of {msg, ...}
function errorDetailMessage(detail: unknown): string | undefined {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((item) => (item && typeof item === 'object' && 'msg' in item ? String(item.msg) : ''))
      .filter(Boolean)
    return msgs.length ? msgs.join('; ') : undefined
  }
  if (detail && typeof detail === 'object' && 'message' in detail) {
    return String((detail as { message: unknown }).message)
  }
  return undefined
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
      const errorData = (await response.json()) as { detail?: unknown }
      detail = errorDetailMessage(errorData.detail)
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

export interface SourcePathPollOptions {
  pollIntervalMs?: number
  pollTimeoutMs?: number
}

const ACTIVE_PATH_TEST_STATUSES = new Set(['pending', 'claimed', 'running', 'cancelling'])
const ACTIVE_BROWSE_STATUSES = new Set(['pending', 'claimed', 'running', 'cancelling'])

function wait(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const onAbort = () => {
      window.clearTimeout(timer)
      resolve()
    }
    const timer = window.setTimeout(() => {
      signal.removeEventListener('abort', onAbort)
      resolve()
    }, milliseconds)
    signal.addEventListener('abort', onAbort, { once: true })
  })
}

export async function getSourcePathTestResult(
  jobId: string,
  signal?: AbortSignal,
): Promise<SourcePathTestResponse> {
  return apiFetch<SourcePathTestResponse>(`/sources/test-path/${encodeURIComponent(jobId)}`, { signal })
}

export async function pollSourcePathTest(
  jobId: string,
  options: SourcePathPollOptions = {},
): Promise<SourcePathTestResponse> {
  const timeoutMs = options.pollTimeoutMs ?? 20_000
  let intervalMs = Math.max(options.pollIntervalMs ?? 300, 0)
  const deadline = Date.now() + timeoutMs
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), Math.max(timeoutMs, 0))

  try {
    while (!controller.signal.aborted) {
      const remainingMs = deadline - Date.now()
      if (remainingMs <= 0) break
      await wait(Math.min(intervalMs, remainingMs), controller.signal)
      if (controller.signal.aborted || Date.now() >= deadline) break
      const result = await getSourcePathTestResult(jobId, controller.signal)
      if (!result.status || !ACTIVE_PATH_TEST_STATUSES.has(result.status)) return result
      intervalMs = Math.min(Math.max(intervalMs * 1.5, 100), 1_500)
    }
  } catch (error) {
    if (!controller.signal.aborted) throw error
  } finally {
    window.clearTimeout(timeout)
  }
  throw new ApiError('Remote path validation timed out.', 408, 'remote_path_validation_timeout')
}

/**
 * Test a candidate source path before saving
 */
export async function testSourcePath(
  data: SourcePathTestRequest,
  options: SourcePathPollOptions = {},
): Promise<SourcePathTestResponse> {
  const result = await apiFetch<SourcePathTestResponse>('/sources/test-path', {
    method: 'POST',
    body: JSON.stringify(data),
  })
  if (!result.job_id || !result.status || !ACTIVE_PATH_TEST_STATUSES.has(result.status)) {
    return result
  }
  return pollSourcePathTest(result.job_id, options)
}

export async function getSourceDirectoryBrowseResult(jobId: string, signal?: AbortSignal): Promise<SourceBrowseResponse> {
  return apiFetch<SourceBrowseResponse>(`/sources/browse/${encodeURIComponent(jobId)}`, { signal })
}

export async function pollSourceDirectoryBrowse(jobId: string, options: SourcePathPollOptions = {}): Promise<SourceBrowseResponse> {
  const timeoutMs = options.pollTimeoutMs ?? 20_000
  let intervalMs = Math.max(options.pollIntervalMs ?? 300, 0)
  const deadline = Date.now() + timeoutMs
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), Math.max(timeoutMs, 0))
  try {
    while (!controller.signal.aborted) {
      const remainingMs = deadline - Date.now()
      if (remainingMs <= 0) break
      await wait(Math.min(intervalMs, remainingMs), controller.signal)
      if (controller.signal.aborted || Date.now() >= deadline) break
      const result = await getSourceDirectoryBrowseResult(jobId, controller.signal)
      if (!ACTIVE_BROWSE_STATUSES.has(result.status)) return result
      intervalMs = Math.min(Math.max(intervalMs * 1.5, 100), 1_500)
    }
  } catch (error) {
    if (!controller.signal.aborted) throw error
  } finally {
    window.clearTimeout(timeout)
  }
  throw new ApiError('Remote directory browse timed out.', 408, 'remote_directory_browse_timeout')
}

export async function browseSourceDirectory(data: SourceBrowseRequest, options: SourcePathPollOptions = {}): Promise<SourceBrowseResponse> {
  const result = await apiFetch<SourceBrowseResponse>('/sources/browse', { method: 'POST', body: JSON.stringify(data) })
  if (!ACTIVE_BROWSE_STATUSES.has(result.status)) return result
  return pollSourceDirectoryBrowse(result.job_id, options)
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

/**
 * Clean failed file entries for a source
 */
export async function clearStaleFailed(id: string): Promise<{ cleared: number; reindexed: number; still_failed: number; skipped: number }> {
  return apiFetch<{ cleared: number; reindexed: number; still_failed: number; skipped: number }>(`/sources/${encodeURIComponent(id)}/clear-stale`, { method: 'POST' })
}

// ============================================================================
// App Settings
// ============================================================================

export async function getAppSettings(): Promise<AppSettings> {
  return apiFetch<AppSettings>('/settings')
}

export async function updateAppSettings(data: AppSettingsUpdate): Promise<AppSettings> {
  return apiFetch<AppSettings>('/settings', {
    method: 'PUT',
    body: JSON.stringify(data),
  })
}

export async function getAgents(): Promise<Agent[]> { return apiFetch<Agent[]>('/agents') }
export async function getAgent(id: string): Promise<AgentDetails> { return apiFetch<AgentDetails>(`/agents/${encodeURIComponent(id)}`) }
export async function createAgentEnrollment(): Promise<AgentEnrollment> { return apiFetch<AgentEnrollment>('/agents/enrollments', { method: 'POST' }) }
export async function approveAgent(id: string): Promise<Agent> { return apiFetch<Agent>(`/agents/${encodeURIComponent(id)}/approve`, { method: 'POST' }) }
export async function disableAgent(id: string): Promise<Agent> { return apiFetch<Agent>(`/agents/${encodeURIComponent(id)}/disable`, { method: 'POST' }) }
export async function revokeAgent(id: string, deleteSources?: boolean): Promise<Agent> {
  const suffix = deleteSources ? '?delete_sources=true' : ''
  return apiFetch<Agent>(`/agents/${encodeURIComponent(id)}/revoke${suffix}`, { method: 'POST' })
}
export async function updateAgentProcessingMode(id: string, default_processing_mode: ProcessingMode): Promise<Agent> {
  return apiFetch<Agent>(`/agents/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify({ default_processing_mode }) })
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

export function getDocumentPreviewUrl(id: string): string {
  return `${API_BASE}/documents/${encodeURIComponent(id)}/preview`
}

export async function getDocumentPreviewBlob(id: string): Promise<Blob> {
  const token = getToken()
  const response = await fetch(getDocumentPreviewUrl(id), {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })

  if (!response.ok) {
    if (response.status === 401) {
      clearToken()
      window.location.href = '/login'
      throw new ApiError('Session expired', 401)
    }

    let detail = `Preview unavailable (${response.status})`
    try {
      const data = await response.json()
      detail = errorDetailMessage(data.detail) ?? detail
    } catch {
      // Response body not JSON
    }
    throw new ApiError(detail, response.status, detail)
  }

  return response.blob()
}

interface DocumentDownloadLink {
  url: string
  expires_in: number
  filename: string
}

export async function getDocumentDownloadLink(id: string): Promise<DocumentDownloadLink> {
  return apiFetch<DocumentDownloadLink>(`/documents/${encodeURIComponent(id)}/download-link`, {
    method: 'POST',
  })
}

// Same order as the backend markdown extractor: utf-8, then latin-1 (the browser's
// "latin1" is really windows-1252; only differs for 0x80-0x9F)
export function decodeText(buffer: ArrayBuffer): string {
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(buffer)
  } catch {
    return new TextDecoder('latin1').decode(buffer)
  }
}

/**
 * Original file contents, via a short-lived download link. The link carries its
 * own token, so a 401 here is about the link, not the login session.
 */
export async function getDocumentRawText(id: string): Promise<string> {
  const link = await getDocumentDownloadLink(id)

  let response: Response
  try {
    response = await fetch(link.url)
  } catch {
    throw new ApiError("Couldn't reach the server to load the original file", 0)
  }

  if (!response.ok) {
    let detail = `Could not load the original file (${response.status})`
    try {
      const data = await response.json()
      detail = errorDetailMessage(data.detail) ?? detail
    } catch {
      // Response body not JSON
    }
    throw new ApiError(detail, response.status, detail)
  }

  return decodeText(await response.arrayBuffer())
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
  documentRaw: (id: string, modifiedAt: number) => ['documents', id, 'raw', modifiedAt] as const,
  appSettings: ['appSettings'] as const,
  authStatus: ['authStatus'] as const,
  currentUser: ['currentUser'] as const,
  agents: ['agents'] as const,
  agent: (id: string) => ['agents', id] as const,
}
