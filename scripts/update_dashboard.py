#!/usr/bin/env python3
"""Regenerate the Notion dashboard with 4-week training and health trend tables."""

import argparse
import logging
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from dotenv import load_dotenv

from scripts.notion_client import ConfigurationError, NotionClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TRAINING_DB_PROPERTIES = [
    "Name",
    "Date",
    "Training Type",
    "Duration (min)",
    "Distance (km)",
    "Volume (kg)",
    "Feeling",
]
HEALTH_DB_PROPERTIES = [
    "Date",
    "Sleep Duration (h)",
    "Sleep Quality",
    "Resting HR",
    "Steps",
    "Body Battery",
    "Status",
]


@dataclass(frozen=True)
class DashboardConfig:
    """Dashboard configuration from environment variables."""

    training_db_id: str
    health_db_id: str
    dashboard_page_id: str


def get_env_config() -> DashboardConfig:
    """Load dashboard configuration from environment variables."""
    training_db_id = os.environ.get("NOTION_TRAINING_DB_ID")
    health_db_id = os.environ.get("NOTION_HEALTH_DB_ID")
    dashboard_page_id = os.environ.get("NOTION_DASHBOARD_PAGE_ID")

    missing: list[str] = []
    if not training_db_id:
        missing.append("NOTION_TRAINING_DB_ID")
    if not health_db_id:
        missing.append("NOTION_HEALTH_DB_ID")
    if not dashboard_page_id:
        missing.append("NOTION_DASHBOARD_PAGE_ID")

    if missing:
        raise ConfigurationError(
            f"Missing required environment variables: {', '.join(missing)}"
        )

    return DashboardConfig(
        training_db_id=training_db_id,  # type: ignore[arg-type]
        health_db_id=health_db_id,  # type: ignore[arg-type]
        dashboard_page_id=dashboard_page_id,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class TrainingWeek:
    """Aggregated training metrics for one week."""

    label: str = ""
    sessions: int = 0
    active_days: int = 0
    running_km: float = 0.0
    longest_run_km: float = 0.0
    running_count: int = 0
    gym_sessions: int = 0
    gym_volume: float = 0.0
    gym_volume_per_session: float = 0.0
    feeling_avg: float = 0.0
    tough_sessions: int = 0
    total_duration_min: int = 0


@dataclass
class HealthWeek:
    """Aggregated health metrics for one week."""

    label: str = ""
    avg_sleep_hours: float = 0.0
    sleep_quality_mode: str = ""
    avg_resting_hr: float = 0.0
    avg_steps: float = 0.0
    avg_body_battery: float = 0.0
    sick_days: int = 0
    injured_days: int = 0
    rest_days: int = 0
    entries: int = 0


# ---------------------------------------------------------------------------
# Week boundaries
# ---------------------------------------------------------------------------

FEELING_MAP: dict[str, int] = {
    "Great": 5,
    "Good": 4,
    "Okay": 3,
    "Tired": 2,
    "Exhausted": 1,
}

RUNNING_TYPES = {"Running"}
GYM_TYPES = {"Gym-Strength", "Gym-Crossfit"}
TOUGH_FEELINGS = {"Tired", "Exhausted"}


def get_week_boundaries(today: date) -> list[tuple[date, date, str]]:
    """Return 4 (monday, sunday, label) tuples for the last 4 weeks, most recent first."""
    # Find this Monday
    current_monday = today - timedelta(days=today.weekday())
    weeks: list[tuple[date, date, str]] = []
    for i in range(4):
        monday = current_monday - timedelta(weeks=i)
        sunday = monday + timedelta(days=6)
        label = f"{monday.strftime('%b %d')} – {sunday.strftime('%b %d')}"
        weeks.append((monday, sunday, label))
    return weeks


def group_by_week(
    records: list[dict[str, Any]],
    weeks: list[tuple[date, date, str]],
    date_key: str = "date",
) -> list[list[dict[str, Any]]]:
    """Bucket records into weeks. Returns one list per week, same order as weeks."""
    buckets: list[list[dict[str, Any]]] = [[] for _ in weeks]
    for record in records:
        d = record.get(date_key)
        if d is None:
            continue
        if isinstance(d, str):
            d = date.fromisoformat(d)
        for idx, (monday, sunday, _label) in enumerate(weeks):
            if monday <= d <= sunday:
                buckets[idx].append(record)
                break
    return buckets


# ---------------------------------------------------------------------------
# Property extraction (flatten Notion JSON → dict)
# ---------------------------------------------------------------------------


def _get_text(prop: dict[str, Any]) -> str:
    """Extract plain text from a rich_text or title property."""
    for key in ("title", "rich_text"):
        items = prop.get(key, [])
        if items:
            return str(items[0].get("plain_text", ""))
    return ""


def _get_number(prop: dict[str, Any]) -> float | None:
    """Extract number value from a number property."""
    val = prop.get("number")
    if val is not None:
        return float(val)
    return None


def _get_date(prop: dict[str, Any]) -> str | None:
    """Extract date string from a date property."""
    date_obj = prop.get("date")
    if date_obj and date_obj.get("start"):
        return str(date_obj["start"])
    return None


def _get_select(prop: dict[str, Any]) -> str | None:
    """Extract select name from a select property."""
    select_obj = prop.get("select")
    if select_obj:
        return str(select_obj.get("name", ""))
    return None


def extract_training_props(page: dict[str, Any]) -> dict[str, Any]:
    """Flatten a Training Sessions page into a simple dict."""
    props = page.get("properties", {})
    return {
        "name": _get_text(props.get("Name", {})),
        "date": _get_date(props.get("Date", {})),
        "training_type": _get_select(props.get("Training Type", {})),
        "duration_min": _get_number(props.get("Duration (min)", {})),
        "distance_km": _get_number(props.get("Distance (km)", {})),
        "volume_kg": _get_number(props.get("Volume (kg)", {})),
        "feeling": _get_select(props.get("Feeling", {})),
    }


def extract_health_props(page: dict[str, Any]) -> dict[str, Any]:
    """Flatten a Health Status Log page into a simple dict."""
    props = page.get("properties", {})
    return {
        "date": _get_date(props.get("Date", {})),
        "sleep_hours": _get_number(props.get("Sleep Duration (h)", {})),
        "sleep_quality": _get_select(props.get("Sleep Quality", {})),
        "resting_hr": _get_number(props.get("Resting HR", {})),
        "steps": _get_number(props.get("Steps", {})),
        "body_battery": _get_number(props.get("Body Battery", {})),
        "status": _get_select(props.get("Status", {})),
    }


# ---------------------------------------------------------------------------
# Weekly calculations (pure)
# ---------------------------------------------------------------------------


def _safe_avg(values: list[float]) -> float:
    """Average of non-None numeric values. Returns 0.0 if empty."""
    if not values:
        return 0.0
    return round(sum(values) / len(values), 1)


def calculate_training_week(records: list[dict[str, Any]], label: str) -> TrainingWeek:
    """Compute training metrics for one week's records."""
    tw = TrainingWeek(label=label)
    tw.sessions = len(records)

    active_dates: set[str] = set()
    run_distances: list[float] = []
    gym_volumes: list[float] = []
    feeling_scores: list[int] = []

    for r in records:
        d = r.get("date")
        if d:
            active_dates.add(str(d)[:10])

        training_type = r.get("training_type") or ""
        duration = r.get("duration_min") or 0
        distance = r.get("distance_km") or 0.0
        volume = r.get("volume_kg") or 0.0
        feeling = r.get("feeling")

        tw.total_duration_min += int(duration)

        if training_type in RUNNING_TYPES:
            tw.running_count += 1
            tw.running_km += float(distance)
            run_distances.append(float(distance))

        if training_type in GYM_TYPES:
            tw.gym_sessions += 1
            tw.gym_volume += float(volume)
            gym_volumes.append(float(volume))

        if feeling:
            score = FEELING_MAP.get(feeling)
            if score is not None:
                feeling_scores.append(score)
            if feeling in TOUGH_FEELINGS:
                tw.tough_sessions += 1

    tw.active_days = len(active_dates)
    tw.running_km = round(tw.running_km, 1)
    tw.longest_run_km = round(max(run_distances), 1) if run_distances else 0.0
    tw.gym_volume = round(tw.gym_volume, 1)
    tw.gym_volume_per_session = (
        round(tw.gym_volume / tw.gym_sessions, 1) if tw.gym_sessions > 0 else 0.0
    )
    tw.feeling_avg = _safe_avg([float(s) for s in feeling_scores])

    return tw


def _most_common(values: list[str]) -> str:
    """Return the most common value in a list, or empty string if empty."""
    if not values:
        return ""
    counts: dict[str, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return max(counts, key=lambda k: counts[k])


def calculate_health_week(records: list[dict[str, Any]], label: str) -> HealthWeek:
    """Compute health metrics for one week's records."""
    hw = HealthWeek(label=label)
    hw.entries = len(records)

    sleep_hours: list[float] = []
    sleep_qualities: list[str] = []
    resting_hrs: list[float] = []
    steps_vals: list[float] = []
    battery_vals: list[float] = []

    for r in records:
        if r.get("sleep_hours") is not None:
            sleep_hours.append(float(r["sleep_hours"]))
        if r.get("sleep_quality"):
            sleep_qualities.append(str(r["sleep_quality"]))
        if r.get("resting_hr") is not None:
            resting_hrs.append(float(r["resting_hr"]))
        if r.get("steps") is not None:
            steps_vals.append(float(r["steps"]))
        if r.get("body_battery") is not None:
            battery_vals.append(float(r["body_battery"]))

        status = r.get("status") or ""
        if status == "Sick":
            hw.sick_days += 1
        elif status == "Injured":
            hw.injured_days += 1
        elif status == "Rest Day":
            hw.rest_days += 1

    hw.avg_sleep_hours = _safe_avg(sleep_hours)
    hw.sleep_quality_mode = _most_common(sleep_qualities)
    hw.avg_resting_hr = _safe_avg(resting_hrs)
    hw.avg_steps = _safe_avg(steps_vals)
    hw.avg_body_battery = _safe_avg(battery_vals)

    return hw


# ---------------------------------------------------------------------------
# Trend / insight generation (pure)
# ---------------------------------------------------------------------------


def trend_direction(current: float, previous_avg: float) -> str:
    """Return 'up', 'down', or 'stable' comparing current to previous average."""
    if previous_avg == 0:
        return "stable" if current == 0 else "up"
    pct_change = (current - previous_avg) / abs(previous_avg)
    if pct_change > 0.05:
        return "up"
    if pct_change < -0.05:
        return "down"
    return "stable"


def _trend_arrow(direction: str) -> str:
    """Return an arrow character for the trend direction."""
    return {"up": "\u2191", "down": "\u2193", "stable": "\u2192"}.get(direction, "")


def generate_training_insights(weeks: list[TrainingWeek]) -> list[str]:
    """Generate insight strings comparing current week to prior 3-week avg."""
    if not weeks:
        return []

    current = weeks[0]
    prior = weeks[1:] if len(weeks) > 1 else []

    insights: list[str] = []

    if prior:
        avg_sessions = _safe_avg([float(w.sessions) for w in prior])
        d = trend_direction(float(current.sessions), avg_sessions)
        insights.append(
            f"{_trend_arrow(d)} Sessions: {current.sessions} (avg {avg_sessions})"
        )

        avg_duration = _safe_avg([float(w.total_duration_min) for w in prior])
        d = trend_direction(float(current.total_duration_min), avg_duration)
        insights.append(
            f"{_trend_arrow(d)} Duration: {current.total_duration_min}min "
            f"(avg {avg_duration}min)"
        )

        avg_volume = _safe_avg([float(w.gym_volume) for w in prior])
        d = trend_direction(current.gym_volume, avg_volume)
        insights.append(
            f"{_trend_arrow(d)} Gym volume: {current.gym_volume}kg "
            f"(avg {avg_volume}kg)"
        )

        avg_running = _safe_avg([float(w.running_km) for w in prior])
        d = trend_direction(current.running_km, avg_running)
        insights.append(
            f"{_trend_arrow(d)} Running: {current.running_km}km "
            f"(avg {avg_running}km)"
        )
    else:
        insights.append(f"Sessions: {current.sessions}")
        insights.append(f"Duration: {current.total_duration_min}min")
        insights.append(f"Gym volume: {current.gym_volume}kg")
        insights.append(f"Running: {current.running_km}km")

    return insights


def generate_health_insights(weeks: list[HealthWeek]) -> list[str]:
    """Generate insight strings comparing current week to prior 3-week avg."""
    if not weeks:
        return []

    current = weeks[0]
    prior = weeks[1:] if len(weeks) > 1 else []

    insights: list[str] = []

    if prior:
        avg_sleep = _safe_avg([w.avg_sleep_hours for w in prior])
        d = trend_direction(current.avg_sleep_hours, avg_sleep)
        insights.append(
            f"{_trend_arrow(d)} Sleep: {current.avg_sleep_hours}h (avg {avg_sleep}h)"
        )

        avg_hr = _safe_avg([w.avg_resting_hr for w in prior])
        d = trend_direction(current.avg_resting_hr, avg_hr)
        arrow = _trend_arrow(d)
        insights.append(
            f"{arrow} Resting HR: {current.avg_resting_hr}bpm (avg {avg_hr}bpm)"
        )

        avg_steps = _safe_avg([w.avg_steps for w in prior])
        d = trend_direction(current.avg_steps, avg_steps)
        insights.append(
            f"{_trend_arrow(d)} Steps: {current.avg_steps} (avg {avg_steps})"
        )

        avg_battery = _safe_avg([w.avg_body_battery for w in prior])
        d = trend_direction(current.avg_body_battery, avg_battery)
        insights.append(
            f"{_trend_arrow(d)} Body battery: {current.avg_body_battery} "
            f"(avg {avg_battery})"
        )
    else:
        insights.append(f"Sleep: {current.avg_sleep_hours}h")
        insights.append(f"Resting HR: {current.avg_resting_hr}bpm")
        insights.append(f"Steps: {current.avg_steps}")
        insights.append(f"Body battery: {current.avg_body_battery}")

    return insights


def generate_training_takeaway(weeks: list[TrainingWeek]) -> str:
    """Generate a brief takeaway for training trends."""
    if not weeks or not weeks[0].sessions:
        return "No training data this week."

    current = weeks[0]
    parts: list[str] = []

    parts.append(f"{current.sessions} sessions, {current.active_days} active days")

    if current.gym_volume > 0:
        parts.append(f"{current.gym_volume}kg gym volume")
    if current.running_km > 0:
        parts.append(f"{current.running_km}km running")
    if current.feeling_avg > 0:
        parts.append(f"avg feeling {current.feeling_avg}/5")

    return "This week: " + ", ".join(parts) + "."


def generate_health_takeaway(weeks: list[HealthWeek]) -> str:
    """Generate a brief takeaway for health trends."""
    if not weeks or not weeks[0].entries:
        return "No health data this week."

    current = weeks[0]
    parts: list[str] = []

    if current.avg_sleep_hours > 0:
        parts.append(f"{current.avg_sleep_hours}h avg sleep")
    if current.avg_resting_hr > 0:
        parts.append(f"{current.avg_resting_hr}bpm resting HR")
    if current.avg_steps > 0:
        parts.append(f"{current.avg_steps} avg steps")
    if current.sick_days > 0:
        parts.append(f"{current.sick_days} sick days")

    if not parts:
        return "Health data logged but no specific metrics this week."

    return "This week: " + ", ".join(parts) + "."


# ---------------------------------------------------------------------------
# Notion block builders (pure, return dict)
# ---------------------------------------------------------------------------


def build_text(content: str, bold: bool = False, color: str = "default") -> dict[str, Any]:
    """Build a rich_text element."""
    rt: dict[str, Any] = {"type": "text", "text": {"content": content}}
    annotations: dict[str, Any] = {}
    if bold:
        annotations["bold"] = True
    if color != "default":
        annotations["color"] = color
    if annotations:
        rt["annotations"] = annotations
    return rt


def build_heading_2(text: str) -> dict[str, Any]:
    """Build a heading_2 block."""
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [build_text(text)],
        },
    }


def build_callout(text: str, icon: str = "info", color: str = "default") -> dict[str, Any]:
    """Build a callout block with text content."""
    icon_map: dict[str, str] = {
        "info": "\u2139\ufe0f",
        "check": "\u2705",
        "warning": "\u26a0\ufe0f",
        "chart": "\ud83d\udcca",
        "fire": "\ud83d\udd25",
        "heart": "\u2764\ufe0f",
    }
    return {
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": [build_text(text)],
            "icon": {"type": "emoji", "emoji": icon_map.get(icon, icon)},
            "color": color,
        },
    }


def build_divider() -> dict[str, Any]:
    """Build a divider block."""
    return {"object": "block", "type": "divider", "divider": {}}


def _color_for_value(
    value: float, prev_avg: float, higher_is_better: bool = True
) -> str:
    """Determine text color based on trend direction."""
    d = trend_direction(value, prev_avg)
    if d == "stable":
        return "default"
    if higher_is_better:
        return "green" if d == "up" else "red"
    return "red" if d == "up" else "green"


def _format_num(value: float, decimals: int = 1) -> str:
    """Format a number, showing integer if whole."""
    if value == int(value):
        return str(int(value))
    return f"{value:.{decimals}f}"


def build_table_row(cells: list[list[dict[str, Any]]]) -> dict[str, Any]:
    """Build a table_row block from cells (each cell is a list of rich_text elements)."""
    return {
        "object": "block",
        "type": "table_row",
        "table_row": {"cells": cells},
    }


def build_training_table(
    weeks: list[TrainingWeek],
) -> dict[str, Any]:
    """Build the training trends table block with colored values."""
    headers = [
        "Week",
        "Sessions",
        "Active Days",
        "Run km",
        "Longest Run",
        "Gym Sessions",
        "Gym Vol (kg)",
        "Vol/Session",
        "Feeling",
        "Duration (min)",
    ]
    header_row = build_table_row([[build_text(h, bold=True)] for h in headers])

    rows = [header_row]

    # Prior weeks average for coloring
    prior = weeks[1:] if len(weeks) > 1 else []

    def _prior_avg(attr: str) -> float:
        return _safe_avg([float(getattr(pw, attr)) for pw in prior])

    def _cell(
        val: float, attr: str, is_current: bool, higher: bool = True
    ) -> list[dict[str, Any]]:
        if is_current and prior:
            color = _color_for_value(val, _prior_avg(attr), higher)
            return [build_text(_format_num(val), color=color)]
        return [build_text(_format_num(val))]

    for i, w in enumerate(weeks):
        is_current = i == 0
        row = build_table_row(
            [
                [build_text(w.label, bold=is_current)],
                _cell(float(w.sessions), "sessions", is_current),
                _cell(float(w.active_days), "active_days", is_current),
                _cell(w.running_km, "running_km", is_current),
                _cell(w.longest_run_km, "longest_run_km", is_current),
                _cell(float(w.gym_sessions), "gym_sessions", is_current),
                _cell(w.gym_volume, "gym_volume", is_current),
                _cell(w.gym_volume_per_session, "gym_volume_per_session", is_current),
                _cell(w.feeling_avg, "feeling_avg", is_current),
                _cell(float(w.total_duration_min), "total_duration_min", is_current),
            ]
        )
        rows.append(row)

    return {
        "object": "block",
        "type": "table",
        "table": {
            "table_width": len(headers),
            "has_column_header": True,
            "has_row_header": False,
            "children": rows,
        },
    }


def build_health_table(
    weeks: list[HealthWeek],
) -> dict[str, Any]:
    """Build the health trends table block with colored values."""
    headers = [
        "Week",
        "Sleep (h)",
        "Sleep Quality",
        "Resting HR",
        "Steps",
        "Body Battery",
        "Sick",
        "Injured",
        "Rest Days",
    ]
    header_row = build_table_row([[build_text(h, bold=True)] for h in headers])

    rows = [header_row]

    prior = weeks[1:] if len(weeks) > 1 else []

    def _prior_avg(attr: str) -> float:
        return _safe_avg([float(getattr(pw, attr)) for pw in prior])

    def _cell(
        val: float, attr: str, is_current: bool, higher: bool = True
    ) -> list[dict[str, Any]]:
        if is_current and prior:
            color = _color_for_value(val, _prior_avg(attr), higher)
            return [build_text(_format_num(val), color=color)]
        return [build_text(_format_num(val))]

    for i, w in enumerate(weeks):
        is_current = i == 0
        quality_str = w.sleep_quality_mode or "\u2014"
        row = build_table_row(
            [
                [build_text(w.label, bold=is_current)],
                _cell(w.avg_sleep_hours, "avg_sleep_hours", is_current),
                [build_text(quality_str)],
                _cell(w.avg_resting_hr, "avg_resting_hr", is_current, higher=False),
                _cell(w.avg_steps, "avg_steps", is_current),
                _cell(w.avg_body_battery, "avg_body_battery", is_current),
                [build_text(str(w.sick_days))],
                [build_text(str(w.injured_days))],
                [build_text(str(w.rest_days))],
            ]
        )
        rows.append(row)

    return {
        "object": "block",
        "type": "table",
        "table": {
            "table_width": len(headers),
            "has_column_header": True,
            "has_row_header": False,
            "children": rows,
        },
    }


def build_paragraph(rich_text: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a paragraph block."""
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": rich_text},
    }


def build_toggle(text: str, children: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a toggle block with children."""
    return {
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": [build_text(text, bold=True)],
            "children": children,
        },
    }


def build_insights_block(insights: list[str]) -> dict[str, Any]:
    """Build a callout block with insight lines."""
    text = "\n".join(insights)
    return build_callout(text, icon="chart", color="blue_background")


def build_full_dashboard(
    training_weeks: list[TrainingWeek],
    health_weeks: list[HealthWeek],
    training_insights: list[str],
    health_insights: list[str],
    training_takeaway: str,
    health_takeaway: str,
    training_db_id: str,
    health_db_id: str,
) -> list[dict[str, Any]]:
    """Build the complete dashboard as a list of Notion blocks."""
    now_str = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
    blocks: list[dict[str, Any]] = []

    # Header
    blocks.append(
        build_callout(
            f"Dashboard auto-updated on {now_str}",
            icon="check",
            color="green_background",
        )
    )

    # Training section
    blocks.append(build_heading_2("4-Week Training Trends"))
    blocks.append(build_training_table(training_weeks))
    blocks.append(build_insights_block(training_insights))
    blocks.append(build_callout(training_takeaway, icon="fire"))
    blocks.append(build_divider())

    # Health section
    blocks.append(build_heading_2("4-Week Health Trends"))
    blocks.append(build_health_table(health_weeks))
    blocks.append(build_insights_block(health_insights))
    blocks.append(build_callout(health_takeaway, icon="heart"))
    blocks.append(build_divider())

    # Database links
    blocks.append(build_heading_2("Databases"))
    blocks.append(
        build_paragraph(
            [
                build_text("Training Sessions: "),
                {
                    "type": "mention",
                    "mention": {
                        "type": "database",
                        "database": {"id": training_db_id},
                    },
                },
            ]
        )
    )
    blocks.append(
        build_paragraph(
            [
                build_text("Health Status Log: "),
                {
                    "type": "mention",
                    "mention": {
                        "type": "database",
                        "database": {"id": health_db_id},
                    },
                },
            ]
        )
    )
    blocks.append(build_divider())

    # Quick Add guide
    blocks.append(
        build_toggle(
            "Quick Add Guide",
            [
                build_paragraph(
                    [build_text("Use the databases above to add entries manually.")]
                ),
                build_paragraph(
                    [
                        build_text("Training: ", bold=True),
                        build_text(
                            "Name, Date, Training Type, Duration, and optionally "
                            "Distance/Volume/Feeling."
                        ),
                    ]
                ),
                build_paragraph(
                    [
                        build_text("Health: ", bold=True),
                        build_text(
                            "Date, then any combination of Sleep, HR, Steps, "
                            "Body Battery, Status."
                        ),
                    ]
                ),
            ],
        )
    )

    # Integration status
    blocks.append(
        build_toggle(
            "Integration Status",
            [
                build_paragraph(
                    [
                        build_text("Hevy", bold=True),
                        build_text(" — GitHub Actions, every 6h"),
                    ]
                ),
                build_paragraph(
                    [
                        build_text("Garmin", bold=True),
                        build_text(" — GitHub Actions, daily 7AM UTC"),
                    ]
                ),
                build_paragraph(
                    [
                        build_text("Strava", bold=True),
                        build_text(" — Zapier automation (manual setup)"),
                    ]
                ),
                build_paragraph(
                    [
                        build_text("CrossFit", bold=True),
                        build_text(" — Manual entry in Notion"),
                    ]
                ),
                build_paragraph(
                    [
                        build_text("Dashboard", bold=True),
                        build_text(" — GitHub Actions, weekly Monday 8AM UTC"),
                    ]
                ),
            ],
        )
    )

    # Metric definitions
    blocks.append(
        build_toggle(
            "Metric Definitions",
            [
                build_paragraph(
                    [
                        build_text("Active Days", bold=True),
                        build_text(" — Unique days with at least one training session"),
                    ]
                ),
                build_paragraph(
                    [
                        build_text("Gym Volume", bold=True),
                        build_text(" — Total weight x reps across all gym exercises"),
                    ]
                ),
                build_paragraph(
                    [
                        build_text("Vol/Session", bold=True),
                        build_text(" — Average gym volume per gym session"),
                    ]
                ),
                build_paragraph(
                    [
                        build_text("Feeling", bold=True),
                        build_text(
                            " — 1-5 scale (Exhausted=1, Tired=2, Okay=3, Good=4, Great=5)"
                        ),
                    ]
                ),
                build_paragraph(
                    [
                        build_text("Body Battery", bold=True),
                        build_text(" — Garmin energy level metric (0-100)"),
                    ]
                ),
                build_paragraph(
                    [
                        build_text("Trend colors", bold=True),
                        build_text(
                            " — Green = improving vs 3-week avg, "
                            "Red = declining, Default = stable (within 5%)"
                        ),
                    ]
                ),
            ],
        )
    )

    return blocks


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------


def fetch_training_data(
    client: NotionClient, config: DashboardConfig, since: date
) -> list[dict[str, Any]]:
    """Fetch training sessions from Notion, filtered by date."""
    pages = client.query_database(
        config.training_db_id,
        filter_obj={
            "property": "Date",
            "date": {"on_or_after": since.isoformat()},
        },
        sorts=[{"property": "Date", "direction": "ascending"}],
    )
    return [extract_training_props(p) for p in pages]


def fetch_health_data(
    client: NotionClient, config: DashboardConfig, since: date
) -> list[dict[str, Any]]:
    """Fetch health status entries from Notion, filtered by date."""
    pages = client.query_database(
        config.health_db_id,
        filter_obj={
            "property": "Date",
            "date": {"on_or_after": since.isoformat()},
        },
        sorts=[{"property": "Date", "direction": "ascending"}],
    )
    return [extract_health_props(p) for p in pages]


# ---------------------------------------------------------------------------
# Page replacement
# ---------------------------------------------------------------------------


def clear_page_blocks(client: NotionClient, page_id: str) -> int:
    """Delete all blocks on a page. Returns count of deleted blocks."""
    children = client.get_block_children(page_id)
    for block in children:
        block_id = block.get("id", "")
        logger.debug("Deleting block %s (type=%s)", block_id, block.get("type"))
        client.delete_block(block_id)
    return len(children)


def write_dashboard(
    client: NotionClient, page_id: str, blocks: list[dict[str, Any]]
) -> None:
    """Append dashboard blocks to the page."""
    logger.info("Appending %d blocks to page %s", len(blocks), page_id)
    client.append_block_children(page_id, blocks)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Update Notion dashboard with trends")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Calculate and log metrics without writing to Notion",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    load_dotenv()

    try:
        config = get_env_config()
    except ConfigurationError as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from exc

    today = date.today()
    weeks = get_week_boundaries(today)
    earliest_monday = weeks[-1][0]

    logger.info("Fetching data from %s to %s", earliest_monday, today)

    if args.dry_run:
        logger.info("[DRY RUN] Would fetch training and health data from Notion")
        logger.info("[DRY RUN] Week boundaries:")
        for monday, sunday, label in weeks:
            logger.info("  %s: %s to %s", label, monday, sunday)
        logger.info("[DRY RUN] No changes written to Notion")
        return

    try:
        client = NotionClient()
    except ConfigurationError as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from exc

    # Fetch data
    training_records = fetch_training_data(client, config, earliest_monday)
    health_records = fetch_health_data(client, config, earliest_monday)

    logger.info(
        "Fetched %d training records, %d health records",
        len(training_records),
        len(health_records),
    )

    # Group by week
    training_by_week = group_by_week(training_records, weeks)
    health_by_week = group_by_week(health_records, weeks)

    # Calculate metrics
    training_weeks = [
        calculate_training_week(records, label)
        for records, (_mon, _sun, label) in zip(training_by_week, weeks, strict=True)
    ]
    health_weeks = [
        calculate_health_week(records, label)
        for records, (_mon, _sun, label) in zip(health_by_week, weeks, strict=True)
    ]

    # Log metrics
    for tw in training_weeks:
        logger.info(
            "Training %s: %d sessions, %dmin, %.1fkg gym, %.1fkm run",
            tw.label,
            tw.sessions,
            tw.total_duration_min,
            tw.gym_volume,
            tw.running_km,
        )
    for hw in health_weeks:
        logger.info(
            "Health %s: %.1fh sleep (%s), %.0f HR, %.0f steps",
            hw.label,
            hw.avg_sleep_hours,
            hw.sleep_quality_mode or "—",
            hw.avg_resting_hr,
            hw.avg_steps,
        )

    # Generate insights
    training_insights = generate_training_insights(training_weeks)
    health_insights = generate_health_insights(health_weeks)
    training_takeaway = generate_training_takeaway(training_weeks)
    health_takeaway = generate_health_takeaway(health_weeks)

    # Build and write dashboard
    blocks = build_full_dashboard(
        training_weeks,
        health_weeks,
        training_insights,
        health_insights,
        training_takeaway,
        health_takeaway,
        config.training_db_id,
        config.health_db_id,
    )

    logger.info("Clearing existing dashboard blocks...")
    deleted = clear_page_blocks(client, config.dashboard_page_id)
    logger.info("Deleted %d blocks", deleted)

    write_dashboard(client, config.dashboard_page_id, blocks)
    logger.info("Dashboard updated successfully")


if __name__ == "__main__":
    main()
