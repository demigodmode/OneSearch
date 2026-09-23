// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { useSyncExternalStore } from 'react'
import { oneDark, oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'

type PrismTheme = typeof oneDark

// Prism themes also paint a background on <code>, which shows up as a stripe
// behind every line on top of our card. The container bg is enough.
function withTransparentCode(theme: PrismTheme): PrismTheme {
  const key = 'code[class*="language-"]'
  return { ...theme, [key]: { ...theme[key], background: 'transparent' } }
}

const darkTheme = withTransparentCode(oneDark)
const lightTheme = withTransparentCode(oneLight)

// ThemeProvider toggles .light on <html> (System mode included), so the class
// is what's actually on screen.
function subscribe(onChange: () => void) {
  const observer = new MutationObserver(onChange)
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
  return () => observer.disconnect()
}

function isLight() {
  return document.documentElement.classList.contains('light')
}

export function useCodeTheme(): PrismTheme {
  const light = useSyncExternalStore(subscribe, isLight, () => false)
  return light ? lightTheme : darkTheme
}
