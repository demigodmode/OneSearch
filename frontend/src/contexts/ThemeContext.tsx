// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import {
  useState,
  useCallback,
  useEffect,
  type ReactNode,
} from 'react'
import { ThemeContext } from '@/contexts/ThemeContextValue'
import { DEFAULT_PRESET, type ThemeMode, type ThemePreset } from '@/contexts/theme'

const STORAGE_KEY = 'onesearch-theme'
const MODE_STORAGE_KEY = 'onesearch-theme-mode'

function applyTheme(preset: ThemePreset) {
  const r = document.documentElement.style
  r.setProperty('--brand-h', String(preset.brandH))
  r.setProperty('--brand-s', preset.brandS + '%')
  r.setProperty('--brand-l', preset.brandL + '%')
  r.setProperty('--bg-h', String(preset.bgH))
}

function applyThemeMode(mode: ThemeMode) {
  const prefersLight = window.matchMedia?.('(prefers-color-scheme: light)').matches ?? false
  const useLight = mode === 'light' || (mode === 'system' && prefersLight)
  document.documentElement.classList.toggle('light', useLight)
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

function saveThemeMode(mode: ThemeMode) {
  try {
    localStorage.setItem(MODE_STORAGE_KEY, mode)
  } catch {
    // localStorage can be unavailable in private browsing or restricted embeds.
  }
}

function loadThemeMode(): ThemeMode {
  try {
    const raw = localStorage.getItem(MODE_STORAGE_KEY)
    if (raw === 'light' || raw === 'dark' || raw === 'system') return raw
  } catch {
    // localStorage can be unavailable in private browsing or restricted embeds.
  }
  return 'system'
}

function getInitialThemeState() {
  const saved = loadTheme()
  const theme = saved ?? DEFAULT_PRESET
  return {
    theme,
    themeMode: loadThemeMode(),
    customHue: theme.id === 'custom' ? theme.brandH : null,
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [initialThemeState] = useState(getInitialThemeState)
  const [theme, setTheme] = useState<ThemePreset>(initialThemeState.theme)
  const [themeMode, setThemeModeState] = useState<ThemeMode>(initialThemeState.themeMode)
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

  const setThemeMode = useCallback((mode: ThemeMode) => {
    setThemeModeState(mode)
    applyThemeMode(mode)
    saveThemeMode(mode)
  }, [])

  useEffect(() => {
    applyTheme(theme)
    applyThemeMode(themeMode)
  }, [theme, themeMode])

  useEffect(() => {
    if (themeMode !== 'system') return
    const media = window.matchMedia?.('(prefers-color-scheme: light)')
    if (!media) return

    const handleChange = () => applyThemeMode('system')
    media.addEventListener('change', handleChange)
    return () => media.removeEventListener('change', handleChange)
  }, [themeMode])

  return (
    <ThemeContext.Provider value={{ theme, themeMode, customHue, setPreset, setCustomHue, setThemeMode }}>
      {children}
    </ThemeContext.Provider>
  )
}
