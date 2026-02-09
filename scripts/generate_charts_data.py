#!/usr/bin/env python3
"""Generate JSON data for the GitHub Pages fitness dashboard.

Fetches training and health data from Notion, computes weekly aggregates
and rolling ACWR, then writes a data.json file consumed by the static site.
"""

import argparse
import json
import logging
import os
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

from dotenv import load_dotenv

from scripts.notion_client import ConfigurationError, NotionClient
from scripts.update_dashboard import (
    DashboardConfig,
    RunningPeriod,
    calculate_health_week,
    calculate_running_period,
    calculate_training_load,
    calculate_training_week,
    fetch_health_data,
    fetch_training_data,
    get_period_boundaries,
    group_by_period,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rolling ACWR
# ---------------------------------------------------------------------------


def compute_rolling_acwr(
    running_periods: list[RunningPeriod],
    week_starts: list[date],
) -> list[dict[str, Any]]:
    """Compute ACWR for each week using a 4-week rolling window.

    running_periods and week_starts must be the same length and ordered
    chronologically (oldest first).
    """
    results: list[dict[str, Any]] = []
    for i in range(len(running_periods)):
        rp = running_periods[i]
        # Build a window: current week + up to 3 prior weeks (most recent first)
        window_start = max(0, i - 3)
        # Reverse so index 0 = current week (most recent)
        window = list(reversed(running_periods[window_start : i + 1]))
        load = calculate_training_load(window)
        results.append({
            "week_start": week_starts[i].isoformat(),
            "label": rp.label,
            "weekly_rss": rp.total_rss,
            "acute_load": load.acute_load,
            "chronic_load": load.chronic_load,
            "acwr": load.acwr,
            "load_status": load.load_status,
        })
    return results


# ---------------------------------------------------------------------------
# Build complete data.json structure
# ---------------------------------------------------------------------------


def build_charts_data(
    training_records: list[dict[str, Any]],
    health_records: list[dict[str, Any]],
    today: date,
) -> dict[str, Any]:
    """Pure function: raw Notion records -> complete data.json structure."""
    # Determine date range
    all_dates: list[date] = []
    for r in training_records:
        d = r.get("date")
        if d:
            all_dates.append(date.fromisoformat(str(d)[:10]))
    for r in health_records:
        d = r.get("date")
        if d:
            all_dates.append(date.fromisoformat(str(d)[:10]))

    if not all_dates:
        return {
            "generated_at": datetime.now(tz=UTC).isoformat(),
            "meta": {
                "total_training": 0,
                "total_health": 0,
                "earliest": None,
                "latest": None,
            },
            "sessions": [],
            "health": [],
            "weekly": {
                "training": [],
                "health": [],
                "running": [],
                "load": [],
            },
        }

    earliest = min(all_dates)
    latest = max(all_dates)

    # Build weekly periods from earliest Monday to today
    first_monday = earliest - timedelta(days=earliest.weekday())
    current_monday = today - timedelta(days=today.weekday())

    week_boundaries: list[tuple[date, date, str]] = []
    week_starts: list[date] = []
    monday = first_monday
    while monday <= current_monday:
        sunday = monday + timedelta(days=6)
        label = f"{monday.strftime('%b %d')} – {sunday.strftime('%b %d')}"
        week_boundaries.append((monday, sunday, label))
        week_starts.append(monday)
        monday += timedelta(weeks=1)

    # Reverse to get most recent first (matching get_period_boundaries convention)
    week_boundaries_rev = list(reversed(week_boundaries))

    # Group records into weeks
    training_by_week = group_by_period(training_records, week_boundaries_rev)
    health_by_week = group_by_period(health_records, week_boundaries_rev)

    # Calculate weekly aggregates (most recent first)
    training_weeks = [
        calculate_training_week(records, label)
        for records, (_s, _e, label) in zip(
            training_by_week, week_boundaries_rev, strict=True
        )
    ]
    health_weeks = [
        calculate_health_week(records, label)
        for records, (_s, _e, label) in zip(
            health_by_week, week_boundaries_rev, strict=True
        )
    ]
    running_periods = [
        calculate_running_period(records, label)
        for records, (_s, _e, label) in zip(
            training_by_week, week_boundaries_rev, strict=True
        )
    ]

    # Reverse back to chronological for rolling ACWR
    running_periods_chrono = list(reversed(running_periods))
    week_starts_list = list(week_starts)  # already chronological

    load_data = compute_rolling_acwr(running_periods_chrono, week_starts_list)

    # Serialize weekly data (chronological, oldest first)
    training_weeks_chrono = list(reversed(training_weeks))
    health_weeks_chrono = list(reversed(health_weeks))

    weekly_training = []
    for i, tw in enumerate(training_weeks_chrono):
        d = asdict(tw)
        d["week_start"] = week_starts_list[i].isoformat()
        weekly_training.append(d)

    weekly_health = []
    for i, hw in enumerate(health_weeks_chrono):
        d = asdict(hw)
        d["week_start"] = week_starts_list[i].isoformat()
        weekly_health.append(d)

    weekly_running = []
    for i, rp in enumerate(running_periods_chrono):
        d = asdict(rp)
        d["week_start"] = week_starts_list[i].isoformat()
        weekly_running.append(d)

    # Serialize individual records
    sessions = []
    for r in training_records:
        sessions.append({
            "date": r.get("date"),
            "name": r.get("name"),
            "training_type": r.get("training_type"),
            "duration_min": r.get("duration_min"),
            "distance_km": r.get("distance_km"),
            "volume_kg": r.get("volume_kg"),
            "feeling": r.get("feeling"),
            "avg_hr": r.get("avg_hr"),
            "power_w": r.get("power_w"),
            "rss": r.get("rss"),
            "critical_power_w": r.get("critical_power_w"),
            "cadence_spm": r.get("cadence_spm"),
            "stride_length_m": r.get("stride_length_m"),
            "ground_contact_ms": r.get("ground_contact_ms"),
            "vertical_oscillation_cm": r.get("vertical_oscillation_cm"),
            "leg_spring_stiffness": r.get("leg_spring_stiffness"),
            "rpe": r.get("rpe"),
            "source": r.get("source"),
        })

    health = []
    for r in health_records:
        health.append({
            "date": r.get("date"),
            "sleep_hours": r.get("sleep_hours"),
            "sleep_quality": r.get("sleep_quality"),
            "resting_hr": r.get("resting_hr"),
            "steps": r.get("steps"),
            "body_battery": r.get("body_battery"),
        })

    return {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "meta": {
            "total_training": len(training_records),
            "total_health": len(health_records),
            "earliest": earliest.isoformat(),
            "latest": latest.isoformat(),
        },
        "sessions": sessions,
        "health": health,
        "weekly": {
            "training": weekly_training,
            "health": weekly_health,
            "running": weekly_running,
            "load": load_data,
        },
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate JSON data for the fitness dashboard"
    )
    parser.add_argument(
        "--output",
        "-o",
        default="site/data.json",
        help="Output path for data.json (default: site/data.json)",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and compute but don't write file",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    load_dotenv()

    training_db_id = os.environ.get("NOTION_TRAINING_DB_ID")
    health_db_id = os.environ.get("NOTION_HEALTH_DB_ID")

    missing: list[str] = []
    if not training_db_id:
        missing.append("NOTION_TRAINING_DB_ID")
    if not health_db_id:
        missing.append("NOTION_HEALTH_DB_ID")
    if not os.environ.get("NOTION_API_KEY"):
        missing.append("NOTION_API_KEY")
    if missing:
        logger.error("Missing required environment variables: %s", ", ".join(missing))
        raise SystemExit(1)

    config = DashboardConfig(
        training_db_id=training_db_id,  # type: ignore[arg-type]
        health_db_id=health_db_id,  # type: ignore[arg-type]
        dashboard_page_id="",  # unused by fetch functions
    )

    today = date.today()

    # Fetch up to 2 years of data
    year_periods = get_period_boundaries(today, "year", 2)
    earliest_date = year_periods[-1][0]

    logger.info("Fetching data from %s to %s", earliest_date, today)

    try:
        client = NotionClient()
    except ConfigurationError as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from exc

    training_records = fetch_training_data(client, config, earliest_date)
    health_records = fetch_health_data(client, config, earliest_date)

    logger.info(
        "Fetched %d training records, %d health records",
        len(training_records),
        len(health_records),
    )

    data = build_charts_data(training_records, health_records, today)

    logger.info(
        "Generated data: %d sessions, %d health, %d weekly periods",
        len(data["sessions"]),
        len(data["health"]),
        len(data["weekly"]["training"]),
    )

    if args.dry_run:
        logger.info("[DRY RUN] Would write %d bytes to %s", len(json.dumps(data)), args.output)
        return

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(data, f, indent=2)

    logger.info("Wrote %s", args.output)


if __name__ == "__main__":
    main()
