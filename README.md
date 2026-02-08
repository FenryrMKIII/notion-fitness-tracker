# Notion Fitness Tracker

Automated fitness and health data aggregation into Notion. Pulls training sessions from Hevy and Garmin, health metrics from Garmin, and generates a weekly dashboard with 4-week trends.

## Features

- **Multi-source training sync** — Hevy (gym), Garmin (running/cycling), Strava (via Zapier), manual entry
- **Health data tracking** — Sleep, steps, resting HR, body battery from Garmin
- **Auto-generated dashboard** — 4-week trend tables with color-coded comparisons and insights
- **Deduplication** — Safe to re-run; uses External ID to skip already-synced entries
- **Backfill support** — Sync historical data with `--days 30`

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
| **Garmin** | Python script via GitHub Actions | Daily at 7 AM UTC |
| **Strava** | Zapier automation | On new activity |
| **CrossFit / Mobility** | Manual entry in Notion | — |
| **Dashboard** | Python script via GitHub Actions | Weekly Monday 8 AM UTC |

## Setup

### Prerequisites

- [uv](https://docs.astral.sh/uv/) for Python dependency management
- A [Notion integration](https://www.notion.so/my-integrations) with access to your Fitness Tracker page
- Hevy Pro subscription (for API access)
- Garmin Connect account

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
| `NOTION_DASHBOARD_PAGE_ID` | Dashboard page ID |
| `HEVY_API_KEY` | Hevy API key (from Hevy Settings > API) |
| `GARMIN_EMAIL` | Garmin Connect email |
| `GARMIN_PASSWORD` | Garmin Connect password |

### 4. Set up Strava (optional)

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

# Dashboard — update the Notion dashboard
uv run python -m scripts.update_dashboard

# Dashboard — dry run (log metrics without writing)
uv run python -m scripts.update_dashboard --dry-run
```

All commands accept `--verbose` / `-v` for debug logging.

### GitHub Actions

Workflows run on schedule automatically. To trigger manually:

```bash
# Garmin sync (yesterday)
gh workflow run "Garmin Sync"

# Garmin backfill (last 30 days)
gh workflow run "Garmin Sync" --field days=30

# Hevy sync (all workouts)
gh workflow run "Hevy Sync"

# Dashboard update
gh workflow run "Update Dashboard"
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
  notion_client.py      # Shared Notion API client (retry, rate limiting)
  hevy_sync.py          # Hevy -> Training Sessions sync
  garmin_sync.py         # Garmin -> Training Sessions + Health Status Log sync
  update_dashboard.py    # Dashboard generation with trend tables + insights
tests/
  test_notion_client.py
  test_hevy_sync.py
  test_garmin_sync.py
  test_update_dashboard.py
.github/workflows/
  hevy_sync.yml          # Every 6 hours
  garmin_sync.yml        # Daily 7 AM UTC
  update_dashboard.yml   # Weekly Monday 8 AM UTC
```
