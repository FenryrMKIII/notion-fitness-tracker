#!/usr/bin/env python3
"""Sync workouts from Hevy API to Notion Training Sessions database."""

import argparse
import logging
import os
import sys
from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv()

HEVY_API_URL = "https://api.hevyapp.com/v1"
NOTION_API_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

logger = logging.getLogger(__name__)


def get_hevy_headers():
    api_key = os.environ.get("HEVY_API_KEY")
    if not api_key:
        logger.error("HEVY_API_KEY not set")
        sys.exit(1)
    return {"api-key": api_key}


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
    db_id = os.environ.get("NOTION_TRAINING_DB_ID", "13d713283dd14cd89ba1eb7ac77db89f")
    return db_id


def fetch_hevy_workouts(page=1, page_size=10):
    """Fetch workouts from Hevy API."""
    resp = requests.get(
        f"{HEVY_API_URL}/workouts",
        headers=get_hevy_headers(),
        params={"page": page, "pageSize": page_size},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def check_existing(external_id):
    """Check if a workout with this External ID already exists in Notion."""
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


def format_exercise_details(exercises):
    """Format exercises into a readable text summary."""
    parts = []
    for ex in exercises:
        sets_str = []
        for s in ex.get("sets", []):
            weight = s.get("weight_kg", 0) or 0
            reps = s.get("reps")
            distance = s.get("distance_meters")
            duration = s.get("duration_seconds")

            if reps is not None:
                sets_str.append(f"{weight}x{reps}")
            elif distance is not None:
                sets_str.append(f"{weight}kg x {distance}m")
            elif duration is not None:
                sets_str.append(f"{weight}kg x {duration}s")
            else:
                sets_str.append(f"{weight}kg")

        parts.append(f"{ex['title']}: {', '.join(sets_str)}")
    return " | ".join(parts)


def calculate_volume(exercises):
    """Calculate total volume (weight x reps) across all exercises."""
    total = 0.0
    for ex in exercises:
        for s in ex.get("sets", []):
            weight = s.get("weight_kg", 0) or 0
            reps = s.get("reps", 0) or 0
            total += weight * reps
    return round(total, 1)


def calculate_duration_min(start_time, end_time):
    """Calculate duration in minutes from ISO timestamps."""
    fmt = "%Y-%m-%dT%H:%M:%S%z"
    start = datetime.fromisoformat(start_time)
    end = datetime.fromisoformat(end_time)
    return round((end - start).total_seconds() / 60)


def create_notion_entry(workout):
    """Create a Training Sessions entry in Notion for a Hevy workout."""
    db_id = get_db_id()
    exercises = workout.get("exercises", [])
    start_time = workout["start_time"]
    end_time = workout["end_time"]
    date_str = start_time[:10]

    properties = {
        "Name": {"title": [{"text": {"content": workout["title"]}}]},
        "Date": {"date": {"start": date_str}},
        "Training Type": {"select": {"name": "Gym-Strength"}},
        "Duration (min)": {"number": calculate_duration_min(start_time, end_time)},
        "Source": {"select": {"name": "Hevy"}},
        "External ID": {"rich_text": [{"text": {"content": workout["id"]}}]},
        "Volume (kg)": {"number": calculate_volume(exercises)},
        "Exercise Details": {
            "rich_text": [{"text": {"content": format_exercise_details(exercises)[:2000]}}]
        },
    }

    notes_parts = []
    for ex in exercises:
        if ex.get("notes"):
            notes_parts.append(f"{ex['title']}: {ex['notes']}")
    if notes_parts:
        properties["Notes"] = {
            "rich_text": [{"text": {"content": " | ".join(notes_parts)[:2000]}}]
        }

    resp = requests.post(
        f"{NOTION_API_URL}/pages",
        headers=get_notion_headers(),
        json={"parent": {"database_id": db_id}, "properties": properties},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def sync_workouts(full=False, since=None):
    """Sync workouts from Hevy to Notion."""
    page = 1
    synced = 0
    skipped = 0

    while True:
        data = fetch_hevy_workouts(page=page, page_size=10)
        workouts = data.get("workouts", [])
        page_count = data.get("page_count", 1)

        if not workouts:
            break

        for workout in workouts:
            workout_id = workout["id"]
            workout_date = workout["start_time"][:10]

            if since and workout_date < since:
                logger.info("Reached workouts before %s, stopping", since)
                return synced, skipped

            if check_existing(workout_id):
                logger.info("Skipping %s (already exists)", workout["title"])
                skipped += 1
                continue

            logger.info("Syncing: %s (%s)", workout["title"], workout_date)
            create_notion_entry(workout)
            synced += 1

        if not full or page >= page_count:
            break
        page += 1

    return synced, skipped


def main():
    parser = argparse.ArgumentParser(description="Sync Hevy workouts to Notion")
    parser.add_argument("--full", action="store_true", help="Sync all workouts (not just latest page)")
    parser.add_argument("--since", type=str, help="Only sync workouts after this date (YYYY-MM-DD)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    logger.info("Starting Hevy -> Notion sync")
    synced, skipped = sync_workouts(full=args.full, since=args.since)
    logger.info("Done: %d synced, %d skipped", synced, skipped)


if __name__ == "__main__":
    main()
