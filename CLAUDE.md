# CLAUDE.md — Project Context for AI Assistants

## What This Project Does

Syncs fitness training and health data from multiple sources into Notion databases, then generates a static GitHub Pages dashboard with interactive Chart.js charts showing trends, load analysis, and biomechanics. Runs as scheduled GitHub Actions workflows.

## Technology Stack

- **Language**: Python 3.11+
- **Package manager**: uv (pyproject.toml, uv.lock)
- **Key dependencies**: `requests`, `garminconnect`, `python-dotenv`
- **Frontend**: Chart.js v4 static site (GitHub Pages)
- **Testing**: pytest (~301 tests), ruff (linting), mypy (type checking)
- **CI/CD**: GitHub Actions with `prod` environment for secrets
- **Notion API**: REST API v2022-06-28, accessed via `scripts/notion_client.py`

## Architecture

```
Hevy API ──────> hevy_sync.py ──────> Training Sessions DB
Garmin Connect ─> garmin_sync.py ──> Training Sessions DB
                                 └──> Health Status Log DB
Stryd API ─────> stryd_sync.py ──┐
                                 ├──> Training Sessions DB (enriches Garmin runs or creates new)
Strava ─────────> Zapier ────────┘──> Training Sessions DB
Manual ─────────> Notion UI ───────> Training Sessions DB

All 3 DBs ──────> generate_charts_data.py ──> site/data.json ──> GitHub Pages (dashboard)
```

## Notion Database IDs

| Database | ID | Data Source ID |
|----------|-----|----------------|
| Parent Page (Fitness Tracker) | `300483e2-4127-81f7-97c6-e4f6297952fc` | — |
| Training Sessions | `13d713283dd14cd89ba1eb7ac77db89f` | `dad510e1-5618-49f9-a93f-208e0039886b` |
| Health Status Log | `8092ea0a10af4fc895910dec2f0e2862` | `9d63129d-7352-45d2-8c81-4a003102896c` |
| Weekly Statistics | `4f54bdec7af746b78e02eb4a1b290052` | `f137563b-1870-4da6-8f2a-53bf2db2e756` |

## Database Schemas

### Training Sessions

| Property | Type | Notes |
|----------|------|-------|
| Name | title | Activity name |
| Date | date | Activity date |
| Training Type | select | Running, Gym-Strength, Gym-Crossfit, Mobility, Specifics |
| Duration (min) | number | |
| Source | select | Hevy, Garmin, Strava, Stryd, Manual |
| External ID | rich_text | Dedup key (e.g. `garmin-12345`, `hevy-abc`, `stryd-1738900800`) |
| Distance (km) | number | Optional |
| Avg Heart Rate | number | Optional |
| Volume (kg) | number | Total weight x reps |
| Exercise Details | rich_text | Formatted exercise summary |
| Notes | rich_text | Optional |
| Feeling | select | Great, Good, Okay, Tired, Exhausted |
| Power (W) | number | Stryd: average running power |
| RSS | number | Stryd: Running Stress Score |
| Critical Power (W) | number | Stryd: FTP at time of run |
| Cadence (spm) | number | Stryd: steps per minute |
| Stride Length (m) | number | Stryd: average stride length |
| Ground Contact (ms) | number | Stryd: ground contact time |
| Vertical Oscillation (cm) | number | Stryd: vertical bounce |
| Leg Spring Stiffness | number | Stryd: running economy metric |
| RPE | number | Rate of Perceived Exertion (1-10, from Stryd if available) |
| Temperature (C) | number | Stryd: environmental temp during run |
| Wind Speed | number | Stryd: wind speed during run |

### Health Status Log

| Property | Type | Notes |
|----------|------|-------|
| Date Label | title | `"Health Log — YYYY-MM-DD"` |
| Date | date | |
| External ID | rich_text | `"garmin-health-YYYY-MM-DD"` |
| Sleep Duration (h) | number | From Garmin `sleepTimeSeconds / 3600` |
| Sleep Quality | select | EXCELLENT, GOOD, FAIR, POOR (from Garmin `sleepScores.overall.qualifierKey`, with `sleepQualityType` as legacy fallback) |
| Steps | number | Sum of Garmin step entries |
| Resting HR | number | From Garmin `get_heart_rates()` → `restingHeartRate` |
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
- `find_page_by_external_id(external_id, db_id)` — find page ID by External ID
- `update_page(page_id, properties)` — update existing page properties
- `archive_page(page_id)` — archive a page (set `archived: true`)
- `query_database(db_id, filter, sorts)` — paginated queries
- `get_block_children(block_id)` / `delete_block(block_id)` / `append_block_children(block_id, children)` — block operations for dashboard

### `scripts/hevy_sync.py`

Syncs gym workouts from Hevy API. Flags: `--full` (all pages), `--since DATE`.
- Hevy API: `GET https://api.hevyapp.com/v1/workouts` with `api-key` header
- Maps all workouts to Training Type = "Gym-Strength"
- Calculates volume (weight x reps) and formats exercise details
- Duration capped at 60 min to handle timer-not-stopped scenarios

### `scripts/garmin_sync.py`

Syncs activities and health data from Garmin Connect. Flags: `--date DATE`, `--days N`.
- Uses `garminconnect` library for authentication and API calls
- **Activities** → Training Sessions DB (maps activity types via `GARMIN_TYPE_MAPPING`)
- **Health data** → Health Status Log DB (sleep, steps, RHR, body battery)
- 4 Garmin endpoints fetched independently with per-endpoint error handling:
  `get_sleep_data()`, `get_steps_data()`, `get_heart_rates()`, `get_body_battery()`
- Multi-day mode: iterates date range, catches per-day errors, reports failures at end
- Skips health sync gracefully if `NOTION_HEALTH_DB_ID` is not set

### `scripts/stryd_sync.py`

Syncs running power and biomechanics data from Stryd (complement to Garmin). Flags: `--since DATE`, `--full`, `--debug`.
- Stryd API: `POST https://www.stryd.com/b/email/signin` (auth), `GET /b/api/v1/users/{user_id}/calendar` (activities)
- **Auth**: Non-standard bearer header: `Authorization: Bearer: {token}` (note colon after Bearer)
- **Date filtering**: Server-side via Unix timestamp `from`/`to` params (replaces old MM-DD-YYYY client-side filtering)
- **Deduplication**: `deduplicate_activities()` handles Stryd's dual-source entries (Garmin-synced + native recordings for same run)
- **Complement mode**: matches Stryd activities to existing Garmin running entries by date + Source=Garmin + Training Type=Running, updates them with power metrics
- **Standalone mode**: creates new entries (Source = "Stryd") if no Garmin match found
- Power metrics: watts, RSS, critical power, cadence, stride length, ground contact, vertical oscillation, leg spring stiffness, temperature, wind speed
- **RPE**: available as `rpe` field (integer 1-10, 0 = not entered). Stored as number, independent from Feeling
- **Feeling**: available as `feel` field (great/good/normal/ok/bad/terrible). Mapped to Notion select via `FEEL_MAPPING`. RPE and Feeling are never correlated
- Uses `average_power` (not `stryds` which is cumulative)
- `--debug` flag dumps raw API JSON for inspection
- External ID format: `stryd-{unix_timestamp}`

### `scripts/cleanup_duplicates.py`

One-time utility to archive duplicate Running entries. Flags: `--dry-run`, `--verbose`.
- Groups Running entries by date, scores each by data completeness
- Scoring: +1 per non-empty property, +3 for power data, +2 for HR, +2 for distance > 1km
- Before archiving, merges Stryd power metrics from lower-scored duplicate into keeper
- `has_power_data(page)` / `get_power_properties(page)` — pure helpers for power data detection and extraction
- `merge_power_data()` — transfers all Stryd metrics (Power, RSS, Cadence, etc.) to keeper via PATCH

### `scripts/update_dashboard.py` (retired — Notion dashboard no longer used)

Previously generated a Notion-based dashboard. Now serves only as a library of shared pure functions reused by `generate_charts_data.py`:
- `fetch_training_data()`, `fetch_health_data()` — query Notion DBs
- `calculate_training_week()`, `calculate_health_week()`, `calculate_running_period()`, `calculate_training_load()` — weekly aggregate computations
- `TrainingWeek`, `HealthWeek`, `RunningPeriod`, `TrainingLoad` dataclasses
- `detect_overreaching()`, `get_period_boundaries()`, `get_week_boundaries()`

### `scripts/generate_charts_data.py`

Generates `data.json` for the static GitHub Pages dashboard. Flags: `--output PATH`, `--verbose`, `--dry-run`.
- Reuses `fetch_training_data`, `fetch_health_data`, `calculate_training_week`, `calculate_health_week`, `calculate_running_period`, `calculate_training_load` from `update_dashboard.py`
- `build_charts_data()`: pure function converting raw Notion records to the full JSON structure
- `compute_rolling_acwr()`: computes ACWR for each week using a 4-week sliding window
- Output: `site/data.json` with `sessions`, `health`, `weekly.training`, `weekly.health`, `weekly.running`, `weekly.load`
- Weekly data is chronological (oldest first); individual records sorted by date ascending

### `site/` — Static Dashboard

GitHub Pages site with interactive Chart.js charts.
- `index.html`: single-page layout with 8 sections, 18 chart canvases + activity calendar heatmap
- `style.css`: dark theme (GitHub-inspired), responsive grid
- `app.js`: Chart.js rendering, time range filtering (4W/3M/6M/1Y/All)
- **Activity Calendar**: GitHub-style heatmap showing training days by type (color-coded, diagonal split for multi-activity days, hover tooltips)
- **Performance**: power trend, power vs HR
- **Training Load**: weekly RSS, weekly distance, duration by type (stacked), ACWR with zone bands
- **Strength**: weekly gym volume (bar), volume per session (line), gym session duration (line)
- **Running Form**: cadence, ground contact, vertical oscillation
- **Balance**: type/feeling distribution donuts
- **Recovery**: sleep, resting HR, body battery, steps
- `data.json` is gitignored (generated artifact)

## Environment Variables

| Variable | Used By | Required |
|----------|---------|----------|
| `NOTION_API_KEY` | All scripts | Yes |
| `NOTION_TRAINING_DB_ID` | All scripts | Yes |
| `NOTION_HEALTH_DB_ID` | garmin_sync, generate_charts_data | Yes (garmin_sync skips if missing) |
| `HEVY_API_KEY` | hevy_sync | Yes |
| `GARMIN_EMAIL` | garmin_sync | Yes |
| `GARMIN_PASSWORD` | garmin_sync | Yes |
| `STRYD_EMAIL` | stryd_sync | Yes |
| `STRYD_PASSWORD` | stryd_sync | Yes |

For local dev: copy `.env.example` to `.env`. In CI: secrets are in the GitHub `prod` environment.

## GitHub Actions Workflows

| Workflow | File | Schedule | Inputs |
|----------|------|----------|--------|
| Running Sync | `running_sync.yml` | Daily 7 AM UTC | `garmin_date`, `garmin_days`, `stryd_since`, `stryd_full`, `verbose` |
| Hevy Sync | `hevy_sync.yml` | Every 6h | `full`, `since`, `verbose` |
| Garmin Sync | `garmin_sync.yml` | Manual only | `date`, `days`, `verbose` |
| Stryd Sync | `stryd_sync.yml` | Manual only | `since`, `full`, `debug`, `verbose` |
| Deploy Charts (dashboard) | `deploy_charts.yml` | Monday 8:30 AM UTC + after any sync | `verbose` |

All workflows use `environment: prod`, pinned action versions (SHA), and secret validation steps.

The Deploy Charts workflow also requires GitHub Pages enabled (Settings > Pages > Source = "GitHub Actions") and `pages: write` + `id-token: write` permissions.

## Testing

```bash
uv run pytest           # ~301 tests, ~0.2s
uv run ruff check scripts/ tests/
```

All sync logic is tested via pure functions (extraction, property building, calculations, block generation). No mocking of Notion/Garmin APIs needed for unit tests.

## Key Design Patterns

- **Deduplication**: Every synced entry has an `External ID` (e.g. `garmin-12345`, `hevy-abc`, `garmin-health-2026-02-07`, `stryd-1738900800`). Scripts check for existing entries before creating.
- **Complement enrichment**: Stryd sync finds matching Garmin entries by date + Source + Training Type filter, then updates them with power metrics via `update_page()`. Creates standalone entries only when no Garmin match exists.
- **Pure functions**: Data extraction, property building, metric calculations, and Notion block construction are all pure — no side effects, easy to test.
- **Graceful degradation**: Each Garmin health endpoint is fetched independently; if one fails, others still sync. Multi-day mode catches per-day errors.
- **Rate limiting**: NotionClient sleeps 0.35s between API calls to stay within Notion's 3 req/s limit.
- **Sequential sync**: Running Sync workflow runs Garmin before Stryd in the same job, ensuring Stryd complement mode always finds Garmin entries to enrich (eliminates race-condition duplicates).

## Known Quirks

- Garmin `sleepQualityType` is a deprecated/legacy field — almost always `None`. Code falls back to `sleepScores.overall.qualifierKey` (modern Garmin sleep score system)
- Garmin `get_rhr_day()` returns a deeply nested structure unsuitable for simple extraction — use `get_heart_rates()` instead which returns `restingHeartRate` at the top level
- Garmin `sleepTimeSeconds` can be `None` (not just 0) when the key exists — handled with `or 0`
- Notion MCP `<database data-source-url>` does NOT work for inline database views — use `<mention-database>` instead
- The dashboard script clears ALL blocks on the page before rewriting — don't put manual content on the dashboard page
- Weekly Statistics DB uses Notion-native rollups/relations — not written to by scripts

## Stryd Integration

- **API**: Undocumented REST API at `https://www.stryd.com/b/api/v1/` — email/password auth returns bearer token
- **Auth header**: Non-standard `Authorization: Bearer: {token}` (colon after Bearer)
- **Activities endpoint**: `GET /users/{user_id}/calendar?from=UNIX_TS&to=UNIX_TS&include_deleted=false`
- **Complement mode**: Stryd data enriches existing Garmin running entries (power, biomechanics, environmental conditions)
- **RPE**: Available as `rpe` field (integer 1-10, 0 = not entered). Stored as a standalone number — never correlated to Feeling
- **Feeling**: Available as `feel` field (great/good/normal/ok/bad/terrible). Mapped to Notion Feeling select. Independent from RPE
- **Power**: Use `average_power` field (watts). The `stryds` field is cumulative (not average)
- **Matching**: Finds Garmin entries by date + Source=Garmin + Training Type=Running filter
- **Historical data**: ~310 activities going back to 2021

## Strava Integration

Not automated via code. Requires manual Zapier setup (see `remaining.md` for step-by-step guide). Maps Strava activities to Training Sessions with Source = "Strava".
