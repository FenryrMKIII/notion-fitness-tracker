#!/usr/bin/env python3
"""Sync activities, sleep, and steps from Garmin Connect to Notion."""

import argparse
import logging
import os
from datetime import date, timedelta
from typing import Any

import requests
from dotenv import load_dotenv
from garminconnect import Garmin, GarminConnectAuthenticationError

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


def sync_sleep_and_steps(client: Garmin, target_date: date) -> None:
    """Fetch and log sleep/step data for *target_date*.

    TODO: This is currently a logging-only stub. To make it useful, build
    Notion page properties from the data below and call notion.create_page().
    """
    try:
        sleep_data = client.get_sleep_data(target_date.isoformat())
        steps_data = client.get_steps_data(target_date.isoformat())
    except (requests.RequestException, GarminConnectAuthenticationError) as exc:
        logger.warning("Could not fetch sleep/steps data: %s", exc)
        return

    sleep_minutes = 0
    sleep_quality = "Unknown"
    if sleep_data and sleep_data.get("dailySleepDTO"):
        dto = sleep_data["dailySleepDTO"]
        sleep_seconds = dto.get("sleepTimeSeconds", 0)
        sleep_minutes = round(sleep_seconds / 60)
        sleep_quality = dto.get("sleepQualityType", "Unknown")

    total_steps = 0
    if steps_data:
        for entry in steps_data:
            total_steps += entry.get("steps", 0)

    logger.info(
        "Date %s: Sleep=%d min (%s), Steps=%d",
        target_date,
        sleep_minutes,
        sleep_quality,
        total_steps,
    )


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

    target_date: date = args.date if args.date else date.today() - timedelta(days=1)

    logger.info("Syncing Garmin data for %s", target_date)

    synced = sync_activities(client, notion, target_date)
    sync_sleep_and_steps(client, target_date)

    logger.info("Done: %d activities synced", synced)


if __name__ == "__main__":
    main()
