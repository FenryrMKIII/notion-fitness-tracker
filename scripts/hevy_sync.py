#!/usr/bin/env python3
"""Sync workouts from Hevy API to Notion Training Sessions database."""

import argparse
import logging
import os
from datetime import date, datetime
from typing import Any

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from scripts.notion_client import ConfigurationError, NotionClient

HEVY_API_URL = "https://api.hevyapp.com/v1"
NOTION_RICH_TEXT_MAX_LENGTH = 2000

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Hevy API helpers
# ---------------------------------------------------------------------------


def _build_hevy_session() -> requests.Session:
    """Create a requests.Session with retry/backoff for Hevy API calls."""
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def get_hevy_headers() -> dict[str, str]:
    """Return Hevy API headers.  Raises ConfigurationError if the key is missing."""
    api_key = os.environ.get("HEVY_API_KEY")
    if not api_key:
        raise ConfigurationError("HEVY_API_KEY environment variable is not set")
    return {"api-key": api_key}


def fetch_hevy_workouts(
    session: requests.Session,
    headers: dict[str, str],
    page: int = 1,
    page_size: int = 10,
) -> dict[str, Any]:
    """Fetch workouts from Hevy API."""
    resp = session.get(
        f"{HEVY_API_URL}/workouts",
        headers=headers,
        params={"page": page, "pageSize": page_size},
        timeout=30,
    )
    resp.raise_for_status()
    result: dict[str, Any] = resp.json()
    return result


# ---------------------------------------------------------------------------
# Data formatting helpers
# ---------------------------------------------------------------------------


def format_exercise_details(exercises: list[dict[str, Any]]) -> str:
    """Format exercises into a readable text summary."""
    parts: list[str] = []
    for ex in exercises:
        sets_str: list[str] = []
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

        title = ex.get("title", "Unknown Exercise")
        parts.append(f"{title}: {', '.join(sets_str)}")
    return " | ".join(parts)


def calculate_volume(exercises: list[dict[str, Any]]) -> float:
    """Calculate total volume (weight x reps) across all exercises."""
    total = 0.0
    for ex in exercises:
        for s in ex.get("sets", []):
            weight = s.get("weight_kg", 0) or 0
            reps = s.get("reps", 0) or 0
            total += weight * reps
    return round(total, 1)


def calculate_duration_min(start_time: str, end_time: str) -> int:
    """Calculate duration in minutes from ISO timestamps."""
    start = datetime.fromisoformat(start_time)
    end = datetime.fromisoformat(end_time)
    return round((end - start).total_seconds() / 60)


# ---------------------------------------------------------------------------
# Notion sync
# ---------------------------------------------------------------------------


def create_notion_entry(
    notion: NotionClient,
    workout: dict[str, Any],
) -> dict[str, Any]:
    """Create a Training Sessions entry in Notion for a Hevy workout."""
    exercises: list[dict[str, Any]] = workout.get("exercises", [])
    start_time: str = workout.get("start_time", "")
    end_time: str = workout.get("end_time", "")
    date_str = start_time[:10]

    properties: dict[str, Any] = {
        "Name": {
            "title": [{"text": {"content": workout.get("title", "Hevy Workout")}}]
        },
        "Date": {"date": {"start": date_str}},
        "Training Type": {"select": {"name": "Gym-Strength"}},
        "Duration (min)": {"number": calculate_duration_min(start_time, end_time)},
        "Source": {"select": {"name": "Hevy"}},
        "External ID": {
            "rich_text": [{"text": {"content": workout.get("id", "")}}]
        },
        "Volume (kg)": {"number": calculate_volume(exercises)},
        "Exercise Details": {
            "rich_text": [
                {
                    "text": {
                        "content": format_exercise_details(exercises)[
                            :NOTION_RICH_TEXT_MAX_LENGTH
                        ]
                    }
                }
            ]
        },
    }

    notes_parts: list[str] = []
    for ex in exercises:
        if ex.get("notes"):
            title = ex.get("title", "Unknown Exercise")
            notes_parts.append(f"{title}: {ex['notes']}")
    if notes_parts:
        properties["Notes"] = {
            "rich_text": [
                {
                    "text": {
                        "content": " | ".join(notes_parts)[
                            :NOTION_RICH_TEXT_MAX_LENGTH
                        ]
                    }
                }
            ]
        }

    return notion.create_page(properties)


def sync_workouts(
    notion: NotionClient,
    hevy_session: requests.Session,
    hevy_headers: dict[str, str],
    full: bool = False,
    since: date | None = None,
) -> tuple[int, int]:
    """Sync workouts from Hevy to Notion."""
    page = 1
    synced = 0
    skipped = 0

    while True:
        data = fetch_hevy_workouts(hevy_session, hevy_headers, page=page, page_size=10)
        workouts: list[dict[str, Any]] = data.get("workouts", [])
        page_count: int = data.get("page_count", 1)

        if not workouts:
            break

        for workout in workouts:
            workout_id: str = workout.get("id", "")
            workout_date: str = workout.get("start_time", "")[:10]

            if since and workout_date < since.isoformat():
                logger.info("Reached workouts before %s, stopping", since)
                return synced, skipped

            if notion.check_existing(workout_id):
                logger.info(
                    "Skipping %s (already exists)", workout.get("title", "unknown")
                )
                skipped += 1
                continue

            logger.info(
                "Syncing: %s (%s)", workout.get("title", "unknown"), workout_date
            )
            create_notion_entry(notion, workout)
            synced += 1

        if not full or page >= page_count:
            break
        page += 1

    return synced, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Hevy workouts to Notion")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Sync all workouts (not just latest page)",
    )
    parser.add_argument(
        "--since",
        type=date.fromisoformat,
        help="Only sync workouts after this date (YYYY-MM-DD)",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    load_dotenv()

    try:
        notion = NotionClient()
        hevy_headers = get_hevy_headers()
    except ConfigurationError as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from exc

    hevy_session = _build_hevy_session()

    logger.info("Starting Hevy -> Notion sync")
    synced, skipped = sync_workouts(
        notion, hevy_session, hevy_headers, full=args.full, since=args.since
    )
    logger.info("Done: %d synced, %d skipped", synced, skipped)


if __name__ == "__main__":
    main()
