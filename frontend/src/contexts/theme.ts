// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

export type ThemeMode = 'system' | 'light' | 'dark'

export interface ThemePreset {
  id: string
  name: string
  brandH: number
  brandS: number  // plain number, % appended when writing to CSS
  brandL: number  // plain number, % appended when writing to CSS
  bgH: number
}

export const PRESETS: ThemePreset[] = [
  { id: 'amber',  name: 'Amber',  brandH: 38,  brandS: 92, brandL: 58, bgH: 28  },
  { id: 'indigo', name: 'Indigo', brandH: 248, brandS: 70, brandL: 65, bgH: 242 },
  { id: 'cyan',   name: 'Cyan',   brandH: 192, brandS: 78, brandL: 50, bgH: 200 },
  { id: 'teal',   name: 'Teal',   brandH: 174, brandS: 66, brandL: 44, bgH: 180 },
  { id: 'rose',   name: 'Rose',   brandH: 350, brandS: 89, brandL: 60, bgH: 340 },
]

export const DEFAULT_PRESET = PRESETS[0] // Amber
