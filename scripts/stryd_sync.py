#!/usr/bin/env python3
"""Sync running activities from Stryd to Notion Training Sessions database.

Stryd provides power-based running metrics (watts, RSS, ground contact time, etc.)
that complement Garmin's distance/HR data. This script:
  - Fetches activity summaries from the Stryd API
  - Matches them to existing Garmin entries by date/time overlap
  - Updates matched entries with Stryd power data (complement mode)
  - Creates new entries for Stryd-only runs
"""

import argparse
import json
import logging
import os
from datetime import UTC, date, datetime, timedelta
from typing import Any

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from scripts.notion_client import ConfigurationError, NotionClient

STRYD_BASE_URL = "https://www.stryd.com/b"
STRYD_API_URL = "https://www.stryd.com/b/api/v1"

# Stryd "feel" field to our Feeling select mapping
FEEL_MAPPING: dict[str, str] = {
    "great": "Great",
    "good": "Good",
    "normal": "Good",
    "ok": "Good",
    "bad": "Tired",
    "terrible": "Exhausted",
}


# Maximum time difference (seconds) for matching a Stryd activity to a Garmin entry
MATCH_WINDOW_SECONDS = 30 * 60  # 30 minutes

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stryd API helpers
# ---------------------------------------------------------------------------


def _build_stryd_session() -> requests.Session:
    """Create a requests.Session with retry/backoff for Stryd API calls."""
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


def authenticate(
    session: requests.Session,
    email: str,
    password: str,
) -> str:
    """Authenticate with Stryd and return a bearer token."""
    resp = session.post(
        f"{STRYD_BASE_URL}/email/signin",
        json={"email": email, "password": password},
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Stryd authentication failed (HTTP {resp.status_code})")
    data: dict[str, Any] = resp.json()
    token: str = data["token"]
    return token


def fetch_activities(
    session: requests.Session,
    token: str,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    """Fetch activity summaries from Stryd for a date range."""
    headers = {"Authorization": f"Bearer: {token}"}
    params = {
        "srtDate": start_date.strftime("%m-%d-%Y"),
        "endDate": end_date.strftime("%m-%d-%Y"),
        "sortBy": "StartDate",
    }
    resp = session.get(
        f"{STRYD_API_URL}/users/calendar",
        headers=headers,
        params=params,
        timeout=30,
    )
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    activities: list[dict[str, Any]] = data.get("activities", [])
    return activities


# ---------------------------------------------------------------------------
# Data extraction (pure functions)
# ---------------------------------------------------------------------------


def extract_timestamp(activity: dict[str, Any]) -> datetime:
    """Extract the activity start time as a timezone-aware datetime."""
    ts = activity.get("timestamp", 0)
    return datetime.fromtimestamp(ts, tz=UTC)


def extract_date(activity: dict[str, Any]) -> date:
    """Extract the activity date."""
    return extract_timestamp(activity).date()


def extract_power_metrics(activity: dict[str, Any]) -> dict[str, float | int | None]:
    """Extract Stryd power and biomechanics metrics from an activity summary."""
    return {
        "power": _safe_round(activity.get("average_power"), 1),
        "ftp": _safe_round(activity.get("ftp"), 1),
        "rss": _safe_round(activity.get("stress"), 1),
        "cadence": _safe_int(activity.get("average_cadence")),
        "stride_length": _safe_round(activity.get("average_stride_length"), 2),
        "ground_contact": _safe_round(activity.get("average_ground_time"), 1),
        "vertical_oscillation": _safe_round(activity.get("average_oscillation"), 1),
        "leg_spring_stiffness": _safe_round(activity.get("average_leg_spring"), 1),
        "temperature": _safe_round(activity.get("temperature"), 1),
        "wind_speed": _safe_round(activity.get("windSpeed"), 1),
        "elevation_gain": _safe_round(activity.get("total_elevation_gain"), 1),
    }


def extract_rpe(activity: dict[str, Any]) -> int | None:
    """Extract RPE from the activity data.

    Stryd stores RPE as an integer (1-10 scale) in the 'rpe' field,
    entered by the user via the Post Run Report.
    Returns None if not set (0 means not entered).
    """
    val = activity.get("rpe")
    if val is not None and int(val) > 0:
        return int(val)
    return None


def extract_feel(activity: dict[str, Any]) -> str | None:
    """Extract the 'feel' field and map to Notion Feeling select values.

    Stryd values: great, good, normal, ok, bad, terrible.
    Falls back to RPE-based mapping if feel is not set.
    """
    feel = activity.get("feel", "")
    if not feel:
        return None
    return FEEL_MAPPING.get(feel.lower())


def _safe_float(val: float | int | str | None) -> float | None:
    """Convert to float or return None."""
    if val is None:
        return None
    try:
        f = float(val)
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


def _safe_int(val: float | int | str | None) -> int | None:
    """Convert to int or return None."""
    if val is None:
        return None
    try:
        i = int(val)
        return i if i > 0 else None
    except (ValueError, TypeError):
        return None


def _safe_round(val: float | int | str | None, decimals: int) -> float | None:
    """Convert to float, round, or return None."""
    f = _safe_float(val)
    return round(f, decimals) if f is not None else None


# ---------------------------------------------------------------------------
# Notion property builders (pure functions)
# ---------------------------------------------------------------------------


STRYD_METRIC_TO_NOTION: dict[str, str] = {
    "power": "Power (W)",
    "rss": "RSS",
    "ftp": "Critical Power (W)",
    "cadence": "Cadence (spm)",
    "stride_length": "Stride Length (m)",
    "ground_contact": "Ground Contact (ms)",
    "vertical_oscillation": "Vertical Oscillation (cm)",
    "leg_spring_stiffness": "Leg Spring Stiffness",
    "temperature": "Temperature (C)",
    "wind_speed": "Wind Speed",
}


def build_stryd_update_properties(
    metrics: dict[str, float | int | None],
    rpe: int | None = None,
    feel: str | None = None,
) -> dict[str, Any]:
    """Build Notion properties dict for updating an existing page with Stryd data."""
    props: dict[str, Any] = {}

    for key, notion_prop in STRYD_METRIC_TO_NOTION.items():
        val = metrics.get(key)
        if val is not None:
            props[notion_prop] = {"number": val}

    if rpe is not None:
        props["RPE"] = {"number": rpe}
    if feel is not None:
        props["Feeling"] = {"select": {"name": feel}}

    return props


def build_stryd_create_properties(
    activity: dict[str, Any],
    metrics: dict[str, float | int | None],
    rpe: int | None = None,
    feel: str | None = None,
) -> dict[str, Any]:
    """Build full Notion properties for a new Stryd-only Training Session entry."""
    ts = extract_timestamp(activity)
    date_str = ts.date().isoformat()
    external_id = f"stryd-{activity.get('timestamp', '')}"
    name = activity.get("name") or "Stryd Run"

    props: dict[str, Any] = {
        "Name": {"title": [{"text": {"content": name}}]},
        "Date": {"date": {"start": date_str}},
        "Training Type": {"select": {"name": "Running"}},
        "Source": {"select": {"name": "Stryd"}},
        "External ID": {"rich_text": [{"text": {"content": external_id}}]},
    }

    # Duration from moving_time (seconds → minutes)
    moving_time = activity.get("moving_time", 0)
    if moving_time and moving_time > 0:
        props["Duration (min)"] = {"number": round(moving_time / 60)}

    # Distance (meters → km)
    distance = activity.get("distance", 0)
    if distance and distance > 0:
        props["Distance (km)"] = {"number": round(distance / 1000, 2)}

    # Heart rate from Stryd (comes from the watch via Stryd)
    avg_hr = activity.get("average_heart_rate")
    if avg_hr and int(avg_hr) > 0:
        props["Avg Heart Rate"] = {"number": int(avg_hr)}

    # Notes with elevation and surface info
    notes_parts: list[str] = []
    elevation = metrics.get("elevation_gain")
    if elevation:
        notes_parts.append(f"Elevation: +{elevation}m")
    surface = activity.get("surface_type", "")
    if surface:
        notes_parts.append(f"Surface: {surface}")
    run_type = activity.get("type", "")
    if run_type:
        notes_parts.append(f"Type: {run_type}")
    if notes_parts:
        props["Notes"] = {
            "rich_text": [{"text": {"content": " | ".join(notes_parts)}}]
        }

    # Merge power metrics + RPE + feel
    update_props = build_stryd_update_properties(metrics, rpe, feel)
    props.update(update_props)

    return props


# ---------------------------------------------------------------------------
# Matching logic
# ---------------------------------------------------------------------------


def find_garmin_match(
    notion: NotionClient,
    activity_time: datetime,
    db_id: str,
) -> str | None:
    """Find a Garmin Training Session entry that matches the Stryd activity time.

    Searches for Garmin entries on the same date, then checks if any start
    within the MATCH_WINDOW_SECONDS of the Stryd timestamp.
    Returns the Notion page ID if found, None otherwise.
    """
    target_date = activity_time.date().isoformat()

    results = notion.query_database(
        db_id,
        filter_obj={
            "and": [
                {"property": "Date", "date": {"equals": target_date}},
                {"property": "Source", "select": {"equals": "Garmin"}},
                {"property": "Training Type", "select": {"equals": "Running"}},
            ]
        },
    )

    if not results:
        return None

    # If there's exactly one Garmin running entry on this date, match it
    if len(results) == 1:
        page_id: str = results[0]["id"]
        return page_id

    # Multiple Garmin runs on same day — shouldn't be common, take the first
    logger.warning(
        "Multiple Garmin running entries on %s, matching first one", target_date
    )
    first_id: str = results[0]["id"]
    return first_id


# ---------------------------------------------------------------------------
# Sync orchestration
# ---------------------------------------------------------------------------


def sync_activities(
    notion: NotionClient,
    stryd_session: requests.Session,
    token: str,
    start_date: date,
    end_date: date,
    debug: bool = False,
) -> tuple[int, int, int]:
    """Sync Stryd activities to Notion.

    Returns (updated, created, skipped) counts.
    """
    activities = fetch_activities(stryd_session, token, start_date, end_date)
    logger.info("Fetched %d activities from Stryd", len(activities))

    if debug and activities:
        logger.info(
            "DEBUG — Raw first activity JSON:\n%s",
            json.dumps(activities[0], indent=2, default=str),
        )
        # Log all keys to discover RPE and other fields
        logger.info("DEBUG — Activity keys: %s", list(activities[0].keys()))

    db_id = notion.get_db_id()
    updated = 0
    created = 0
    skipped = 0

    for activity in activities:
        ts = extract_timestamp(activity)
        external_id = f"stryd-{activity.get('timestamp', '')}"

        # Skip if already synced
        if notion.check_existing(external_id):
            logger.debug("Skipping stryd activity at %s (already synced)", ts)
            skipped += 1
            continue

        metrics = extract_power_metrics(activity)
        rpe = extract_rpe(activity)
        feel = extract_feel(activity)

        if debug:
            logger.info(
                "DEBUG — Metrics for %s: %s, RPE: %s, Feel: %s",
                ts, metrics, rpe, feel,
            )

        # Skip activities with no real power data (near-zero entries)
        if metrics.get("power") is None:
            logger.debug("Skipping activity at %s (no power data)", ts)
            skipped += 1
            continue

        # Try to find a matching Garmin entry to enrich
        garmin_page_id = find_garmin_match(notion, ts, db_id)

        if garmin_page_id:
            update_props = build_stryd_update_properties(metrics, rpe, feel)
            if update_props:
                notion.update_page(garmin_page_id, update_props)
                logger.info("Updated Garmin entry for %s with Stryd data", ts.date())
                updated += 1
            else:
                logger.info("No Stryd metrics to add for %s", ts.date())
                skipped += 1
        else:
            # No Garmin match — create a Stryd-only entry
            props = build_stryd_create_properties(activity, metrics, rpe, feel)
            notion.create_page(props)
            logger.info("Created Stryd-only entry for %s", ts.date())
            created += 1

    return updated, created, skipped


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def get_stryd_credentials() -> tuple[str, str]:
    """Return (email, password) from environment. Raises on missing."""
    email = os.environ.get("STRYD_EMAIL")
    password = os.environ.get("STRYD_PASSWORD")
    if not email or not password:
        raise ConfigurationError(
            "STRYD_EMAIL and STRYD_PASSWORD environment variables must be set"
        )
    return email, password


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync Stryd running data to Notion"
    )
    parser.add_argument(
        "--since",
        type=date.fromisoformat,
        help="Sync activities from this date (YYYY-MM-DD). Default: 7 days ago.",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Sync all historical activities",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Dump raw Stryd API responses to log (discover RPE fields)",
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
        email, password = get_stryd_credentials()
    except ConfigurationError as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from exc

    stryd_session = _build_stryd_session()

    logger.info("Authenticating with Stryd...")
    token = authenticate(stryd_session, email, password)
    logger.info("Stryd authenticated")

    end_date = date.today() + timedelta(days=1)  # include today
    if args.full:
        start_date = date(2020, 1, 1)
    elif args.since:
        start_date = args.since
    else:
        start_date = date.today() - timedelta(days=7)

    logger.info("Syncing Stryd data from %s to %s", start_date, end_date)
    updated, created, skipped = sync_activities(
        notion, stryd_session, token, start_date, end_date, debug=args.debug
    )
    logger.info(
        "Done: %d updated, %d created, %d skipped", updated, created, skipped
    )


if __name__ == "__main__":
    main()
