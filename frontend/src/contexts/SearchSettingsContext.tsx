// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import {
  useState,
  useCallback,
  type ReactNode,
} from 'react'
import { SearchSettingsContext } from '@/contexts/SearchSettingsContextValue'
import { DEFAULT_SETTINGS, type SearchSettings } from '@/contexts/searchSettings'

const STORAGE_KEY = 'onesearch-search-settings'

/**
 * User search preferences with localStorage persistence.
 * Settings load during state initialization and save on each update.
 */
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
  } catch {
    // localStorage can be unavailable in private browsing or restricted embeds.
  }
}

export function SearchSettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<SearchSettings>(() => loadSettings())

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
