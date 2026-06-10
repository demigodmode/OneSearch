# Scheduling

You can set up automatic scan schedules so your sources stay indexed without manual intervention.

## Setting a Schedule

When adding or editing a source in the web UI, you'll see a schedule picker with these options:

- **Manual**: No automatic scanning. You trigger reindex yourself.
- **Hourly**: Runs every hour on the hour (`0 * * * *`)
- **Daily**: Runs at 2 AM (`0 2 * * *`)
- **Weekly**: Runs at 2 AM on Sundays (`0 2 * * 0`)
- **Custom interval...**: Choose every N minutes, hours, or days without writing cron by hand.
- **Advanced cron...**: Enter your own cron expression.

The daily and weekly presets run at 2 AM to avoid interfering with daytime usage. Daily custom intervals also run at 2 AM. Minute and hourly intervals are saved as cron expressions and run on cron clock boundaries, not N minutes or hours after you click save.

## Custom Intervals

Custom intervals are a friendlier way to create common cron schedules:

| UI choice | Saved cron | Meaning |
|-----------|------------|---------|
| Every 15 minutes | `*/15 * * * *` | Runs when the minute is divisible by 15 |
| Every 6 hours | `0 */6 * * *` | Runs at 00:00, 06:00, 12:00, and 18:00 |
| Every 3 days | `0 2 */3 * *` | Runs at 2 AM on matching calendar days |

These are still cron schedules. For example, “Every 6 hours” does not mean six hours after you saved the source; it means the next matching cron boundary.

## Advanced Cron Expressions

Standard five-field cron format: `minute hour day month weekday`

Use **Advanced cron...** when you want exact control.

Some examples:

| Expression | Meaning |
|-----------|---------|
| `0 * * * *` | Every hour |
| `0 2 * * *` | Daily at 2 AM |
| `0 */6 * * *` | Every 6 hours |
| `30 1 * * 1-5` | Weekdays at 1:30 AM |
| `0 3 1 * *` | First day of each month at 3 AM |

## Timezone

Schedules run in the timezone configured by `SCHEDULE_TIMEZONE` (defaults to UTC). Set this in your `.env` file if you want schedules to follow your local time:

```env
SCHEDULE_TIMEZONE=America/New_York
```

Uses standard IANA timezone names.

## How It Works

OneSearch uses APScheduler running in a background thread. The schedule is saved on the source record, and scheduler jobs are rebuilt from those source records on startup. When a scheduled job fires, it runs the same incremental indexing as a manual reindex. Only changed files get processed.

If a source is already being indexed (from a manual trigger or another schedule run), the new run is skipped to avoid conflicts. You'll see a 409 response if you try to manually reindex while a scheduled run is in progress.

## Monitoring Schedules

The sources table in the admin UI shows each source's schedule and when the next scan is expected. The status page also shows next scan times.

Via the API, check `scan_schedule`, `last_scan_at`, and `next_scan_at` fields on source objects.

## Disabling the Scheduler

If you only want manual indexing, set `SCHEDULER_ENABLED=false` in your environment. This stops the background scheduler entirely. No scheduled jobs will run.
