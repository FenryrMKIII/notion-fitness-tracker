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
) -> tuple[str, str]:
    """Authenticate with Stryd and return (token, user_id)."""
    resp = session.post(
        f"{STRYD_BASE_URL}/email/signin",
        json={"email": email, "password": password},
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Stryd authentication failed (HTTP {resp.status_code})")
    data: dict[str, Any] = resp.json()
    return data["token"], data["id"]


def fetch_activities(
    session: requests.Session,
    token: str,
    start_date: date,
    end_date: date,
    user_id: str = "",
) -> list[dict[str, Any]]:
    """Fetch activity summaries from Stryd for a date range."""
    headers = {"Authorization": f"Bearer: {token}"}
    from_ts = int(datetime.combine(start_date, datetime.min.time()).timestamp())
    to_ts = int(datetime.combine(end_date, datetime.min.time()).timestamp())
    params: dict[str, Any] = {
        "from": from_ts,
        "to": to_ts,
        "include_deleted": "false",
    }
    resp = session.get(
        f"{STRYD_API_URL}/users/{user_id}/calendar",
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


def deduplicate_activities(
    activities: list[dict[str, Any]],
    distance_threshold: float = 0.15,
) -> list[dict[str, Any]]:
    """Remove duplicate Stryd activities for the same run.

    Stryd's API often returns two entries for a single run — one from the
    Garmin-synced source and one native Stryd workout.  This function:

    1. Groups activities by date.
    2. Within each date, clusters activities whose distance is within
       *distance_threshold* (default 15 %).
    3. Keeps the "best" entry per cluster (most data fields, prefers HR).
    4. Returns the flattened, deduplicated list.
    """
    from collections import defaultdict

    by_date: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for act in activities:
        by_date[extract_date(act)].append(act)

    result: list[dict[str, Any]] = []
    for _d, group in sorted(by_date.items()):
        if len(group) == 1:
            result.append(group[0])
            continue
        # Cluster by similar distance
        clusters: list[list[dict[str, Any]]] = []
        used = [False] * len(group)
        for i, a in enumerate(group):
            if used[i]:
                continue
            cluster = [a]
            used[i] = True
            dist_a = float(a.get("distance", 0) or 0)
            for j in range(i + 1, len(group)):
                if used[j]:
                    continue
                dist_b = float(group[j].get("distance", 0) or 0)
                if _distances_similar(dist_a, dist_b, distance_threshold):
                    cluster.append(group[j])
                    used[j] = True
            clusters.append(cluster)
        for cluster in clusters:
            best = max(cluster, key=_activity_quality_score)
            result.append(best)
    return result


def _distances_similar(a: float, b: float, threshold: float) -> bool:
    """Return True if two distances are within *threshold* fraction of each other."""
    if a <= 0 and b <= 0:
        return True
    ref = max(a, b)
    if ref == 0:
        return True
    return abs(a - b) / ref <= threshold


def _activity_quality_score(activity: dict[str, Any]) -> tuple[int, int, float]:
    """Score an activity for dedup selection.

    Returns a tuple for tie-breaking:
      (has_hr, non_null_field_count, distance)
    Higher is better.
    """
    non_null = sum(1 for v in activity.values() if v is not None and v != 0 and v != "")
    has_hr = 1 if activity.get("average_heart_rate") else 0
    dist = float(activity.get("distance", 0) or 0)
    return (has_hr, non_null, dist)


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


def find_existing_match(
    notion: NotionClient,
    activity_time: datetime,
    db_id: str,
    stryd_distance_m: float = 0,
) -> str | None:
    """Find an existing Running entry that matches the Stryd activity by date.

    Searches for any Running entry (regardless of source) on the same date.
    This prevents duplicates when a Stryd standalone entry already exists.
    When multiple matches exist, picks the one with closest distance.
    Returns the Notion page ID if found, None otherwise.
    """
    target_date = activity_time.date().isoformat()

    results = notion.query_database(
        db_id,
        filter_obj={
            "and": [
                {"property": "Date", "date": {"equals": target_date}},
                {"property": "Training Type", "select": {"equals": "Running"}},
            ]
        },
    )

    if not results:
        return None

    if len(results) == 1:
        page_id: str = results[0]["id"]
        return page_id

    # Multiple running entries — pick closest distance match
    stryd_km = stryd_distance_m / 1000.0 if stryd_distance_m > 0 else 0
    best_page_id: str = results[0]["id"]
    best_diff = float("inf")
    for page in results:
        dist_prop = page.get("properties", {}).get("Distance (km)", {})
        page_dist = dist_prop.get("number") if dist_prop else None
        if page_dist is not None and stryd_km > 0:
            diff = abs(page_dist - stryd_km)
            if diff < best_diff:
                best_diff = diff
                best_page_id = page["id"]
    logger.info(
        "Multiple running entries on %s, matched closest distance (diff=%.2fkm)",
        target_date,
        best_diff if best_diff != float("inf") else 0,
    )
    return best_page_id


# ---------------------------------------------------------------------------
# Sync orchestration
# ---------------------------------------------------------------------------


def sync_activities(
    notion: NotionClient,
    stryd_session: requests.Session,
    token: str,
    start_date: date,
    end_date: date,
    user_id: str = "",
    debug: bool = False,
) -> tuple[int, int, int]:
    """Sync Stryd activities to Notion.

    Returns (updated, created, skipped) counts.
    """
    activities = fetch_activities(stryd_session, token, start_date, end_date, user_id)
    logger.info("Fetched %d activities from Stryd", len(activities))

    # Deduplicate before syncing (Stryd often returns Garmin-synced + native entries)
    deduped = deduplicate_activities(activities)
    if len(deduped) < len(activities):
        logger.info(
            "Deduplicated %d → %d activities", len(activities), len(deduped)
        )
    activities = deduped

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

        # Try to find an existing running entry to enrich
        distance_m = float(activity.get("distance", 0) or 0)
        match_page_id = find_existing_match(notion, ts, db_id, distance_m)

        if match_page_id:
            update_props = build_stryd_update_properties(metrics, rpe, feel)
            if update_props:
                notion.update_page(match_page_id, update_props)
                logger.info("Updated existing entry for %s with Stryd data", ts.date())
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
    token, user_id = authenticate(stryd_session, email, password)
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
        notion, stryd_session, token, start_date, end_date,
        user_id=user_id, debug=args.debug,
    )
    logger.info(
        "Done: %d updated, %d created, %d skipped", updated, created, skipped
    )


if __name__ == "__main__":
    main()
