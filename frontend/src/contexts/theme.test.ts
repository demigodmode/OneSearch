import { describe, expect, it } from 'vitest'
import css from '../index.css?raw'
import { PRESETS } from './theme'

type Hsl = [number, number, number]

const lightDeclarations = css.match(/\.light\s*\{([\s\S]*?)\}/)?.[1]

function declaration(name: string): Hsl {
  const value = lightDeclarations?.match(new RegExp(`${name}:\\s*([\\d.]+)\\s+([\\d.]+)%\\s+([\\d.]+)%`))
  if (!value) throw new Error(`Missing ${name} in .light`)
  return [Number(value[1]), Number(value[2]), Number(value[3])]
}

function luminance([hue, saturation, lightness]: Hsl) {
  const chroma = (1 - Math.abs(2 * lightness / 100 - 1)) * saturation / 100
  const segment = hue / 60
  const second = chroma * (1 - Math.abs(segment % 2 - 1))
  const [red, green, blue] = segment < 1 ? [chroma, second, 0]
    : segment < 2 ? [second, chroma, 0]
      : segment < 3 ? [0, chroma, second]
        : segment < 4 ? [0, second, chroma]
          : segment < 5 ? [second, 0, chroma]
            : [chroma, 0, second]
  const offset = lightness / 100 - chroma / 2
  const linear = [red, green, blue].map(channel => {
    const srgb = channel + offset
    return srgb <= 0.04045 ? srgb / 12.92 : ((srgb + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
}

function contrast(foreground: Hsl, background: Hsl) {
  const [lighter, darker] = [luminance(foreground), luminance(background)].sort((a, b) => b - a)
  return (lighter + 0.05) / (darker + 0.05)
}

describe('light theme brand text', () => {
  it('keeps every preset and saturated hue readable on card and secondary surfaces', () => {
    const strong = lightDeclarations?.match(/--brand-strong:\s*var\(--brand-h\)\s+var\(--brand-s\)\s+([\d.]+)%/)
    if (!strong) throw new Error('Missing --brand-strong in .light')
    const surfaces = [declaration('--card'), declaration('--secondary')]
    const colors: Hsl[] = PRESETS.map(({ brandH, brandS }) => [brandH, brandS, Number(strong[1])])
    for (let hue = 0; hue <= 360; hue++) colors.push([hue, 92, Number(strong[1])])

    for (const color of colors) {
      for (const surface of surfaces) expect(contrast(color, surface)).toBeGreaterThanOrEqual(4.5)
    }
  })
})
