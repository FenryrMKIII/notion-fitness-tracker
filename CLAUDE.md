# CLAUDE.md — Project Context for AI Assistants

## What This Project Does

Syncs fitness training and health data from multiple sources into Notion databases, then generates a dashboard with 4-week trend analysis. Runs as scheduled GitHub Actions workflows.

## Technology Stack

- **Language**: Python 3.11+
- **Package manager**: uv (pyproject.toml, uv.lock)
- **Key dependencies**: `requests`, `garminconnect`, `python-dotenv`
- **Testing**: pytest (122 tests), ruff (linting), mypy (type checking)
- **CI/CD**: GitHub Actions with `prod` environment for secrets
- **Notion API**: REST API v2022-06-28, accessed via `scripts/notion_client.py`

## Architecture

```
Hevy API ──────> hevy_sync.py ──────> Training Sessions DB
Garmin Connect ─> garmin_sync.py ──> Training Sessions DB
                                 └──> Health Status Log DB
Strava ─────────> Zapier ──────────> Training Sessions DB
Manual ─────────> Notion UI ───────> Training Sessions DB

All 3 DBs ──────> update_dashboard.py ──> Dashboard Page (Notion blocks)
```

## Notion Database IDs

| Database | ID | Data Source ID |
|----------|-----|----------------|
| Parent Page (Fitness Tracker) | `300483e2-4127-81f7-97c6-e4f6297952fc` | — |
| Training Sessions | `13d713283dd14cd89ba1eb7ac77db89f` | `dad510e1-5618-49f9-a93f-208e0039886b` |
| Health Status Log | `8092ea0a10af4fc895910dec2f0e2862` | `9d63129d-7352-45d2-8c81-4a003102896c` |
| Weekly Statistics | `4f54bdec7af746b78e02eb4a1b290052` | `f137563b-1870-4da6-8f2a-53bf2db2e756` |
| Dashboard Page | `300483e24127810e8458d0bbedc7bb7e` | — |

## Database Schemas

### Training Sessions

| Property | Type | Notes |
|----------|------|-------|
| Name | title | Activity name |
| Date | date | Activity date |
| Training Type | select | Running, Gym-Strength, Gym-Crossfit, Mobility, Specifics |
| Duration (min) | number | |
| Source | select | Hevy, Garmin, Strava, Manual |
| External ID | rich_text | Dedup key (e.g. `garmin-12345`, `hevy-abc`) |
| Distance (km) | number | Optional |
| Avg Heart Rate | number | Optional |
| Volume (kg) | number | Total weight x reps |
| Exercise Details | rich_text | Formatted exercise summary |
| Notes | rich_text | Optional |
| Feeling | select | Great, Good, Okay, Tired, Exhausted |

### Health Status Log

| Property | Type | Notes |
|----------|------|-------|
| Date Label | title | `"Health Log — YYYY-MM-DD"` |
| Date | date | |
| External ID | rich_text | `"garmin-health-YYYY-MM-DD"` |
| Sleep Duration (h) | number | From Garmin `sleepTimeSeconds / 3600` |
| Sleep Quality | select | EXCELLENT, GOOD, FAIR, POOR (from Garmin `sleepQualityType`) |
| Steps | number | Sum of Garmin step entries |
| Resting HR | number | From Garmin RHR endpoint |
| Body Battery | number | Max charged value from Garmin |
| Status | select | Healthy, Sick, Injured, Rest Day, Travel (manual only) |
| Condition | multi_select | Cold, Flu, Muscle Strain, etc. (manual only) |
| Severity | select | Minor, Moderate, Severe (manual only) |
| Notes | rich_text | Manual notes |

## Scripts

### `scripts/notion_client.py`

Shared Notion REST API client. Features:
- Retry with exponential backoff (3 retries, status 429/5xx)
- Rate limiting (0.35s between requests for Notion's 3 req/s limit)
- `check_existing(external_id)` — dedup in Training Sessions DB
- `check_existing_in_db(db_id, external_id)` — dedup in any DB
- `create_page(properties)` / `create_page_in_db(db_id, properties)` — page creation
- `query_database(db_id, filter, sorts)` — paginated queries
- `get_block_children(block_id)` / `delete_block(block_id)` / `append_block_children(block_id, children)` — block operations for dashboard

### `scripts/hevy_sync.py`

Syncs gym workouts from Hevy API. Flags: `--full` (all pages), `--since DATE`.
- Hevy API: `GET https://api.hevyapp.com/v1/workouts` with `api-key` header
- Maps all workouts to Training Type = "Gym-Strength"
- Calculates volume (weight x reps) and formats exercise details

### `scripts/garmin_sync.py`

Syncs activities and health data from Garmin Connect. Flags: `--date DATE`, `--days N`.
- Uses `garminconnect` library for authentication and API calls
- **Activities** → Training Sessions DB (maps activity types via `GARMIN_TYPE_MAPPING`)
- **Health data** → Health Status Log DB (sleep, steps, RHR, body battery)
- 4 Garmin endpoints fetched independently with per-endpoint error handling:
  `get_sleep_data()`, `get_steps_data()`, `get_rhr_day()`, `get_body_battery()`
- Multi-day mode: iterates date range, catches per-day errors, reports failures at end
- Skips health sync gracefully if `NOTION_HEALTH_DB_ID` is not set

### `scripts/update_dashboard.py`

Generates a Notion dashboard page with trend analysis. Flags: `--dry-run`.
- Fetches last 4 weeks of training + health data from Notion
- Computes weekly aggregates (TrainingWeek, HealthWeek dataclasses)
- Builds Notion blocks: tables with color-coded trend values, callouts, insights
- Replaces all blocks on the dashboard page (clear + append)
- Pure functions for all calculations and block building (easy to test)

## Environment Variables

| Variable | Used By | Required |
|----------|---------|----------|
| `NOTION_API_KEY` | All scripts | Yes |
| `NOTION_TRAINING_DB_ID` | All scripts | Yes |
| `NOTION_HEALTH_DB_ID` | garmin_sync, update_dashboard | Yes (garmin_sync skips if missing) |
| `NOTION_DASHBOARD_PAGE_ID` | update_dashboard | Yes |
| `HEVY_API_KEY` | hevy_sync | Yes |
| `GARMIN_EMAIL` | garmin_sync | Yes |
| `GARMIN_PASSWORD` | garmin_sync | Yes |

For local dev: copy `.env.example` to `.env`. In CI: secrets are in the GitHub `prod` environment.

## GitHub Actions Workflows

| Workflow | File | Schedule | Inputs |
|----------|------|----------|--------|
| Hevy Sync | `hevy_sync.yml` | Every 6h | `full`, `since`, `verbose` |
| Garmin Sync | `garmin_sync.yml` | Daily 7 AM UTC | `date`, `days`, `verbose` |
| Update Dashboard | `update_dashboard.yml` | Monday 8 AM UTC | `verbose`, `dry_run` |

All workflows use `environment: prod`, pinned action versions (SHA), and secret validation steps.

## Testing

```bash
uv run pytest           # 122 tests, ~0.2s
uv run ruff check scripts/ tests/
```

All sync logic is tested via pure functions (extraction, property building, calculations, block generation). No mocking of Notion/Garmin APIs needed for unit tests.

## Key Design Patterns

- **Deduplication**: Every synced entry has an `External ID` (e.g. `garmin-12345`, `hevy-abc`, `garmin-health-2026-02-07`). Scripts check for existing entries before creating.
- **Pure functions**: Data extraction, property building, metric calculations, and Notion block construction are all pure — no side effects, easy to test.
- **Graceful degradation**: Each Garmin health endpoint is fetched independently; if one fails, others still sync. Multi-day mode catches per-day errors.
- **Rate limiting**: NotionClient sleeps 0.35s between API calls to stay within Notion's 3 req/s limit.

## Known Quirks

- Garmin `sleepQualityType` is not always present — the field may be missing or `None`
- Garmin `sleepTimeSeconds` can be `None` (not just 0) when the key exists — handled with `or 0`
- Notion MCP `<database data-source-url>` does NOT work for inline database views — use `<mention-database>` instead
- The dashboard script clears ALL blocks on the page before rewriting — don't put manual content on the dashboard page
- Weekly Statistics DB uses Notion-native rollups/relations — not written to by scripts

## Strava Integration

Not automated via code. Requires manual Zapier setup (see `remaining.md` for step-by-step guide). Maps Strava activities to Training Sessions with Source = "Strava".
