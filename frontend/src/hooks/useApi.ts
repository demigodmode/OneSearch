// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

/**
 * TanStack Query hooks for API data fetching
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  getSources,
  getSource,
  createSource,
  updateSource,
  testSourcePath,
  deleteSource,
  reindexSource,
  searchDocuments,
  getDocument,
  getStatus,
  getHealth,
  getAppSettings,
  updateAppSettings,
  queryKeys,
  getAgents, getAgent, createAgentEnrollment, approveAgent, disableAgent, revokeAgent, updateAgentProcessingMode,
} from '@/lib/api'
import type {
  SourceCreate,
  SourceUpdate,
  SearchQuery,
  AppSettingsUpdate,
  ProcessingMode,
  SourcePathTestRequest,
} from '@/types/api'

// ============================================================================
// Health & Status Hooks
// ============================================================================

/**
 * Hook for health check
 */
export function useHealth() {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: getHealth,
    refetchInterval: 30000, // Refetch every 30 seconds
    staleTime: 10000,
  })
}

/**
 * Hook for indexing status
 */
export function useStatus() {
  return useQuery({
    queryKey: queryKeys.status,
    queryFn: getStatus,
    refetchInterval: 30000,
    staleTime: 10000,
  })
}

// ============================================================================
// App Settings Hooks
// ============================================================================

export function useAppSettings() {
  return useQuery({
    queryKey: queryKeys.appSettings,
    queryFn: getAppSettings,
  })
}

export function useUpdateAppSettings() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: AppSettingsUpdate) => updateAppSettings(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.appSettings })
      queryClient.invalidateQueries({ queryKey: queryKeys.sources })
    },
  })
}

export function useAgents() { return useQuery({ queryKey: queryKeys.agents, queryFn: getAgents }) }
export function useAgent(id: string) { return useQuery({ queryKey: queryKeys.agent(id), queryFn: () => getAgent(id), enabled: !!id }) }
function useAgentAction<T>(mutationFn: (value: T) => Promise<unknown>) {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn, onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.agents }) })
}
export function useCreateAgentEnrollment() {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: createAgentEnrollment, onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.agents }) })
}
export function useApproveAgent() { return useAgentAction(approveAgent) }
export function useDisableAgent() { return useAgentAction(disableAgent) }
export function useRevokeAgent() { return useAgentAction(revokeAgent) }
export function useUpdateAgentProcessingMode() { return useAgentAction(({ id, mode }: { id: string; mode: ProcessingMode }) => updateAgentProcessingMode(id, mode)) }

// ============================================================================
// Sources Hooks
// ============================================================================

/**
 * Hook to fetch all sources
 */
export function useSources() {
  return useQuery({
    queryKey: queryKeys.sources,
    queryFn: getSources,
  })
}

/**
 * Hook to fetch a single source
 */
export function useSource(id: string) {
  return useQuery({
    queryKey: queryKeys.source(id),
    queryFn: () => getSource(id),
    enabled: !!id,
  })
}

/**
 * Hook to create a new source
 */
export function useCreateSource() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: SourceCreate) => createSource(data),
    onSuccess: () => {
      // Invalidate sources list to refetch
      queryClient.invalidateQueries({ queryKey: queryKeys.sources })
    },
  })
}

/**
 * Hook to update a source
 */
export function useUpdateSource() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: SourceUpdate }) =>
      updateSource(id, data),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.sources })
      queryClient.invalidateQueries({ queryKey: queryKeys.source(id) })
    },
  })
}

/**
 * Hook to test a source path before saving
 */
export function useTestSourcePath() {
  return useMutation({
    mutationFn: (data: SourcePathTestRequest) => testSourcePath(data),
  })
}

/**
 * Hook to delete a source
 */
export function useDeleteSource() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (id: string) => deleteSource(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.sources })
      queryClient.invalidateQueries({ queryKey: queryKeys.status })
    },
  })
}

/**
 * Hook to trigger reindex
 * @param full - If true, wipe and rebuild entire index
 */
export function useReindexSource() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ id, full = false }: { id: string; full?: boolean }) =>
      reindexSource(id, full),
    onSuccess: () => {
      // Invalidate both sources (for updated_at) and status (for indexing info)
      queryClient.invalidateQueries({ queryKey: queryKeys.sources })
      queryClient.invalidateQueries({ queryKey: queryKeys.status })
    },
  })
}

// ============================================================================
// Search Hook
// ============================================================================

/**
 * Hook for search
 * Only executes when query string is non-empty
 */
export function useSearch(query: SearchQuery) {
  return useQuery({
    queryKey: queryKeys.search(query),
    queryFn: () => searchDocuments(query),
    enabled: query.q.length > 0,
    staleTime: 60000, // Cache search results for 1 minute
  })
}

// ============================================================================
// Document Hook
// ============================================================================

/**
 * Hook to fetch a single document by ID
 */
export function useDocument(id: string) {
  return useQuery({
    queryKey: queryKeys.document(id),
    queryFn: () => getDocument(id),
    enabled: !!id,
    staleTime: 300000, // Cache document for 5 minutes
  })
}
