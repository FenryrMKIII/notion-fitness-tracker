#!/usr/bin/env python3
"""Sync activities, sleep, and steps from Garmin Connect to Notion."""

import argparse
import logging
import os
from datetime import date, timedelta
from typing import Any

from dotenv import load_dotenv
from garminconnect import Garmin

from scripts.notion_client import ConfigurationError, NotionClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Activity-type mapping
# ---------------------------------------------------------------------------

GARMIN_TYPE_MAPPING: dict[str, str] = {
    "running": "Running",
    "trail_running": "Running",
    "treadmill_running": "Running",
    "cycling": "Specifics",
    "walking": "Mobility",
    "strength_training": "Gym-Strength",
    "hiit": "Gym-Crossfit",
}


def garmin_type_to_training_type(activity_type: str) -> str:
    """Map Garmin activity types to Training Session types."""
    return GARMIN_TYPE_MAPPING.get(activity_type.lower(), "Specifics")


# ---------------------------------------------------------------------------
# Garmin client
# ---------------------------------------------------------------------------


def get_garmin_client() -> Garmin:
    """Authenticate with Garmin Connect.  Raises ConfigurationError on missing creds."""
    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")
    if not email or not password:
        raise ConfigurationError(
            "GARMIN_EMAIL and GARMIN_PASSWORD environment variables must be set"
        )

    client = Garmin(email, password)
    client.login()
    return client


# ---------------------------------------------------------------------------
# Sync helpers
# ---------------------------------------------------------------------------


def sync_activities(
    client: Garmin,
    notion: NotionClient,
    target_date: date,
) -> int:
    """Sync Garmin activities for a given date."""
    activities: list[dict[str, Any]] = client.get_activities_by_date(
        target_date.isoformat(), target_date.isoformat()
    )

    synced = 0
    for activity in activities:
        activity_id = str(activity.get("activityId", ""))
        external_id = f"garmin-{activity_id}"

        if notion.check_existing(external_id):
            logger.info(
                "Skipping activity %s (already exists)",
                activity.get("activityName"),
            )
            continue

        duration_min = round(activity.get("duration", 0) / 60)
        distance_km = round(activity.get("distance", 0) / 1000, 2)
        avg_hr = activity.get("averageHR")
        activity_type: str = activity.get("activityType", {}).get("typeKey", "other")

        properties: dict[str, Any] = {
            "Name": {
                "title": [
                    {
                        "text": {
                            "content": activity.get(
                                "activityName", "Garmin Activity"
                            )
                        }
                    }
                ]
            },
            "Date": {"date": {"start": target_date.isoformat()}},
            "Training Type": {
                "select": {"name": garmin_type_to_training_type(activity_type)}
            },
            "Duration (min)": {"number": duration_min},
            "Source": {"select": {"name": "Garmin"}},
            "External ID": {"rich_text": [{"text": {"content": external_id}}]},
        }

        if distance_km > 0:
            properties["Distance (km)"] = {"number": distance_km}
        if avg_hr:
            properties["Avg Heart Rate"] = {"number": int(avg_hr)}

        notes_parts: list[str] = []
        calories = activity.get("calories")
        if calories:
            notes_parts.append(f"Calories: {calories}")
        max_hr = activity.get("maxHR")
        if max_hr:
            notes_parts.append(f"Max HR: {max_hr}")
        if notes_parts:
            properties["Notes"] = {
                "rich_text": [{"text": {"content": " | ".join(notes_parts)}}]
            }

        notion.create_page(properties)
        logger.info("Synced activity: %s", activity.get("activityName"))
        synced += 1

    return synced


# ---------------------------------------------------------------------------
# Health data extraction (pure functions)
# ---------------------------------------------------------------------------


def extract_sleep_data(
    sleep_data: dict[str, Any] | None,
) -> tuple[float | None, str | None]:
    """Extract sleep hours and quality from Garmin sleep data.

    Returns (hours, quality) where quality is one of EXCELLENT/GOOD/FAIR/POOR.
    """
    if not sleep_data or not sleep_data.get("dailySleepDTO"):
        return None, None
    dto = sleep_data["dailySleepDTO"]
    sleep_seconds = dto.get("sleepTimeSeconds") or 0
    if sleep_seconds == 0:
        return None, None
    hours = round(sleep_seconds / 3600, 1)
    quality = dto.get("sleepQualityType")
    return hours, quality


def extract_steps(steps_data: list[dict[str, Any]] | None) -> int | None:
    """Extract total steps from Garmin steps data."""
    if not steps_data:
        return None
    total = sum(entry.get("steps", 0) for entry in steps_data)
    return total if total > 0 else None


def extract_resting_hr(rhr_data: dict[str, Any] | None) -> int | None:
    """Extract resting heart rate from Garmin RHR data."""
    if not rhr_data:
        return None
    rhr = rhr_data.get("restingHeartRate")
    if rhr is None:
        return None
    return int(rhr)


def extract_body_battery(
    battery_data: list[dict[str, Any]] | None,
) -> int | None:
    """Extract max body battery from Garmin body battery data."""
    if not battery_data:
        return None
    charged = [
        entry.get("charged", 0)
        for entry in battery_data
        if entry.get("charged") is not None
    ]
    return max(charged) if charged else None


# ---------------------------------------------------------------------------
# Health properties builder
# ---------------------------------------------------------------------------


def build_health_properties(
    target_date: date,
    sleep_hours: float | None,
    sleep_quality: str | None,
    steps: int | None,
    resting_hr: int | None,
    body_battery: int | None,
) -> dict[str, Any]:
    """Build Notion page properties for a Health Status Log entry."""
    date_str = target_date.isoformat()
    external_id = f"garmin-health-{date_str}"

    properties: dict[str, Any] = {
        "Date Label": {
            "title": [{"text": {"content": f"Health Log — {date_str}"}}]
        },
        "Date": {"date": {"start": date_str}},
        "External ID": {"rich_text": [{"text": {"content": external_id}}]},
    }

    if sleep_hours is not None:
        properties["Sleep Duration (h)"] = {"number": sleep_hours}
    if sleep_quality is not None:
        properties["Sleep Quality"] = {"select": {"name": sleep_quality}}
    if steps is not None:
        properties["Steps"] = {"number": steps}
    if resting_hr is not None:
        properties["Resting HR"] = {"number": resting_hr}
    if body_battery is not None:
        properties["Body Battery"] = {"number": body_battery}

    return properties


# ---------------------------------------------------------------------------
# Health sync
# ---------------------------------------------------------------------------


def sync_sleep_and_steps(
    client: Garmin, notion: NotionClient, target_date: date
) -> None:
    """Fetch health data from Garmin and create a Health Status Log entry."""
    health_db_id = os.environ.get("NOTION_HEALTH_DB_ID")
    if not health_db_id:
        logger.warning(
            "NOTION_HEALTH_DB_ID not set — skipping health data sync"
        )
        return

    external_id = f"garmin-health-{target_date.isoformat()}"
    if notion.check_existing_in_db(health_db_id, external_id):
        logger.info("Health log for %s already exists, skipping", target_date)
        return

    # Fetch each endpoint independently
    sleep_data: dict[str, Any] | None = None
    try:
        sleep_data = client.get_sleep_data(target_date.isoformat())
    except Exception as exc:
        logger.warning("Could not fetch sleep data: %s", exc)

    steps_data: list[dict[str, Any]] | None = None
    try:
        steps_data = client.get_steps_data(target_date.isoformat())
    except Exception as exc:
        logger.warning("Could not fetch steps data: %s", exc)

    rhr_data: dict[str, Any] | None = None
    try:
        rhr_data = client.get_rhr_day(target_date.isoformat())
    except Exception as exc:
        logger.warning("Could not fetch resting HR data: %s", exc)

    battery_data: list[dict[str, Any]] | None = None
    try:
        battery_data = client.get_body_battery(target_date.isoformat())
    except Exception as exc:
        logger.warning("Could not fetch body battery data: %s", exc)

    # Extract values
    sleep_hours, sleep_quality = extract_sleep_data(sleep_data)
    steps = extract_steps(steps_data)
    resting_hr = extract_resting_hr(rhr_data)
    body_battery = extract_body_battery(battery_data)

    logger.info(
        "Date %s: Sleep=%.1fh (%s), Steps=%s, RHR=%s, Battery=%s",
        target_date,
        sleep_hours or 0,
        sleep_quality or "N/A",
        steps or "N/A",
        resting_hr or "N/A",
        body_battery or "N/A",
    )

    properties = build_health_properties(
        target_date, sleep_hours, sleep_quality, steps, resting_hr, body_battery
    )
    notion.create_page_in_db(health_db_id, properties)
    logger.info("Created health log for %s", target_date)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Garmin data to Notion")
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        help="Date to sync (YYYY-MM-DD). Defaults to yesterday.",
    )
    parser.add_argument(
        "--days",
        type=int,
        help="Number of days to sync (counting back from --date or yesterday).",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    load_dotenv()

    try:
        notion = NotionClient()
        client = get_garmin_client()
    except ConfigurationError as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from exc

    end_date: date = args.date if args.date else date.today() - timedelta(days=1)
    num_days: int = args.days if args.days else 1
    start_date = end_date - timedelta(days=num_days - 1)

    logger.info("Syncing Garmin data from %s to %s (%d days)", start_date, end_date, num_days)

    total_synced = 0
    failed_days: list[date] = []
    current = start_date
    while current <= end_date:
        logger.info("--- %s ---", current)
        try:
            synced = sync_activities(client, notion, current)
            sync_sleep_and_steps(client, notion, current)
            total_synced += synced
        except Exception as exc:
            logger.error("Failed to sync %s: %s", current, exc)
            failed_days.append(current)
        current += timedelta(days=1)

    logger.info("Done: %d activities synced across %d days", total_synced, num_days)
    if failed_days:
        logger.warning("Failed days: %s", ", ".join(d.isoformat() for d in failed_days))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
