# Scheduling

You can set up automatic scan schedules so your sources stay indexed without manual intervention.

## Setting a Schedule

When adding or editing a source in the web UI, you'll see a schedule picker with these options:

- **Manual** — No automatic scanning. You trigger reindex yourself.
- **Hourly** — Runs every hour on the hour (`0 * * * *`)
- **Daily** — Runs at 2 AM (`0 2 * * *`)
- **Weekly** — Runs at 2 AM on Sundays (`0 2 * * 0`)
- **Custom** — Enter your own cron expression

The daily and weekly presets run at 2 AM to avoid interfering with daytime usage, but you can always use a custom cron if you prefer different timing.

## Custom Cron Expressions

Standard five-field cron format: `minute hour day month weekday`

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

OneSearch uses APScheduler running in a background thread. Jobs are persisted in the database, so schedules survive restarts. When a scheduled job fires, it runs the same incremental indexing as a manual reindex — only changed files get processed.

If a source is already being indexed (from a manual trigger or another schedule run), the new run is skipped to avoid conflicts. You'll see a 409 response if you try to manually reindex while a scheduled run is in progress.

## Monitoring Schedules

The sources table in the admin UI shows each source's schedule and when the next scan is expected. The status page also shows next scan times.

Via the API, check `scan_schedule`, `last_scan_at`, and `next_scan_at` fields on source objects.

## Disabling the Scheduler

If you only want manual indexing, set `SCHEDULER_ENABLED=false` in your environment. This stops the background scheduler entirely — no scheduled jobs will run.
