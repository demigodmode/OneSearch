// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from 'react'

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

const DEFAULT_SETTINGS: SearchSettings = {
  resultsPerPage: 20,
  sortOrder: 'relevance',
  snippetLength: 'medium',
  density: 'comfortable',
  showPath: true,
  showSize: true,
  showDate: true,
}

const STORAGE_KEY = 'onesearch-search-settings'

/**
 * User search preferences with localStorage persistence.
 * Settings load on mount and save on each update.
 * Follows the same pattern as ThemeContext.
 */
interface SearchSettingsContextType {
  settings: SearchSettings
  updateSettings: (partial: Partial<SearchSettings>) => void
}

const SearchSettingsContext = createContext<SearchSettingsContextType | undefined>(undefined)

function loadSettings(): SearchSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return DEFAULT_SETTINGS
    const parsed = JSON.parse(raw)
    return { ...DEFAULT_SETTINGS, ...parsed }
  } catch {
    return DEFAULT_SETTINGS
  }
}

function saveSettings(settings: SearchSettings) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings))
  } catch {}
}

export function SearchSettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<SearchSettings>(DEFAULT_SETTINGS)

  useEffect(() => {
    setSettings(loadSettings())
  }, [])

  const updateSettings = useCallback((partial: Partial<SearchSettings>) => {
    setSettings(prev => {
      const next = { ...prev, ...partial }
      saveSettings(next)
      return next
    })
  }, [])

  return (
    <SearchSettingsContext.Provider value={{ settings, updateSettings }}>
      {children}
    </SearchSettingsContext.Provider>
  )
}

export function useSearchSettings() {
  const context = useContext(SearchSettingsContext)
  if (context === undefined) {
    throw new Error('useSearchSettings must be used within a SearchSettingsProvider')
  }
  return context
}
