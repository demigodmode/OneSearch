// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { useContext } from 'react'
import { SearchSettingsContext } from '@/contexts/SearchSettingsContextValue'

export function useSearchSettings() {
  const context = useContext(SearchSettingsContext)
  if (context === undefined) {
    throw new Error('useSearchSettings must be used within a SearchSettingsProvider')
  }
  return context
}
