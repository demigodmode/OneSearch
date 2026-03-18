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

export interface ThemePreset {
  id: string
  name: string
  brandH: number
  brandS: number  // plain number, % appended when writing to CSS
  brandL: number  // plain number, % appended when writing to CSS
  bgH: number
}

interface ThemeContextType {
  theme: ThemePreset
  customHue: number | null  // null = preset active, non-null = slider active
  setPreset: (preset: ThemePreset) => void
  setCustomHue: (hue: number) => void
}

export const PRESETS: ThemePreset[] = [
  { id: 'amber',  name: 'Amber',  brandH: 38,  brandS: 92, brandL: 58, bgH: 28  },
  { id: 'indigo', name: 'Indigo', brandH: 248, brandS: 70, brandL: 65, bgH: 242 },
  { id: 'cyan',   name: 'Cyan',   brandH: 192, brandS: 78, brandL: 50, bgH: 200 },
  { id: 'teal',   name: 'Teal',   brandH: 174, brandS: 66, brandL: 44, bgH: 180 },
  { id: 'rose',   name: 'Rose',   brandH: 350, brandS: 89, brandL: 60, bgH: 340 },
]

const DEFAULT_PRESET = PRESETS[0] // Amber
const STORAGE_KEY = 'onesearch-theme'

const ThemeContext = createContext<ThemeContextType | undefined>(undefined)

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
  } catch (e) {}
}

function loadTheme(): ThemePreset | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (typeof parsed.brandH !== 'number') return null
    return parsed as ThemePreset
  } catch (e) {
    return null
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<ThemePreset>(DEFAULT_PRESET)
  const [customHue, setCustomHueState] = useState<number | null>(null)

  // Restore saved theme on mount
  useEffect(() => {
    const saved = loadTheme()
    if (saved) {
      setTheme(saved)
      if (saved.id === 'custom') {
        setCustomHueState(saved.brandH)
      }
      // CSS vars already applied by anti-FOUC script, but sync React state
    }
  }, [])

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

export function useTheme() {
  const context = useContext(ThemeContext)
  if (context === undefined) {
    throw new Error('useTheme must be used within a ThemeProvider')
  }
  return context
}
