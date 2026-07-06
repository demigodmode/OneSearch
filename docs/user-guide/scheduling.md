# Scheduling

You can set up automatic scan schedules so your sources stay indexed without manual intervention. As of v1.3.0, schedules can be a true interval, a cron expression, or inherited from a single global default.

## Setting a Schedule

When adding or editing a source in the web UI, you'll see a schedule picker with these options:

- **Manual**: No automatic scanning. You trigger reindex yourself.
- **Hourly**: Runs every hour on the hour (`0 * * * *`)
- **Daily**: Runs at 2 AM (`0 2 * * *`)
- **Weekly**: Runs at 2 AM on Sundays (`0 2 * * 0`)
- **Custom interval...**: Choose every N minutes, hours, or days.
- **Advanced cron...**: Enter your own cron expression.

There's also a **Use global default** toggle. When it's on, the source ignores its own schedule fields and follows whatever is configured under **Settings → Scheduling** instead. The source's own schedule is preserved while the toggle is on, and reappears if you turn it back off, so switching between "follow the default" and "use my own schedule" doesn't lose your settings.

## Custom Intervals Are Now True Intervals

Before v1.3.0, custom intervals were converted into cron expressions and ran on cron clock boundaries. An "every 6 hours" schedule always landed at 00:00, 06:00, 12:00, and 18:00, no matter when you saved it.

As of v1.3.0, custom intervals are real interval triggers. "Every 6 hours" now means 6 hours from when the schedule is saved, not the next clock boundary.

If you have an older source whose schedule looks like a fixed interval written as cron (for example `0 */3 * * *`), the source edit form detects this and offers a one-click **Switch to true interval** prompt, which converts it without you needing to re-enter the value.

The daily and weekly presets still run at 2 AM to avoid interfering with daytime usage, since those are cron-based presets, not intervals.

## The Global Default Schedule

Under **Settings → Scheduling**, you can set one schedule (cron or true interval) that acts as the default for any source with **Use global default** enabled. This is useful if most of your sources should follow the same cadence and you don't want to configure each one individually.

The default schedule uses the same picker as a per-source schedule, so it can be a preset, a true interval, or advanced cron. Changing the default automatically re-syncs every source that's following it; sources with their own schedule are untouched.

The Sources list shows a small link icon next to any source that's following the global default, so you can tell at a glance without opening the edit form.

## Advanced Cron Expressions

Standard five-field cron format: `minute hour day month weekday`

Use **Advanced cron...** when you want exact control.

Some examples:

| Expression | Meaning |
|-----------|---------|
| `0 * * * *` | Every hour |
| `0 2 * * *` | Daily at 2 AM |
| `0 */6 * * *` | Every 6 hours, on clock boundaries |
| `30 1 * * 1-5` | Weekdays at 1:30 AM |
| `0 3 1 * *` | First day of each month at 3 AM |

Cron expressions always run on clock boundaries. If you want a true "N units from now" schedule instead, use **Custom interval...**.

## Timezone

Cron-based schedules (presets and advanced cron) run in the timezone configured by `SCHEDULE_TIMEZONE` (defaults to UTC). Set this in your `.env` file if you want cron schedules to follow your local time:

```env
SCHEDULE_TIMEZONE=America/New_York
```

Uses standard IANA timezone names. True intervals aren't affected by timezone, since they run N units from whenever they were last saved or last fired.

## How It Works

OneSearch uses APScheduler running in a background thread. The schedule is saved on the source record (or resolved from the global default), and scheduler jobs are rebuilt from those records on startup. When a scheduled job fires, it runs the same incremental indexing as a manual reindex. Only changed files get processed.

If a source is already being indexed (from a manual trigger or another schedule run), the new run is skipped to avoid conflicts. You'll see a 409 response if you try to manually reindex while a scheduled run is in progress.

## Monitoring Schedules

The sources table in the admin UI shows each source's effective schedule (its own, or the inherited default) and when the next scan is expected. The status page also shows next scan times.

Via the API, check the `effective_schedule`, `last_scan_at`, and `next_scan_at` fields on source objects. See the [Sources API](../api/sources.md) reference for the full field list.

## Disabling the Scheduler

If you only want manual indexing, set `SCHEDULER_ENABLED=false` in your environment. This stops the background scheduler entirely. No scheduled jobs will run.
