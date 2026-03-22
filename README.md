# Notion Fitness Tracker

Automated fitness and health data aggregation into Notion. Pulls training sessions from Hevy, Garmin, and Stryd, health metrics from Garmin, and generates a static GitHub Pages dashboard with interactive charts showing performance trends, training load, biomechanics, and recovery metrics.

## Features

- **Multi-source training sync** — Hevy (gym), Garmin (running/cycling), Stryd (running power/biomechanics), Strava (via Zapier), manual entry
- **Stryd complement mode** — Enriches Garmin runs with power metrics (watts, RSS, cadence, ground contact, etc.) and RPE/feeling data
- **Health data tracking** — Sleep duration, sleep quality, steps, resting HR, body battery from Garmin
- **Interactive dashboard** — GitHub Pages site with Chart.js charts: activity calendar heatmap, power trends, ACWR training load, strength metrics, running form, recovery data
- **Deduplication** — Safe to re-run; uses External ID to skip already-synced entries
- **Backfill support** — Sync historical data with `--days 30` or `--full`

## Notion Databases

| Database | Purpose |
|----------|---------|
| **Training Sessions** | All workouts from all sources |
| **Health Status Log** | Daily health metrics from Garmin |
| **Weekly Statistics** | Aggregated weekly stats (rollups) |

## Data Sources

| Source | Method | Schedule |
|--------|--------|----------|
| **Hevy** | Python script via GitHub Actions | Every 6 hours |
| **Garmin + Stryd** | Combined Python workflow (sequential) | Daily at 7 AM UTC |
| **Strava** | Zapier automation | On new activity |
| **CrossFit / Mobility** | Manual entry in Notion | — |
| **Dashboard** | Auto-deploy after any sync + Monday 8:30 AM UTC | — |

## Setup

### Prerequisites

- [uv](https://docs.astral.sh/uv/) for Python dependency management
- A [Notion integration](https://www.notion.so/my-integrations) with access to your Fitness Tracker page
- Hevy Pro subscription (for API access)
- Garmin Connect account
- Stryd account (for running power data)

### 1. Clone and install

```bash
git clone https://github.com/FenryrMKIII/notion-fitness-tracker.git
cd notion-fitness-tracker
cp .env.example .env
# Edit .env with your actual credentials
uv sync
```

### 2. Create a Notion integration

1. Go to https://www.notion.so/my-integrations
2. Create a new integration named **"Fitness Tracker"**
3. Grant capabilities: **Read content**, **Update content**, **Insert content**
4. Copy the **Internal Integration Token** (starts with `ntn_`)
5. In Notion, open the **Fitness Tracker** page > `...` menu > **Connect to** > select your integration

### 3. Configure GitHub Secrets

Add these secrets in your repo's **Settings > Environments > prod**:

| Secret | Description |
|--------|-------------|
| `NOTION_API_KEY` | Notion integration token |
| `NOTION_TRAINING_DB_ID` | Training Sessions database ID |
| `NOTION_HEALTH_DB_ID` | Health Status Log database ID |
| `HEVY_API_KEY` | Hevy API key (from Hevy Settings > API) |
| `GARMIN_EMAIL` | Garmin Connect email |
| `GARMIN_PASSWORD` | Garmin Connect password |
| `GARMIN_TOKENS` | Base64-encoded OAuth tokens (see below) |
| `STRYD_EMAIL` | Stryd account email |
| `STRYD_PASSWORD` | Stryd account password |

### 4. Set up Garmin token caching

Garmin rate-limits SSO logins from cloud IPs (GitHub Actions runners), causing 429 errors. To avoid this, OAuth tokens are cached between workflow runs. The tokens need to be generated locally and uploaded as a GitHub secret to seed the initial cache.

```bash
# Login locally and upload tokens to GitHub in one step
uv run python -m scripts.refresh_garmin_tokens --upload
```

The OAuth1 token lasts ~1 year. Each workflow run refreshes and re-caches the tokens automatically. If the tokens eventually expire and the workflow starts failing with 429 errors, re-run the command above.

You can also do it in two steps (generate locally, then upload manually):

```bash
uv run python -m scripts.refresh_garmin_tokens
tar -czf - -C .garmin_tokens . | base64 | tr -d '\n' | gh secret set GARMIN_TOKENS -R FenryrMKIII/notion-fitness-tracker --env prod
```

### 5. Set up Stryd (optional)
The Stryd sync enriches Garmin running entries with power-based metrics (watts, RSS, ground contact, cadence, etc.) and can store RPE and feeling data from your Stryd Post Run Reports.

No additional setup needed beyond the GitHub secrets above. The combined Running Sync workflow runs daily at 7 AM UTC — Garmin sync runs first, then Stryd sync matches and enriches the Garmin entries with power data.

To backfill historical data:

```bash
uv run python -m scripts.stryd_sync --full
```

### 6. Set up Strava (optional)

See [remaining.md](remaining.md) for the step-by-step Zapier automation guide.

## Usage

### Local commands

```bash
# Hevy — sync all workouts
uv run python -m scripts.hevy_sync --full

# Hevy — sync since a date
uv run python -m scripts.hevy_sync --since 2026-01-01

# Garmin — sync yesterday
uv run python -m scripts.garmin_sync

# Garmin — sync a specific date
uv run python -m scripts.garmin_sync --date 2026-02-01

# Garmin — backfill last 30 days
uv run python -m scripts.garmin_sync --days 30

# Stryd — sync last 7 days (default)
uv run python -m scripts.stryd_sync

# Stryd — sync since a date
uv run python -m scripts.stryd_sync --since 2026-01-01

# Stryd — sync all historical data
uv run python -m scripts.stryd_sync --full

# Dashboard — generate charts data locally
uv run python -m scripts.generate_charts_data --output site/data.json

# Cleanup — preview duplicate Running entries
uv run python -m scripts.cleanup_duplicates --dry-run

# Cleanup — archive duplicate Running entries
uv run python -m scripts.cleanup_duplicates
```

All commands accept `--verbose` / `-v` for debug logging.

### GitHub Actions

Workflows run on schedule automatically. To trigger manually:

```bash
# Combined Garmin + Stryd sync (yesterday)
gh workflow run "Running Sync"

# Combined sync with Garmin backfill (last 30 days)
gh workflow run "Running Sync" --field garmin_days=30

# Hevy sync (all workouts)
gh workflow run "Hevy Sync"

# Stryd-only sync (full history backfill)
gh workflow run "Stryd Sync" --field full=true

# Garmin-only sync (specific date)
gh workflow run "Garmin Sync" --field date=2026-02-01

# Deploy dashboard
gh workflow run "Deploy Charts Dashboard"
```

## Development

```bash
# Run tests
uv run pytest

# Lint
uv run ruff check scripts/ tests/

# Type check
uv run mypy scripts/
```

## Project Structure

```
scripts/
  notion_client.py        # Shared Notion API client (retry, rate limiting, archive)
  hevy_sync.py            # Hevy -> Training Sessions sync
  garmin_sync.py           # Garmin -> Training Sessions + Health Status Log sync
  stryd_sync.py            # Stryd -> Training Sessions (complement mode)
  generate_charts_data.py  # Generates site/data.json for the dashboard
  update_dashboard.py      # Shared pure functions (retired as standalone script)
  cleanup_duplicates.py    # One-time duplicate Running entry cleanup with power merge
  refresh_garmin_tokens.py # Refresh and upload Garmin OAuth tokens for CI
site/
  index.html              # Dashboard: 8 sections, 18 charts + activity calendar
  app.js                  # Chart.js rendering, time range filtering
  style.css               # Dark theme, responsive grid
tests/
  test_notion_client.py
  test_hevy_sync.py
  test_garmin_sync.py
  test_stryd_sync.py
  test_update_dashboard.py
  test_generate_charts_data.py
  test_cleanup_duplicates.py
.github/workflows/
  running_sync.yml         # Daily 7 AM UTC (Garmin then Stryd sequential)
  hevy_sync.yml            # Every 6 hours
  garmin_sync.yml          # Manual dispatch only
  stryd_sync.yml           # Manual dispatch only
  deploy_charts.yml        # Auto after sync + Monday 8:30 AM UTC
```
