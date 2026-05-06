// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import {
  useState,
  useCallback,
  type ReactNode,
} from 'react'
import { ThemeContext } from '@/contexts/ThemeContextValue'
import { DEFAULT_PRESET, type ThemePreset } from '@/contexts/theme'

const STORAGE_KEY = 'onesearch-theme'

function applyTheme(preset: ThemePreset) {
  const r = document.documentElement.style
  r.setProperty('--brand-h', String(preset.brandH))
  r.setProperty('--brand-s', preset.brandS + '%')
  r.setProperty('--brand-l', preset.brandL + '%')
  r.setProperty('--bg-h', String(preset.bgH))
}

function saveTheme(preset: ThemePreset) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(preset))
  } catch {
    // localStorage can be unavailable in private browsing or restricted embeds.
  }
}

function loadTheme(): ThemePreset | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (typeof parsed.brandH !== 'number') return null
    return parsed as ThemePreset
  } catch {
    return null
  }
}

function getInitialThemeState() {
  const saved = loadTheme()
  const theme = saved ?? DEFAULT_PRESET
  return {
    theme,
    customHue: theme.id === 'custom' ? theme.brandH : null,
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [initialThemeState] = useState(getInitialThemeState)
  const [theme, setTheme] = useState<ThemePreset>(initialThemeState.theme)
  const [customHue, setCustomHueState] = useState<number | null>(initialThemeState.customHue)

  const setPreset = useCallback((preset: ThemePreset) => {
    setTheme(preset)
    setCustomHueState(null)
    applyTheme(preset)
    saveTheme(preset)
  }, [])

  const setCustomHue = useCallback((hue: number) => {
    const custom: ThemePreset = {
      id: 'custom',
      name: 'Custom',
      brandH: hue,
      brandS: 92,
      brandL: 58,
      bgH: hue,
    }
    setTheme(custom)
    setCustomHueState(hue)
    applyTheme(custom)
    saveTheme(custom)
  }, [])

  return (
    <ThemeContext.Provider value={{ theme, customHue, setPreset, setCustomHue }}>
      {children}
    </ThemeContext.Provider>
  )
}
