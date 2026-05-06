// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { createContext } from 'react'
import type { SearchSettings } from '@/contexts/searchSettings'

export interface SearchSettingsContextType {
  settings: SearchSettings
  updateSettings: (partial: Partial<SearchSettings>) => void
}

export const SearchSettingsContext = createContext<SearchSettingsContextType | undefined>(undefined)
