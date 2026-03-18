// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { useTheme, PRESETS, type ThemePreset } from '@/contexts/ThemeContext'
import { cn } from '@/lib/utils'

export default function SettingsPage() {
  const { theme, customHue, setPreset, setCustomHue } = useTheme()

  return (
    <div className="animate-fade-in">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-foreground tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground mt-1">Customize your OneSearch instance</p>
      </div>

      <AppearanceSection
        theme={theme}
        customHue={customHue}
        onPreset={setPreset}
        onCustomHue={setCustomHue}
      />
    </div>
  )
}

interface AppearanceSectionProps {
  theme: ThemePreset
  customHue: number | null
  onPreset: (preset: ThemePreset) => void
  onCustomHue: (hue: number) => void
}

function AppearanceSection({ theme, customHue, onPreset, onCustomHue }: AppearanceSectionProps) {
  return (
    <section className="bg-card border border-border rounded-lg p-6 max-w-lg">
      <h2 className="text-sm font-semibold text-foreground uppercase tracking-wider mb-4">
        Appearance
      </h2>

      {/* Preset swatches */}
      <div className="mb-6">
        <p className="text-xs text-muted-foreground mb-3">Accent color</p>
        <div className="flex gap-3">
          {PRESETS.map((preset) => {
            const isActive = theme.id === preset.id && customHue === null
            return (
              <button
                key={preset.id}
                onClick={() => onPreset(preset)}
                aria-label={preset.name}
                title={preset.name}
                className={cn(
                  'w-8 h-8 rounded-full transition-all duration-150',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-card',
                  isActive && 'ring-2 ring-offset-2 ring-offset-card scale-110'
                )}
                style={{
                  backgroundColor: `hsl(${preset.brandH} ${preset.brandS}% ${preset.brandL}%)`,
                }}
              />
            )
          })}
        </div>
      </div>

      {/* Custom hue slider */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <p className="text-xs text-muted-foreground">Custom hue</p>
          {customHue !== null && (
            <span className="text-xs font-mono text-muted-foreground">{customHue}°</span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <input
            type="range"
            min={0}
            max={360}
            value={customHue ?? theme.brandH}
            onChange={(e) => onCustomHue(Number(e.target.value))}
            aria-label="Custom accent hue"
            className="flex-1 h-2 rounded-full cursor-pointer"
            style={{
              background: 'linear-gradient(to right, hsl(0 80% 55%), hsl(60 80% 55%), hsl(120 80% 45%), hsl(180 80% 45%), hsl(240 80% 60%), hsl(300 80% 55%), hsl(360 80% 55%))',
              accentColor: `hsl(${customHue ?? theme.brandH} ${theme.brandS}% ${theme.brandL}%)`,
            }}
          />
          {/* Live preview swatch */}
          <div
            className={cn(
              'w-6 h-6 rounded-full shrink-0 ring-1 ring-border',
              customHue !== null && 'ring-2 ring-offset-1 ring-offset-card scale-110'
            )}
            style={{
              backgroundColor: `hsl(${customHue ?? theme.brandH} ${theme.brandS}% ${theme.brandL}%)`,
            }}
          />
        </div>
      </div>
    </section>
  )
}
