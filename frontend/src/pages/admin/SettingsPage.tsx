// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { useTheme, PRESETS, type ThemePreset } from '@/contexts/ThemeContext'
import { useSearchSettings, type SearchSettings } from '@/contexts/SearchSettingsContext'
import { cn } from '@/lib/utils'

export default function SettingsPage() {
  const { theme, customHue, setPreset, setCustomHue } = useTheme()
  const { settings, updateSettings } = useSearchSettings()

  return (
    <div className="animate-fade-in">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-foreground tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground mt-1">Customize your OneSearch instance</p>
      </div>

      <div className="space-y-6">
        <AppearanceSection
          theme={theme}
          customHue={customHue}
          onPreset={setPreset}
          onCustomHue={setCustomHue}
        />

        <SearchSection settings={settings} onUpdate={updateSettings} />
      </div>
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

// Segmented button group helper
function SegmentedButtons<T extends string | number>({
  options,
  value,
  onChange,
  ariaLabel,
}: {
  options: { value: T; label: string }[]
  value: T
  onChange: (v: T) => void
  ariaLabel: string
}) {
  return (
    <div className="inline-flex rounded-lg border border-border overflow-hidden" role="radiogroup" aria-label={ariaLabel}>
      {options.map((opt) => (
        <button
          key={String(opt.value)}
          role="radio"
          aria-checked={value === opt.value}
          onClick={() => onChange(opt.value)}
          className={cn(
            'px-3 py-1.5 text-xs font-medium transition-colors',
            value === opt.value
              ? 'bg-brand text-brand-foreground'
              : 'bg-card text-muted-foreground hover:text-foreground hover:bg-secondary'
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label className="flex items-center justify-between gap-3 cursor-pointer">
      <span className="text-sm text-foreground">{label}</span>
      <button
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cn(
          'relative w-9 h-5 rounded-full transition-colors',
          checked ? 'bg-brand' : 'bg-secondary'
        )}
      >
        <span
          className={cn(
            'absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform',
            checked && 'translate-x-4'
          )}
        />
      </button>
    </label>
  )
}

interface SearchSectionProps {
  settings: SearchSettings
  onUpdate: (partial: Partial<SearchSettings>) => void
}

function SearchSection({ settings, onUpdate }: SearchSectionProps) {
  const isMac = /Mac|iPod|iPhone|iPad/.test(navigator.platform)

  return (
    <section className="bg-card border border-border rounded-lg p-6 max-w-lg">
      <h2 className="text-sm font-semibold text-foreground uppercase tracking-wider mb-4">
        Search
      </h2>

      <div className="space-y-5">
        {/* Results per page */}
        <div>
          <p className="text-xs text-muted-foreground mb-2">Results per page</p>
          <SegmentedButtons
            options={[
              { value: 10 as const, label: '10' },
              { value: 25 as const, label: '25' },
              { value: 50 as const, label: '50' },
            ]}
            value={settings.resultsPerPage}
            onChange={(v) => onUpdate({ resultsPerPage: v })}
            ariaLabel="Results per page"
          />
        </div>

        {/* Sort order */}
        <div>
          <p className="text-xs text-muted-foreground mb-2">Default sort</p>
          <select
            value={settings.sortOrder}
            onChange={(e) => onUpdate({ sortOrder: e.target.value as SearchSettings['sortOrder'] })}
            className="px-3 py-2 bg-card border border-border rounded-lg text-sm text-foreground w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ring-offset-background"
          >
            <option value="relevance">Relevance</option>
            <option value="modified_at:desc">Newest first</option>
            <option value="modified_at:asc">Oldest first</option>
            <option value="size_bytes:desc">Largest first</option>
            <option value="basename:asc">Name (A-Z)</option>
          </select>
        </div>

        {/* Snippet length */}
        <div>
          <p className="text-xs text-muted-foreground mb-2">Snippet length</p>
          <SegmentedButtons
            options={[
              { value: 'short' as const, label: 'Short' },
              { value: 'medium' as const, label: 'Medium' },
              { value: 'long' as const, label: 'Long' },
            ]}
            value={settings.snippetLength}
            onChange={(v) => onUpdate({ snippetLength: v })}
            ariaLabel="Snippet length"
          />
        </div>

        {/* Density */}
        <div>
          <p className="text-xs text-muted-foreground mb-2">Display density</p>
          <SegmentedButtons
            options={[
              { value: 'compact' as const, label: 'Compact' },
              { value: 'comfortable' as const, label: 'Comfortable' },
              { value: 'spacious' as const, label: 'Spacious' },
            ]}
            value={settings.density}
            onChange={(v) => onUpdate({ density: v })}
            ariaLabel="Display density"
          />
        </div>

        {/* Metadata toggles */}
        <div>
          <p className="text-xs text-muted-foreground mb-3">Visible metadata</p>
          <div className="space-y-3">
            <Toggle label="File path" checked={settings.showPath} onChange={(v) => onUpdate({ showPath: v })} />
            <Toggle label="File size" checked={settings.showSize} onChange={(v) => onUpdate({ showSize: v })} />
            <Toggle label="Modified date" checked={settings.showDate} onChange={(v) => onUpdate({ showDate: v })} />
          </div>
        </div>

        {/* Keyboard shortcuts info */}
        <div>
          <p className="text-xs text-muted-foreground mb-2">Keyboard shortcuts</p>
          <div className="grid grid-cols-2 gap-y-2 text-xs">
            <span className="text-muted-foreground">Focus search</span>
            <span className="text-foreground font-mono">{isMac ? '⌘' : 'Ctrl'}+K or /</span>
            <span className="text-muted-foreground">Clear / blur</span>
            <span className="text-foreground font-mono">Esc</span>
            <span className="text-muted-foreground">Navigate results</span>
            <span className="text-foreground font-mono">↑ ↓</span>
            <span className="text-muted-foreground">Open result</span>
            <span className="text-foreground font-mono">Enter</span>
          </div>
        </div>
      </div>
    </section>
  )
}
