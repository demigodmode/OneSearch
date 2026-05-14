// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { useEffect, useRef, useState } from 'react'
import { AlertCircle, Loader2 } from 'lucide-react'
import { PRESETS, type ThemePreset } from '@/contexts/theme'
import { useTheme } from '@/contexts/useTheme'
import type { SearchSettings } from '@/contexts/searchSettings'
import { useSearchSettings } from '@/contexts/useSearchSettings'
import { useAppSettings, useUpdateAppSettings } from '@/hooks/useApi'
import type { AppSettings } from '@/types/api'
import { cn } from '@/lib/utils'

type SettingsPanel = 'appearance' | 'file-previews' | 'indexing' | 'search'

export default function SettingsPage() {
  const { theme, customHue, setPreset, setCustomHue } = useTheme()
  const { settings, updateSettings } = useSearchSettings()
  const appSettings = useAppSettings()
  const updateAppSettings = useUpdateAppSettings()
  const [openPanel, setOpenPanel] = useState<SettingsPanel | null>(null)

  const togglePanel = (panel: SettingsPanel) => {
    setOpenPanel((current) => (current === panel ? null : panel))
  }

  return (
    <div className="animate-fade-in">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-foreground tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground mt-1">Customize your OneSearch instance</p>
      </div>

      <div className="grid max-w-lg grid-cols-2 gap-3">
        <SettingsPanelButton label="Appearance" isOpen={openPanel === 'appearance'} onClick={() => togglePanel('appearance')} />
        <SettingsPanelButton label="File Previews" isOpen={openPanel === 'file-previews'} onClick={() => togglePanel('file-previews')} />
        <SettingsPanelButton label="Indexing" isOpen={openPanel === 'indexing'} onClick={() => togglePanel('indexing')} />
        <SettingsPanelButton label="Search" isOpen={openPanel === 'search'} onClick={() => togglePanel('search')} />
      </div>

      <div className="mt-6 space-y-6">
        {openPanel === 'appearance' && (
          <AppearanceSection
            theme={theme}
            customHue={customHue}
            onPreset={setPreset}
            onCustomHue={setCustomHue}
          />
        )}

        {openPanel === 'file-previews' && (
          <FilePreviewsSection
            settings={appSettings.data}
            isLoading={appSettings.isLoading}
            error={appSettings.error}
            isSaving={updateAppSettings.isPending}
            onUpdate={(partial) => updateAppSettings.mutate(partial)}
          />
        )}

        {openPanel === 'indexing' && (
          <IndexingSection
            settings={appSettings.data}
            isLoading={appSettings.isLoading}
            error={appSettings.error}
            isSaving={updateAppSettings.isPending}
            onUpdate={(partial) => updateAppSettings.mutate(partial)}
          />
        )}

        {openPanel === 'search' && <SearchSection settings={settings} onUpdate={updateSettings} />}
      </div>
    </div>
  )
}

function SettingsPanelButton({ label, isOpen, onClick }: { label: string; isOpen: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-expanded={isOpen}
      onClick={onClick}
      className={cn(
        'rounded-lg border px-4 py-3 text-left text-sm font-semibold transition-colors',
        isOpen
          ? 'border-brand bg-brand text-brand-foreground'
          : 'border-border bg-card text-foreground hover:border-brand/60 hover:bg-secondary'
      )}
    >
      {label}
    </button>
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

function NumberSetting({
  label,
  value,
  onChange,
  description,
  min = 0,
}: {
  label: string
  value: number
  onChange: (v: number) => void
  description?: string
  min?: number
}) {
  const [draft, setDraft] = useState(String(value))
  const skipNextBlurCommit = useRef(false)

  useEffect(() => {
    setDraft(String(value))
  }, [value])

  const commit = () => {
    if (skipNextBlurCommit.current) {
      skipNextBlurCommit.current = false
      return
    }
    if (draft.trim() === '') {
      setDraft(String(value))
      return
    }
    const parsed = Number(draft)
    if (!Number.isFinite(parsed) || !Number.isInteger(parsed) || parsed < min) {
      setDraft(String(value))
      return
    }
    if (parsed !== value) onChange(parsed)
  }

  return (
    <label className="block">
      <span className="block text-xs text-muted-foreground mb-2">{label}</span>
      <input
        type="number"
        min={min}
        step={1}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') e.currentTarget.blur()
          if (e.key === 'Escape') {
            skipNextBlurCommit.current = true
            setDraft(String(value))
            e.currentTarget.blur()
          }
        }}
        className="px-3 py-2 bg-card border border-border rounded-lg text-sm text-foreground w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ring-offset-background"
      />
      {description && <span className="block text-xs text-muted-foreground mt-2">{description}</span>}
    </label>
  )
}

function Toggle({
  checked,
  onChange,
  label,
  description,
  disabled = false,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  label: string
  description?: string
  disabled?: boolean
}) {
  return (
    <label className={cn('flex items-start justify-between gap-3', disabled ? 'cursor-not-allowed opacity-60' : 'cursor-pointer')}>
      <span>
        <span className="block text-sm text-foreground">{label}</span>
        {description && <span className="block text-xs text-muted-foreground mt-0.5">{description}</span>}
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cn(
          'relative w-9 h-5 rounded-full transition-colors shrink-0 mt-0.5 disabled:cursor-not-allowed',
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

interface AppSettingsSectionProps {
  settings?: AppSettings
  isLoading: boolean
  error: unknown
  isSaving: boolean
  onUpdate: (partial: Partial<AppSettings>) => void
}

function SettingsLoadingState({ isLoading, error, message }: { isLoading: boolean; error: unknown; message: string }) {
  return (
    <>
      {isLoading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading settings...
        </div>
      )}

      {Boolean(error) && (
        <div className="flex items-start gap-2 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 mt-0.5" />
          <span>{message}</span>
        </div>
      )}
    </>
  )
}

function IndexingSection({ settings, isLoading, error, isSaving, onUpdate }: AppSettingsSectionProps) {
  return (
    <section className="bg-card border border-border rounded-lg p-6 max-w-lg">
      <div className="flex items-center justify-between gap-3 mb-4">
        <h2 className="text-sm font-semibold text-foreground uppercase tracking-wider">Indexing</h2>
        {isSaving && <Loader2 className="h-4 w-4 text-brand animate-spin" />}
      </div>

      <SettingsLoadingState isLoading={isLoading} error={error} message="Unable to load indexing settings." />

      {settings && (
        <div className="space-y-5">
          <div>
            <p className="text-xs text-muted-foreground mb-2">Unsupported files</p>
            <select
              value={settings.unsupported_file_policy}
              onChange={(e) => onUpdate({ unsupported_file_policy: e.target.value as AppSettings['unsupported_file_policy'] })}
              className="px-3 py-2 bg-card border border-border rounded-lg text-sm text-foreground w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ring-offset-background"
            >
              <option value="metadata_only">Index filename/path only</option>
              <option value="skip">Skip unsupported files</option>
            </select>
            <p className="text-xs text-muted-foreground mt-2">
              Metadata-only indexing makes unknown files searchable without extracting content.
            </p>
          </div>

          <div>
            <p className="text-xs text-muted-foreground mb-2">Media metadata extraction</p>
            <SegmentedButtons
              options={[
                { value: 'auto' as const, label: 'Auto' },
                { value: 'off' as const, label: 'Off' },
              ]}
              value={settings.media_metadata_mode}
              onChange={(v) => onUpdate({ media_metadata_mode: v })}
              ariaLabel="Media metadata extraction"
            />
            <p className="text-xs text-muted-foreground mt-2">
              Auto uses ffprobe when available and falls back cleanly when it is not.
            </p>
          </div>

          <Toggle
            label="Index GPS metadata"
            description="Off by default because photo GPS metadata can reveal precise location."
            checked={settings.index_gps_metadata}
            onChange={(v) => onUpdate({ index_gps_metadata: v })}
          />

          <div className="grid grid-cols-1 gap-4 border-t border-border pt-5">
            <NumberSetting
              label="Max media metadata probe size (MB)"
              value={settings.media_probe_max_size_mb}
              min={0}
              onChange={(v) => onUpdate({ media_probe_max_size_mb: v })}
              description="0 means unlimited; ffprobe still has a timeout and falls back cleanly."
            />
            <NumberSetting
              label="Max image/RAW metadata size (MB)"
              value={settings.image_metadata_max_size_mb}
              min={1}
              onChange={(v) => onUpdate({ image_metadata_max_size_mb: v })}
              description="Oversized images still index filename/path metadata."
            />
            <NumberSetting
              label="Max EPUB extraction size (MB)"
              value={settings.epub_extraction_max_size_mb}
              min={1}
              onChange={(v) => onUpdate({ epub_extraction_max_size_mb: v })}
              description="Oversized ebooks are skipped before archive extraction."
            />
            <NumberSetting
              label="Max CBZ comic extraction size (MB)"
              value={settings.comic_extraction_max_size_mb}
              min={1}
              onChange={(v) => onUpdate({ comic_extraction_max_size_mb: v })}
              description="Oversized comics are skipped before archive extraction."
            />
          </div>
        </div>
      )}
    </section>
  )
}

function FilePreviewsSection({ settings, isLoading, error, isSaving, onUpdate }: AppSettingsSectionProps) {
  return (
    <section className="bg-card border border-border rounded-lg p-6 max-w-lg">
      <div className="flex items-center justify-between gap-3 mb-4">
        <h2 className="text-sm font-semibold text-foreground uppercase tracking-wider">File Previews</h2>
        {isSaving && <Loader2 className="h-4 w-4 text-brand animate-spin" />}
      </div>

      <SettingsLoadingState isLoading={isLoading} error={error} message="Unable to load preview settings." />

      {settings && (
        <div className="space-y-5">
          <div className="space-y-3">
            <Toggle
              label="Show previews"
              checked={settings.show_previews}
              onChange={(v) => onUpdate({ show_previews: v })}
            />
            <Toggle
              label="RAW embedded previews"
              description="Extract embedded JPEG previews from RAW photos on demand."
              checked={settings.raw_preview_enabled}
              disabled={!settings.show_previews}
              onChange={(v) => onUpdate({ raw_preview_enabled: v })}
            />
          </div>

          <div>
            <p className="text-xs text-muted-foreground mb-2">Max preview file size</p>
            <SegmentedButtons
              options={[
                { value: 25 as const, label: '25 MB' },
                { value: 50 as const, label: '50 MB' },
                { value: 100 as const, label: '100 MB' },
              ]}
              value={settings.max_preview_size_mb}
              onChange={(v) => onUpdate({ max_preview_size_mb: v })}
              ariaLabel="Max preview file size"
            />
          </div>

          <div className="grid grid-cols-1 gap-4 border-t border-border pt-5">
            <NumberSetting
              label="Readable preview page size (characters)"
              value={settings.readable_preview_page_chars}
              min={1000}
              onChange={(v) => onUpdate({ readable_preview_page_chars: v })}
              description="Controls generated page length in document detail previews."
            />
            <NumberSetting
              label="Long text pagination threshold (characters)"
              value={settings.long_text_pagination_threshold_chars}
              min={1000}
              onChange={(v) => onUpdate({ long_text_pagination_threshold_chars: v })}
              description="Plain text longer than this uses the paginated reader."
            />
          </div>
        </div>
      )}
    </section>
  )
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
