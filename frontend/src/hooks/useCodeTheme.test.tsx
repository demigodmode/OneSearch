import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { oneDark, oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { useCodeTheme } from './useCodeTheme'

const codeKey = 'code[class*="language-"]'

afterEach(() => {
  document.documentElement.classList.remove('light')
})

describe('useCodeTheme', () => {
  it('uses oneDark by default and oneLight when <html> has .light', async () => {
    const { result } = renderHook(() => useCodeTheme())
    expect(result.current[codeKey].color).toBe(oneDark[codeKey].color)

    await act(async () => {
      document.documentElement.classList.add('light')
    })
    expect(result.current[codeKey].color).toBe(oneLight[codeKey].color)

    await act(async () => {
      document.documentElement.classList.remove('light')
    })
    expect(result.current[codeKey].color).toBe(oneDark[codeKey].color)
  })

  it('drops the per-line code background so it does not stripe over the card', () => {
    document.documentElement.classList.add('light')
    const { result } = renderHook(() => useCodeTheme())
    expect(result.current[codeKey].background).toBe('transparent')
  })
})
