#!/usr/bin/env python3
"""One-time cleanup: archive duplicate running entries in Training Sessions DB.

Groups Running entries by date, scores each entry by data completeness,
and archives lower-scored duplicates via the Notion API.

Usage:
    uv run python -m scripts.cleanup_duplicates --dry-run   # preview
    uv run python -m scripts.cleanup_duplicates              # archive duplicates
"""

import argparse
import logging
import os
from collections import defaultdict
from typing import Any

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

NOTION_API_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

logger = logging.getLogger(__name__)

# Properties that indicate Stryd-enriched data (power metrics)
POWER_PROPERTIES = {"Power (W)", "RSS", "Critical Power (W)"}

# All Stryd metric properties to transfer when merging
STRYD_METRIC_PROPERTIES = [
    "Power (W)",
    "RSS",
    "Critical Power (W)",
    "Cadence (spm)",
    "Stride Length (m)",
    "Ground Contact (ms)",
    "Vertical Oscillation (cm)",
    "Leg Spring Stiffness",
    "Temperature (C)",
    "Wind Speed",
    "RPE",
]


def score_entry(page: dict[str, Any]) -> int:
    """Score a Training Session page by data completeness.

    Higher score = more data = should be kept.
    """
    props = page.get("properties", {})
    score = 0

    # +1 per non-empty property
    for _name, prop in props.items():
        if _property_has_value(prop):
            score += 1

    # +3 bonus for power data (Stryd-enriched entries)
    for power_prop in POWER_PROPERTIES:
        if power_prop in props and _property_has_value(props[power_prop]):
            score += 3
            break  # only one bonus

    # +2 bonus for heart rate
    hr_prop = props.get("Avg Heart Rate", {})
    if _property_has_value(hr_prop):
        score += 2

    # +2 bonus if distance > 1km (filters out micro-segments)
    dist_prop = props.get("Distance (km)", {})
    dist_val = dist_prop.get("number")
    if dist_val is not None and dist_val > 1.0:
        score += 2

    return score


def _property_has_value(prop: dict[str, Any]) -> bool:
    """Return True if a Notion property has a non-empty value."""
    prop_type = prop.get("type", "")

    if prop_type == "number":
        return prop.get("number") is not None
    if prop_type == "rich_text":
        items = prop.get("rich_text", [])
        return bool(items) and any(
            t.get("text", {}).get("content", "") for t in items
        )
    if prop_type == "title":
        items = prop.get("title", [])
        return bool(items) and any(
            t.get("text", {}).get("content", "") for t in items
        )
    if prop_type == "select":
        return prop.get("select") is not None
    if prop_type == "multi_select":
        return bool(prop.get("multi_select", []))
    if prop_type == "date":
        return prop.get("date") is not None
    return prop_type == "checkbox"


def get_entry_name(page: dict[str, Any]) -> str:
    """Extract the Name (title) from a Notion page."""
    props = page.get("properties", {})
    name_prop = props.get("Name", {})
    title_items = name_prop.get("title", [])
    if title_items:
        return title_items[0].get("text", {}).get("content", "(no name)")
    return "(no name)"


def get_entry_date(page: dict[str, Any]) -> str:
    """Extract the Date from a Notion page."""
    props = page.get("properties", {})
    date_prop = props.get("Date", {})
    date_val = date_prop.get("date")
    if date_val:
        return date_val.get("start", "")
    return ""


def get_entry_source(page: dict[str, Any]) -> str:
    """Extract the Source from a Notion page."""
    props = page.get("properties", {})
    src = props.get("Source", {})
    sel = src.get("select")
    if sel:
        return sel.get("name", "")
    return ""


def has_power_data(page: dict[str, Any]) -> bool:
    """Return True if the page has any Stryd power metric populated."""
    props = page.get("properties", {})
    return any(
        prop_name in props and _property_has_value(props[prop_name])
        for prop_name in POWER_PROPERTIES
    )


def get_power_properties(page: dict[str, Any]) -> dict[str, Any]:
    """Extract Notion-API-ready property dicts for all populated Stryd metrics.

    Also transfers Feeling (select) if present on the source page.
    """
    props = page.get("properties", {})
    result: dict[str, Any] = {}

    for prop_name in STRYD_METRIC_PROPERTIES:
        if prop_name in props and _property_has_value(props[prop_name]):
            value = props[prop_name].get("number")
            result[prop_name] = {"number": value}

    # Also transfer Feeling (select) if present
    feeling_prop = props.get("Feeling", {})
    if _property_has_value(feeling_prop):
        result["Feeling"] = {"select": feeling_prop.get("select")}

    return result


def merge_power_data(
    session: requests.Session,
    headers: dict[str, str],
    keeper_id: str,
    source_page: dict[str, Any],
) -> None:
    """Transfer Stryd power metrics from source_page to keeper via PATCH."""
    import time

    power_props = get_power_properties(source_page)
    if not power_props:
        return

    time.sleep(0.35)  # rate limit
    resp = session.patch(
        f"{NOTION_API_URL}/pages/{keeper_id}",
        headers=headers,
        json={"properties": power_props},
        timeout=30,
    )
    resp.raise_for_status()
    logger.info("    Merged %d power properties into keeper", len(power_props))


def find_duplicates(
    pages: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    """Group pages by date and return (keeper, to_archive) for dates with duplicates."""
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for page in pages:
        d = get_entry_date(page)
        if d:
            by_date[d].append(page)

    results: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for d in sorted(by_date):
        group = by_date[d]
        if len(group) < 2:
            continue
        # Score and sort descending; first = keeper
        scored = sorted(group, key=score_entry, reverse=True)
        keeper = scored[0]
        to_archive = scored[1:]
        results.append((keeper, to_archive))
    return results


def archive_page(
    session: requests.Session,
    headers: dict[str, str],
    page_id: str,
) -> None:
    """Archive a Notion page via PATCH /pages/{id} with archived=true."""
    import time

    time.sleep(0.35)  # rate limit
    resp = session.patch(
        f"{NOTION_API_URL}/pages/{page_id}",
        headers=headers,
        json={"archived": True},
        timeout=30,
    )
    resp.raise_for_status()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Archive duplicate running entries in Training Sessions DB"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without archiving",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    load_dotenv()

    api_key = os.environ.get("NOTION_API_KEY")
    db_id = os.environ.get("NOTION_TRAINING_DB_ID")
    if not api_key or not db_id:
        logger.error("NOTION_API_KEY and NOTION_TRAINING_DB_ID must be set")
        raise SystemExit(1)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }

    session = requests.Session()
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retry))

    # Query all Running entries
    import time

    logger.info("Querying all Running entries...")
    all_pages: list[dict[str, Any]] = []
    payload: dict[str, Any] = {
        "filter": {
            "property": "Training Type",
            "select": {"equals": "Running"},
        }
    }
    has_more = True
    while has_more:
        time.sleep(0.35)
        resp = session.post(
            f"{NOTION_API_URL}/databases/{db_id}/query",
            headers=headers,
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        all_pages.extend(data.get("results", []))
        has_more = data.get("has_more", False)
        if has_more:
            payload["start_cursor"] = data["next_cursor"]

    logger.info("Found %d Running entries total", len(all_pages))

    duplicates = find_duplicates(all_pages)
    if not duplicates:
        logger.info("No duplicates found!")
        return

    total_archived = 0
    for keeper, to_archive in duplicates:
        d = get_entry_date(keeper)
        keeper_name = get_entry_name(keeper)
        keeper_score = score_entry(keeper)
        keeper_source = get_entry_source(keeper)
        logger.info(
            "Date %s — KEEP: %r (source=%s, score=%d)",
            d, keeper_name, keeper_source, keeper_score,
        )
        for page in to_archive:
            name = get_entry_name(page)
            s = score_entry(page)
            src = get_entry_source(page)

            # Merge power data from Stryd entry into keeper if keeper lacks it
            needs_merge = not has_power_data(keeper) and has_power_data(page)
            if needs_merge:
                if args.dry_run:
                    power_props = get_power_properties(page)
                    logger.info(
                        "  Would merge %d power properties from %r into keeper",
                        len(power_props), name,
                    )
                else:
                    merge_power_data(session, headers, keeper["id"], page)

            if args.dry_run:
                logger.info(
                    "  Would archive: %r (source=%s, score=%d)", name, src, s
                )
            else:
                archive_page(session, headers, page["id"])
                logger.info(
                    "  Archived: %r (source=%s, score=%d)", name, src, s
                )
            total_archived += 1

    action = "Would archive" if args.dry_run else "Archived"
    logger.info("%s %d duplicate entries", action, total_archived)


if __name__ == "__main__":
    main()
