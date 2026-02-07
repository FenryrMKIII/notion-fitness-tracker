# Notion Fitness Tracker

Automated fitness data aggregation into Notion from multiple sources.

## Data Sources

| Source | Method | Schedule |
|--------|--------|----------|
| **Hevy** | Python script via GitHub Actions | Every 6 hours |
| **Garmin** | Python script via GitHub Actions | Daily at 7 AM UTC |
| **Strava** | Zapier automation | On new activity |
| **CrossFit / Mobility / Sprint** | Manual entry in Notion | - |

## Setup

### Prerequisites

- [uv](https://docs.astral.sh/uv/) for Python dependency management
- A Notion integration with access to your Fitness Tracker databases
- Hevy Pro subscription (for API access)
- Garmin Connect account

### Local Development

```bash
# Clone the repo
git clone https://github.com/FenryrMKIII/notion-fitness-tracker.git
cd notion-fitness-tracker

# Create .env from example
cp .env.example .env
# Edit .env with your actual credentials

# Install dependencies
uv sync

# Run Hevy sync (all workouts)
uv run python scripts/hevy_sync.py --full

# Run Hevy sync (since a specific date)
uv run python scripts/hevy_sync.py --since 2026-02-01

# Run Garmin sync (yesterday's data)
uv run python scripts/garmin_sync.py

# Run Garmin sync (specific date)
uv run python scripts/garmin_sync.py --date 2026-02-06
```

### GitHub Actions (Automated)

Add these secrets to your GitHub repository (Settings > Secrets and variables > Actions):

| Secret | Description |
|--------|-------------|
| `HEVY_API_KEY` | Your Hevy API key |
| `NOTION_API_KEY` | Your Notion integration token |
| `NOTION_TRAINING_DB_ID` | Training Sessions database ID (`13d713283dd14cd89ba1eb7ac77db89f`) |
| `GARMIN_EMAIL` | Your Garmin Connect email |
| `GARMIN_PASSWORD` | Your Garmin Connect password |

Workflows run automatically on schedule. You can also trigger them manually from the Actions tab.

## Architecture

```
Hevy API ──> hevy_sync.py ──> Notion Training Sessions
Garmin Connect ──> garmin_sync.py ──> Notion Training Sessions
Strava ──> Zapier ──> Notion Training Sessions
Manual ──> Notion UI ──> Notion Training Sessions
```

All data lands in a single **Training Sessions** database with a `Source` field to identify the origin. Deduplication is handled via the `External ID` field.
