// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { createContext } from 'react'
import type { ThemeMode, ThemePreset } from '@/contexts/theme'

export interface ThemeContextType {
  theme: ThemePreset
  themeMode: ThemeMode
  customHue: number | null  // null = preset active, non-null = slider active
  setPreset: (preset: ThemePreset) => void
  setCustomHue: (hue: number) => void
  setThemeMode: (mode: ThemeMode) => void
}

export const ThemeContext = createContext<ThemeContextType | undefined>(undefined)
