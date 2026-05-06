// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { useContext } from 'react'
import { ThemeContext } from '@/contexts/ThemeContextValue'

export function useTheme() {
  const context = useContext(ThemeContext)
  if (context === undefined) {
    throw new Error('useTheme must be used within a ThemeProvider')
  }
  return context
}
