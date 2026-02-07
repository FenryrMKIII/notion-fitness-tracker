#!/usr/bin/env python3
"""Sync activities, sleep, and steps from Garmin Connect to Notion."""

import argparse
import logging
import os
import sys
from datetime import date, timedelta

import requests
from dotenv import load_dotenv
from garminconnect import Garmin

load_dotenv()

NOTION_API_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

logger = logging.getLogger(__name__)


def get_notion_headers():
    api_key = os.environ.get("NOTION_API_KEY")
    if not api_key:
        logger.error("NOTION_API_KEY not set")
        sys.exit(1)
    return {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def get_db_id():
    return os.environ.get("NOTION_TRAINING_DB_ID", "13d713283dd14cd89ba1eb7ac77db89f")


def get_garmin_client():
    """Authenticate with Garmin Connect."""
    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")
    if not email or not password:
        logger.error("GARMIN_EMAIL and GARMIN_PASSWORD must be set")
        sys.exit(1)

    client = Garmin(email, password)
    client.login()
    return client


def check_existing(external_id):
    """Check if an entry with this External ID already exists in Notion."""
    db_id = get_db_id()
    resp = requests.post(
        f"{NOTION_API_URL}/databases/{db_id}/query",
        headers=get_notion_headers(),
        json={
            "filter": {
                "property": "External ID",
                "rich_text": {"equals": external_id},
            }
        },
        timeout=30,
    )
    resp.raise_for_status()
    return len(resp.json().get("results", [])) > 0


def garmin_type_to_training_type(activity_type):
    """Map Garmin activity types to Training Session types."""
    mapping = {
        "running": "Running",
        "trail_running": "Running",
        "treadmill_running": "Running",
        "cycling": "Running",  # fallback
        "walking": "Mobility",
        "strength_training": "Gym-Strength",
        "hiit": "Gym-Crossfit",
    }
    return mapping.get(activity_type.lower(), "Specifics")


def sync_activities(client, target_date):
    """Sync Garmin activities for a given date."""
    activities = client.get_activities_by_date(
        target_date.isoformat(), target_date.isoformat()
    )

    synced = 0
    for activity in activities:
        activity_id = str(activity.get("activityId", ""))
        external_id = f"garmin-{activity_id}"

        if check_existing(external_id):
            logger.info("Skipping activity %s (already exists)", activity.get("activityName"))
            continue

        duration_min = round(activity.get("duration", 0) / 60)
        distance_km = round(activity.get("distance", 0) / 1000, 2)
        avg_hr = activity.get("averageHR")
        activity_type = activity.get("activityType", {}).get("typeKey", "other")

        properties = {
            "Name": {"title": [{"text": {"content": activity.get("activityName", "Garmin Activity")}}]},
            "Date": {"date": {"start": target_date.isoformat()}},
            "Training Type": {"select": {"name": garmin_type_to_training_type(activity_type)}},
            "Duration (min)": {"number": duration_min},
            "Source": {"select": {"name": "Garmin"}},
            "External ID": {"rich_text": [{"text": {"content": external_id}}]},
        }

        if distance_km > 0:
            properties["Distance (km)"] = {"number": distance_km}
        if avg_hr:
            properties["Avg Heart Rate"] = {"number": int(avg_hr)}

        notes_parts = []
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

        resp = requests.post(
            f"{NOTION_API_URL}/pages",
            headers=get_notion_headers(),
            json={"parent": {"database_id": get_db_id()}, "properties": properties},
            timeout=30,
        )
        resp.raise_for_status()
        logger.info("Synced activity: %s", activity.get("activityName"))
        synced += 1

    return synced


def sync_sleep_and_steps(client, target_date):
    """Log sleep and step data as notes. Creates a summary entry if notable."""
    try:
        sleep_data = client.get_sleep_data(target_date.isoformat())
        steps_data = client.get_steps_data(target_date.isoformat())
    except Exception as e:
        logger.warning("Could not fetch sleep/steps data: %s", e)
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
        target_date, sleep_minutes, sleep_quality, total_steps,
    )


def main():
    parser = argparse.ArgumentParser(description="Sync Garmin data to Notion")
    parser.add_argument(
        "--date", type=str,
        help="Date to sync (YYYY-MM-DD). Defaults to yesterday.",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    target_date = (
        date.fromisoformat(args.date) if args.date
        else date.today() - timedelta(days=1)
    )

    logger.info("Syncing Garmin data for %s", target_date)
    client = get_garmin_client()

    synced = sync_activities(client, target_date)
    sync_sleep_and_steps(client, target_date)

    logger.info("Done: %d activities synced", synced)


if __name__ == "__main__":
    main()
