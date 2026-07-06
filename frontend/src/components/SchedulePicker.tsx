// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

/* eslint-disable react-refresh/only-export-components */

import { useState } from 'react'
import type { IntervalUnit, ScheduleConfig, ScheduleType } from '@/types/api'
import { Input } from '@/components/ui/input'

type ScheduleMode = 'manual' | '@hourly' | '@daily' | '@weekly' | 'interval' | 'advanced'

export function intervalUnitMax(unit: IntervalUnit): number {
  switch (unit) {
    case 'minutes':
      return 59
    case 'hours':
      return 23
    case 'days':
      return 31
  }
}

// Human-readable schedule labels, used outside the picker too (e.g. read-only effective schedule display)
export function formatScheduleConfig(config?: ScheduleConfig | null): string {
  if (!config) return 'Manual'
  if (config.schedule_type === 'interval') {
    if (!config.interval_value || !config.interval_unit) return 'Manual'
    const unitLabel = config.interval_value === 1 ? config.interval_unit.slice(0, -1) : config.interval_unit
    return `Every ${config.interval_value} ${unitLabel}`
  }
  return formatCronSchedule(config.scan_schedule)
}

export function formatCronSchedule(schedule?: string | null): string {
  if (!schedule) return 'Manual'
  switch (schedule) {
    case '@hourly': return 'Hourly'
    case '@daily': return 'Daily'
    case '@weekly': return 'Weekly'
  }
  return schedule
}

function modeFromConfig(config?: ScheduleConfig | null): ScheduleMode {
  if (!config) return 'manual'
  if (config.schedule_type === 'interval') return config.interval_value ? 'interval' : 'manual'
  const s = config.scan_schedule
  if (!s) return 'manual'
  if (['@hourly', '@daily', '@weekly'].includes(s)) return s as ScheduleMode
  return 'advanced'
}

/**
 * Shared schedule picker: cron presets, a true interval, or advanced cron.
 * Used both for a per-source schedule and for the global default schedule
 * in Settings — both bind to the same ScheduleConfig shape.
 */
export function SchedulePicker({
  value,
  onChange,
  idPrefix = 'schedule',
}: {
  value: ScheduleConfig | null | undefined
  onChange: (config: ScheduleConfig) => void
  idPrefix?: string
}) {
  const [mode, setMode] = useState<ScheduleMode>(() => modeFromConfig(value))
  const [intervalValue, setIntervalValue] = useState(String(value?.interval_value ?? 3))
  const [intervalUnit, setIntervalUnit] = useState<IntervalUnit>(value?.interval_unit ?? 'hours')
  const [customCron, setCustomCron] = useState(
    value?.schedule_type === 'cron' && value.scan_schedule && !['@hourly', '@daily', '@weekly'].includes(value.scan_schedule)
      ? value.scan_schedule
      : ''
  )

  const parsedIntervalValue = Number(intervalValue)
  const intervalIsValid = intervalValue.trim() !== '' && Number.isInteger(parsedIntervalValue) && parsedIntervalValue > 0 && parsedIntervalValue <= intervalUnitMax(intervalUnit)

  const emit = (nextMode: ScheduleMode, nextIntervalValue = intervalValue, nextIntervalUnit = intervalUnit, nextCustomCron = customCron) => {
    let config: ScheduleConfig
    if (nextMode === 'interval') {
      const parsed = Number(nextIntervalValue)
      const valid = nextIntervalValue.trim() !== '' && Number.isInteger(parsed) && parsed > 0 && parsed <= intervalUnitMax(nextIntervalUnit)
      config = {
        schedule_type: 'interval' as ScheduleType,
        scan_schedule: null,
        interval_value: valid ? parsed : null,
        interval_unit: nextIntervalUnit,
      }
    } else if (nextMode === 'advanced') {
      config = { schedule_type: 'cron' as ScheduleType, scan_schedule: nextCustomCron.trim() || null, interval_value: null, interval_unit: null }
    } else if (nextMode === 'manual') {
      config = { schedule_type: 'cron' as ScheduleType, scan_schedule: null, interval_value: null, interval_unit: null }
    } else {
      config = { schedule_type: 'cron' as ScheduleType, scan_schedule: nextMode, interval_value: null, interval_unit: null }
    }
    onChange(config)
  }

  const handleModeChange = (nextMode: ScheduleMode) => {
    setMode(nextMode)
    emit(nextMode)
  }

  return (
    <div className="space-y-2">
      <select
        id={`${idPrefix}-mode`}
        value={mode}
        title="How often OneSearch automatically checks this source for changed files."
        onChange={(e) => handleModeChange(e.target.value as ScheduleMode)}
        className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <option value="manual">Manual only</option>
        <option value="@hourly">Every hour</option>
        <option value="@daily">Daily (2:00 AM)</option>
        <option value="@weekly">Weekly (Sunday 2:00 AM)</option>
        <option value="interval">Custom interval...</option>
        <option value="advanced">Advanced cron...</option>
      </select>
      {mode === 'interval' && (
        <div className="space-y-2 rounded-lg border border-border bg-secondary/30 p-3">
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground">Every</span>
            <Input
              type="number"
              min={1}
              max={intervalUnitMax(intervalUnit)}
              step={1}
              value={intervalValue}
              onChange={(e) => {
                setIntervalValue(e.target.value)
                emit('interval', e.target.value, intervalUnit)
              }}
              className="w-24"
              aria-label="Custom interval value"
            />
            <select
              value={intervalUnit}
              onChange={(e) => {
                const unit = e.target.value as IntervalUnit
                setIntervalUnit(unit)
                emit('interval', intervalValue, unit)
              }}
              className="flex h-10 rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              aria-label="Custom interval unit"
            >
              <option value="minutes">minute(s)</option>
              <option value="hours">hour(s)</option>
              <option value="days">day(s)</option>
            </select>
          </div>
          <p className="text-xs text-muted-foreground">
            {intervalIsValid
              ? `Runs every ${intervalValue} ${parsedIntervalValue === 1 ? intervalUnit.slice(0, -1) : intervalUnit}, starting from when this is saved.`
              : `Choose 1-${intervalUnitMax(intervalUnit)}.`}
          </p>
        </div>
      )}
      {mode === 'advanced' && (
        <div className="space-y-2">
          <Input
            value={customCron}
            onChange={(e) => {
              setCustomCron(e.target.value)
              emit('advanced', intervalValue, intervalUnit, e.target.value)
            }}
            placeholder="0 */6 * * *"
            className="font-mono text-sm"
            aria-label="Advanced cron schedule"
          />
          <p className="text-xs text-muted-foreground">Use standard five-field cron syntax.</p>
        </div>
      )}
    </div>
  )
}

/** Detects a legacy fake-interval cron string (from before true intervals existed). */
export function parseFakeIntervalCron(schedule?: string | null): { value: string; unit: IntervalUnit } | null {
  if (!schedule) return null

  const minuteInterval = schedule.match(/^\*\/(\d+) \* \* \* \*$/)
  if (minuteInterval) return { value: minuteInterval[1], unit: 'minutes' }

  const hourInterval = schedule.match(/^0 \*\/(\d+) \* \* \*$/)
  if (hourInterval) return { value: hourInterval[1], unit: 'hours' }

  const dayInterval = schedule.match(/^0 2 \*\/(\d+) \* \*$/)
  if (dayInterval) return { value: dayInterval[1], unit: 'days' }

  return null
}
