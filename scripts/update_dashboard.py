#!/usr/bin/env python3
"""Regenerate the Notion dashboard with 4-week training and health trend tables."""

import argparse
import calendar
import logging
import os
from dataclasses import dataclass, field
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
    "Avg Heart Rate",
    "Power (W)",
    "RSS",
    "Critical Power (W)",
    "Cadence (spm)",
    "Stride Length (m)",
    "Ground Contact (ms)",
    "Vertical Oscillation (cm)",
    "Leg Spring Stiffness",
    "RPE",
    "Temperature (C)",
    "Wind Speed",
    "Source",
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
    feeling_pct: float = 0.0
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


@dataclass
class RunningPeriod:
    """Aggregated running performance metrics for one period."""

    label: str = ""
    run_count: int = 0
    total_km: float = 0.0
    total_duration_min: int = 0
    avg_power_w: float = 0.0
    total_rss: float = 0.0
    avg_rss_per_run: float = 0.0
    avg_critical_power_w: float = 0.0
    avg_cadence_spm: float = 0.0
    avg_stride_length_m: float = 0.0
    avg_ground_contact_ms: float = 0.0
    avg_vertical_oscillation_cm: float = 0.0
    avg_leg_spring_stiffness: float = 0.0
    avg_rpe: float = 0.0
    avg_hr: float = 0.0
    power_to_hr_ratio: float = 0.0
    avg_pace_min_per_km: float = 0.0


@dataclass
class TrainingLoad:
    """Training load and ACWR analysis."""

    label: str = ""
    weekly_rss: float = 0.0
    acute_load: float = 0.0
    chronic_load: float = 0.0
    acwr: float = 0.0
    load_status: str = ""


@dataclass
class DashboardData:
    """Bundles all computed dashboard data."""

    training_weeks: list[TrainingWeek] = field(default_factory=list)
    health_weeks: list[HealthWeek] = field(default_factory=list)
    running_periods: list[RunningPeriod] = field(default_factory=list)
    training_load: TrainingLoad = field(default_factory=TrainingLoad)
    overreaching_warnings: list[str] = field(default_factory=list)
    training_db_id: str = ""
    health_db_id: str = ""
    weekly_stats_db_id: str | None = None
    subpage_ids: dict[str, str] = field(default_factory=dict)
    # Insight strings
    running_power_insight: str = ""
    running_biomechanics_insight: str = ""
    running_takeaway: str = ""
    training_running_trend: str = ""
    training_strength_insight: str = ""
    training_recovery_insight: str = ""
    training_takeaway: str = ""
    health_sleep_insight: str = ""
    health_hr_insight: str = ""
    health_recovery_insight: str = ""
    health_takeaway: str = ""
    correlation_insight: str = ""


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
    return get_period_boundaries(today, "week", 4)


def get_period_boundaries(
    today: date, period_type: str, count: int
) -> list[tuple[date, date, str]]:
    """Return (start, end, label) tuples for the last N periods, most recent first.

    period_type: "week", "month", "quarter", "year"
    """
    periods: list[tuple[date, date, str]] = []

    if period_type == "week":
        current_monday = today - timedelta(days=today.weekday())
        for i in range(count):
            monday = current_monday - timedelta(weeks=i)
            sunday = monday + timedelta(days=6)
            label = f"{monday.strftime('%b %d')} – {sunday.strftime('%b %d')}"
            periods.append((monday, sunday, label))

    elif period_type == "month":
        y, m = today.year, today.month
        for _ in range(count):
            first = date(y, m, 1)
            last_day = calendar.monthrange(y, m)[1]
            last = date(y, m, last_day)
            label = first.strftime("%b %Y")
            periods.append((first, last, label))
            m -= 1
            if m < 1:
                m = 12
                y -= 1

    elif period_type == "quarter":
        q = (today.month - 1) // 3 + 1
        y = today.year
        for _ in range(count):
            first_month = (q - 1) * 3 + 1
            last_month = first_month + 2
            first = date(y, first_month, 1)
            last_day = calendar.monthrange(y, last_month)[1]
            last = date(y, last_month, last_day)
            label = f"Q{q} {y}"
            periods.append((first, last, label))
            q -= 1
            if q < 1:
                q = 4
                y -= 1

    elif period_type == "year":
        y = today.year
        for _ in range(count):
            first = date(y, 1, 1)
            last = date(y, 12, 31)
            label = str(y)
            periods.append((first, last, label))
            y -= 1

    return periods


def group_by_period(
    records: list[dict[str, Any]],
    periods: list[tuple[date, date, str]],
    date_key: str = "date",
) -> list[list[dict[str, Any]]]:
    """Bucket records into periods. Returns one list per period, same order."""
    buckets: list[list[dict[str, Any]]] = [[] for _ in periods]
    for record in records:
        d = record.get(date_key)
        if d is None:
            continue
        if isinstance(d, str):
            d = date.fromisoformat(d)
        for idx, (start, end, _label) in enumerate(periods):
            if start <= d <= end:
                buckets[idx].append(record)
                break
    return buckets


# Alias for backwards compatibility
group_by_week = group_by_period


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
        "avg_hr": _get_number(props.get("Avg Heart Rate", {})),
        "power_w": _get_number(props.get("Power (W)", {})),
        "rss": _get_number(props.get("RSS", {})),
        "critical_power_w": _get_number(props.get("Critical Power (W)", {})),
        "cadence_spm": _get_number(props.get("Cadence (spm)", {})),
        "stride_length_m": _get_number(props.get("Stride Length (m)", {})),
        "ground_contact_ms": _get_number(props.get("Ground Contact (ms)", {})),
        "vertical_oscillation_cm": _get_number(props.get("Vertical Oscillation (cm)", {})),
        "leg_spring_stiffness": _get_number(props.get("Leg Spring Stiffness", {})),
        "rpe": _get_number(props.get("RPE", {})),
        "temperature_c": _get_number(props.get("Temperature (C)", {})),
        "wind_speed": _get_number(props.get("Wind Speed", {})),
        "source": _get_select(props.get("Source", {})),
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

    # Feeling %: proportion of Good/Great sessions
    good_great = sum(1 for f in feeling_scores if f >= 4)
    tw.feeling_pct = round(good_great / len(feeling_scores) * 100, 0) if feeling_scores else 0.0

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


def calculate_running_period(
    records: list[dict[str, Any]], label: str
) -> RunningPeriod:
    """Compute running performance metrics for one period's records."""
    rp = RunningPeriod(label=label)

    runs = [r for r in records if r.get("training_type") in RUNNING_TYPES]
    rp.run_count = len(runs)
    if not runs:
        return rp

    power_vals: list[float] = []
    rss_vals: list[float] = []
    cp_vals: list[float] = []
    cadence_vals: list[float] = []
    stride_vals: list[float] = []
    gct_vals: list[float] = []
    vosc_vals: list[float] = []
    lss_vals: list[float] = []
    rpe_vals: list[float] = []
    hr_vals: list[float] = []

    for r in runs:
        distance = r.get("distance_km") or 0.0
        duration = r.get("duration_min") or 0
        rp.total_km += float(distance)
        rp.total_duration_min += int(duration)

        if r.get("power_w") is not None:
            power_vals.append(float(r["power_w"]))
        if r.get("rss") is not None:
            rss_vals.append(float(r["rss"]))
            rp.total_rss += float(r["rss"])
        if r.get("critical_power_w") is not None:
            cp_vals.append(float(r["critical_power_w"]))
        if r.get("cadence_spm") is not None:
            cadence_vals.append(float(r["cadence_spm"]))
        if r.get("stride_length_m") is not None:
            stride_vals.append(float(r["stride_length_m"]))
        if r.get("ground_contact_ms") is not None:
            gct_vals.append(float(r["ground_contact_ms"]))
        if r.get("vertical_oscillation_cm") is not None:
            vosc_vals.append(float(r["vertical_oscillation_cm"]))
        if r.get("leg_spring_stiffness") is not None:
            lss_vals.append(float(r["leg_spring_stiffness"]))
        if r.get("rpe") is not None:
            rpe_vals.append(float(r["rpe"]))
        if r.get("avg_hr") is not None:
            hr_vals.append(float(r["avg_hr"]))

    rp.total_km = round(rp.total_km, 1)
    rp.total_rss = round(rp.total_rss, 1)
    rp.avg_rss_per_run = round(rp.total_rss / rp.run_count, 1) if rp.run_count else 0.0
    rp.avg_power_w = _safe_avg(power_vals)
    rp.avg_critical_power_w = _safe_avg(cp_vals)
    rp.avg_cadence_spm = _safe_avg(cadence_vals)
    rp.avg_stride_length_m = _safe_avg(stride_vals)
    rp.avg_ground_contact_ms = _safe_avg(gct_vals)
    rp.avg_vertical_oscillation_cm = _safe_avg(vosc_vals)
    rp.avg_leg_spring_stiffness = _safe_avg(lss_vals)
    rp.avg_rpe = _safe_avg(rpe_vals)
    rp.avg_hr = _safe_avg(hr_vals)
    rp.power_to_hr_ratio = (
        round(rp.avg_power_w / rp.avg_hr, 2) if rp.avg_hr > 0 and rp.avg_power_w > 0 else 0.0
    )
    rp.avg_pace_min_per_km = (
        round(rp.total_duration_min / rp.total_km, 2) if rp.total_km > 0 else 0.0
    )

    return rp


# ---------------------------------------------------------------------------
# Training load & ACWR (pure)
# ---------------------------------------------------------------------------


def calculate_training_load(running_periods: list[RunningPeriod]) -> TrainingLoad:
    """Calculate ACWR from weekly running periods (most recent first)."""
    tl = TrainingLoad()
    if not running_periods:
        return tl

    tl.acute_load = running_periods[0].total_rss
    tl.weekly_rss = tl.acute_load

    chronic_periods = running_periods[1:4] if len(running_periods) > 1 else []
    if chronic_periods:
        tl.chronic_load = round(
            sum(rp.total_rss for rp in chronic_periods) / len(chronic_periods), 1
        )
    else:
        tl.chronic_load = tl.acute_load

    tl.acwr = round(tl.acute_load / tl.chronic_load, 2) if tl.chronic_load > 0 else 0.0

    if tl.acwr < 0.8:
        tl.load_status = "detraining"
    elif tl.acwr <= 1.3:
        tl.load_status = "optimal"
    elif tl.acwr <= 1.5:
        tl.load_status = "caution"
    else:
        tl.load_status = "danger"

    tl.label = f"ACWR {tl.acwr} ({tl.load_status})"
    return tl


def detect_overreaching(
    load: TrainingLoad,
    health_weeks: list[HealthWeek],
) -> list[str]:
    """Flag potential overreaching: high ACWR + declining health markers."""
    warnings: list[str] = []
    if load.acwr < 1.3 or len(health_weeks) < 2:
        return warnings

    current_hw = health_weeks[0]
    prior_hw = health_weeks[1:]

    avg_battery = _safe_avg([hw.avg_body_battery for hw in prior_hw])
    if avg_battery > 0 and current_hw.avg_body_battery < avg_battery * 0.9:
        warnings.append(
            f"Body battery declining ({current_hw.avg_body_battery} vs avg {avg_battery}) "
            f"with high training load (ACWR {load.acwr})"
        )

    avg_sleep = _safe_avg([hw.avg_sleep_hours for hw in prior_hw])
    if avg_sleep > 0 and current_hw.avg_sleep_hours < avg_sleep * 0.9:
        warnings.append(
            f"Sleep declining ({current_hw.avg_sleep_hours}h vs avg {avg_sleep}h) "
            f"with high training load"
        )

    avg_hr = _safe_avg([hw.avg_resting_hr for hw in prior_hw])
    if avg_hr > 0 and current_hw.avg_resting_hr > avg_hr * 1.1:
        warnings.append(
            f"Resting HR elevated ({current_hw.avg_resting_hr} vs avg {avg_hr}) "
            f"with high training load"
        )

    return warnings


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
# Themed insight generators (pure)
# ---------------------------------------------------------------------------


def generate_running_power_insight(periods: list[RunningPeriod]) -> str:
    """Generate power and load insight for running performance."""
    if not periods or periods[0].run_count == 0:
        return "No running data this period."

    current = periods[0]
    lines: list[str] = []
    lines.append(f"Avg Power: {_format_num(current.avg_power_w)}W")
    rss_per_run = _format_num(current.avg_rss_per_run)
    lines.append(f"Total RSS: {_format_num(current.total_rss)} ({rss_per_run}/run)")

    if len(periods) > 1:
        prior = periods[1:]
        avg_power = _safe_avg([p.avg_power_w for p in prior])
        d = trend_direction(current.avg_power_w, avg_power)
        lines.append(f"{_trend_arrow(d)} Power vs prior: {_format_num(avg_power)}W avg")

        avg_rss = _safe_avg([p.total_rss for p in prior])
        d = trend_direction(current.total_rss, avg_rss)
        lines.append(f"{_trend_arrow(d)} Load vs prior: {_format_num(avg_rss)} RSS avg")

    if current.power_to_hr_ratio > 0:
        lines.append(f"Power:HR ratio: {_format_num(current.power_to_hr_ratio, 2)}")

    return "\n".join(lines)


def generate_running_biomechanics_insight(periods: list[RunningPeriod]) -> str:
    """Generate biomechanics insight for running performance."""
    if not periods or periods[0].run_count == 0:
        return "No running biomechanics data."

    current = periods[0]
    lines: list[str] = []

    if current.avg_cadence_spm > 0:
        lines.append(f"Cadence: {_format_num(current.avg_cadence_spm)} spm")
    if current.avg_stride_length_m > 0:
        lines.append(f"Stride: {_format_num(current.avg_stride_length_m, 2)}m")
    if current.avg_ground_contact_ms > 0:
        lines.append(f"Ground Contact: {_format_num(current.avg_ground_contact_ms)}ms")
    if current.avg_vertical_oscillation_cm > 0:
        lines.append(f"Vert Oscillation: {_format_num(current.avg_vertical_oscillation_cm)}cm")
    if current.avg_leg_spring_stiffness > 0:
        lines.append(f"Leg Spring: {_format_num(current.avg_leg_spring_stiffness)}")

    if len(periods) > 1:
        prior = periods[1:]
        if current.avg_cadence_spm > 0:
            avg_cad = _safe_avg([p.avg_cadence_spm for p in prior])
            if avg_cad > 0:
                d = trend_direction(current.avg_cadence_spm, avg_cad)
                lines.append(f"{_trend_arrow(d)} Cadence vs prior: {_format_num(avg_cad)} spm")
        if current.avg_ground_contact_ms > 0:
            avg_gct = _safe_avg([p.avg_ground_contact_ms for p in prior])
            if avg_gct > 0:
                d = trend_direction(current.avg_ground_contact_ms, avg_gct)
                lines.append(f"{_trend_arrow(d)} GCT vs prior: {_format_num(avg_gct)}ms")

    return "\n".join(lines) if lines else "No biomechanics data available."


def generate_running_takeaway(periods: list[RunningPeriod]) -> str:
    """Generate a running-specific takeaway."""
    if not periods or periods[0].run_count == 0:
        return "No runs this period."

    current = periods[0]
    parts: list[str] = [
        f"{current.run_count} runs, {_format_num(current.total_km)}km"
    ]
    if current.avg_power_w > 0:
        parts.append(f"{_format_num(current.avg_power_w)}W avg power")
    if current.avg_pace_min_per_km > 0:
        pace_min = int(current.avg_pace_min_per_km)
        pace_sec = int((current.avg_pace_min_per_km - pace_min) * 60)
        parts.append(f"{pace_min}:{pace_sec:02d}/km avg pace")
    if current.avg_rpe > 0:
        parts.append(f"RPE {_format_num(current.avg_rpe)}")

    return "Running: " + ", ".join(parts) + "."


def generate_sleep_insight(health_weeks: list[HealthWeek]) -> str:
    """Generate sleep-specific insight."""
    if not health_weeks or health_weeks[0].entries == 0:
        return "No sleep data."

    current = health_weeks[0]
    lines: list[str] = [f"Avg: {_format_num(current.avg_sleep_hours)}h"]
    if current.sleep_quality_mode:
        lines.append(f"Quality: {current.sleep_quality_mode}")

    if len(health_weeks) > 1:
        prior = health_weeks[1:]
        avg_sleep = _safe_avg([hw.avg_sleep_hours for hw in prior])
        d = trend_direction(current.avg_sleep_hours, avg_sleep)
        lines.append(f"{_trend_arrow(d)} vs prior avg {_format_num(avg_sleep)}h")

    return "\n".join(lines)


def generate_hr_insight(health_weeks: list[HealthWeek]) -> str:
    """Generate resting HR insight."""
    if not health_weeks or health_weeks[0].entries == 0:
        return "No HR data."

    current = health_weeks[0]
    lines: list[str] = [f"Avg: {_format_num(current.avg_resting_hr)} bpm"]

    if len(health_weeks) > 1:
        prior = health_weeks[1:]
        avg_hr = _safe_avg([hw.avg_resting_hr for hw in prior])
        d = trend_direction(current.avg_resting_hr, avg_hr)
        # Lower HR is better
        color_hint = "good" if d == "down" else ("watch" if d == "up" else "stable")
        lines.append(f"{_trend_arrow(d)} vs prior avg {_format_num(avg_hr)} bpm ({color_hint})")

    return "\n".join(lines)


def generate_recovery_health_insight(health_weeks: list[HealthWeek]) -> str:
    """Generate recovery/body battery insight."""
    if not health_weeks or health_weeks[0].entries == 0:
        return "No recovery data."

    current = health_weeks[0]
    lines: list[str] = []
    if current.avg_body_battery > 0:
        lines.append(f"Body Battery: {_format_num(current.avg_body_battery)}")
    if current.avg_steps > 0:
        lines.append(f"Avg Steps: {_format_num(current.avg_steps, 0)}")
    if current.sick_days > 0:
        lines.append(f"Sick days: {current.sick_days}")
    if current.rest_days > 0:
        lines.append(f"Rest days: {current.rest_days}")

    if len(health_weeks) > 1:
        prior = health_weeks[1:]
        avg_battery = _safe_avg([hw.avg_body_battery for hw in prior])
        if avg_battery > 0 and current.avg_body_battery > 0:
            d = trend_direction(current.avg_body_battery, avg_battery)
            lines.append(f"{_trend_arrow(d)} Battery vs prior: {_format_num(avg_battery)}")

    return "\n".join(lines) if lines else "No recovery data available."


def generate_running_trend_insight(
    weeks: list[TrainingWeek], running_periods: list[RunningPeriod]
) -> str:
    """Generate running trend insight for training callouts."""
    if not weeks or not running_periods or running_periods[0].run_count == 0:
        return "No running data."

    current_rp = running_periods[0]
    current_tw = weeks[0]
    lines: list[str] = [
        f"{current_rp.run_count} runs, {_format_num(current_rp.total_km)}km"
    ]
    if current_tw.longest_run_km > 0:
        lines.append(f"Longest: {_format_num(current_tw.longest_run_km)}km")
    if current_rp.avg_power_w > 0:
        lines.append(f"Avg power: {_format_num(current_rp.avg_power_w)}W")

    if len(weeks) > 1:
        avg_km = _safe_avg([w.running_km for w in weeks[1:]])
        d = trend_direction(current_tw.running_km, avg_km)
        lines.append(f"{_trend_arrow(d)} Volume vs prior: {_format_num(avg_km)}km")

    return "\n".join(lines)


def generate_strength_insight(weeks: list[TrainingWeek]) -> str:
    """Generate strength training insight."""
    if not weeks:
        return "No training data."

    current = weeks[0]
    if current.gym_sessions == 0:
        return "No gym sessions this period."

    lines: list[str] = [
        f"{current.gym_sessions} sessions, {_format_num(current.gym_volume)}kg total"
    ]
    if current.gym_volume_per_session > 0:
        lines.append(f"{_format_num(current.gym_volume_per_session)}kg/session")

    if len(weeks) > 1:
        prior = weeks[1:]
        avg_vol = _safe_avg([w.gym_volume for w in prior])
        d = trend_direction(current.gym_volume, avg_vol)
        lines.append(f"{_trend_arrow(d)} Volume vs prior: {_format_num(avg_vol)}kg")

    return "\n".join(lines)


def generate_recovery_insight(
    weeks: list[TrainingWeek], health_weeks: list[HealthWeek]
) -> str:
    """Generate recovery signal from training + health data."""
    if not weeks:
        return "No data."

    current_tw = weeks[0]
    lines: list[str] = []

    if current_tw.feeling_pct > 0:
        lines.append(f"Feeling good/great: {_format_num(current_tw.feeling_pct)}%")
    if current_tw.tough_sessions > 0:
        lines.append(f"Tough sessions: {current_tw.tough_sessions}")

    if health_weeks and health_weeks[0].entries > 0:
        hw = health_weeks[0]
        if hw.avg_body_battery > 0:
            lines.append(f"Body battery: {_format_num(hw.avg_body_battery)}")
        if hw.avg_resting_hr > 0:
            lines.append(f"Resting HR: {_format_num(hw.avg_resting_hr)} bpm")

    return "\n".join(lines) if lines else "No recovery data."


def generate_correlation_insights(
    weeks: list[TrainingWeek],
    health_weeks: list[HealthWeek],
    running_periods: list[RunningPeriod],
    load: TrainingLoad,
) -> str:
    """Generate health-training correlation insights."""
    lines: list[str] = []

    if load.acwr > 0:
        lines.append(f"Training load: ACWR {load.acwr} ({load.load_status})")
        if load.load_status == "optimal":
            lines.append("Training load is in the optimal zone (0.8-1.3)")
        elif load.load_status == "caution":
            lines.append("Training load is elevated — monitor recovery closely")
        elif load.load_status == "danger":
            lines.append("Training load spike detected — high injury risk")
        elif load.load_status == "detraining":
            lines.append("Training load is low — consider increasing volume")

    if weeks and health_weeks and len(weeks) > 1 and len(health_weeks) > 1:
        current_tw = weeks[0]
        current_hw = health_weeks[0]
        prior_tw = weeks[1:]
        prior_hw = health_weeks[1:]

        avg_dur = _safe_avg([float(w.total_duration_min) for w in prior_tw])
        avg_battery = _safe_avg([hw.avg_body_battery for hw in prior_hw])

        if avg_dur > 0 and avg_battery > 0:
            dur_trend = trend_direction(float(current_tw.total_duration_min), avg_dur)
            bat_trend = trend_direction(current_hw.avg_body_battery, avg_battery)

            if dur_trend == "up" and bat_trend == "down":
                lines.append(
                    "Training volume up while body battery declining — watch for overtraining"
                )
            elif dur_trend == "up" and bat_trend == "up":
                lines.append("Training volume and recovery both improving — good adaptation")

    return "\n".join(lines) if lines else "Insufficient data for correlation analysis."


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
        "Period",
        "Sessions",
        "Active Days",
        "Runs",
        "Run km",
        "Longest Run",
        "Gym Sessions",
        "Gym Vol (kg)",
        "Vol/Session",
        "Feeling %",
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
                _cell(float(w.running_count), "running_count", is_current),
                _cell(w.running_km, "running_km", is_current),
                _cell(w.longest_run_km, "longest_run_km", is_current),
                _cell(float(w.gym_sessions), "gym_sessions", is_current),
                _cell(w.gym_volume, "gym_volume", is_current),
                _cell(w.gym_volume_per_session, "gym_volume_per_session", is_current),
                _cell(w.feeling_pct, "feeling_pct", is_current),
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


# ---------------------------------------------------------------------------
# Column layout builders
# ---------------------------------------------------------------------------


def build_column_list(columns: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a column_list block containing column blocks."""
    return {
        "object": "block",
        "type": "column_list",
        "column_list": {"children": columns},
    }


def build_column(children: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a column block with children."""
    return {
        "object": "block",
        "type": "column",
        "column": {"children": children},
    }


# ---------------------------------------------------------------------------
# Running performance table
# ---------------------------------------------------------------------------


def build_running_table(periods: list[RunningPeriod]) -> dict[str, Any]:
    """Build the running performance table block with colored values."""
    headers = [
        "Period",
        "Runs",
        "Distance",
        "Avg Power",
        "Total RSS",
        "RSS/Run",
        "Avg CP",
        "Cadence",
        "Stride",
        "GCT",
        "Vert Osc",
        "Leg Spring",
        "Power:HR",
        "Avg RPE",
    ]
    header_row = build_table_row([[build_text(h, bold=True)] for h in headers])
    rows = [header_row]

    prior = periods[1:] if len(periods) > 1 else []

    def _prior_avg(attr: str) -> float:
        return _safe_avg([float(getattr(pp, attr)) for pp in prior])

    def _cell(
        val: float, attr: str, is_current: bool, higher: bool = True, decimals: int = 1
    ) -> list[dict[str, Any]]:
        if is_current and prior:
            color = _color_for_value(val, _prior_avg(attr), higher)
            return [build_text(_format_num(val, decimals), color=color)]
        return [build_text(_format_num(val, decimals))]

    for i, rp in enumerate(periods):
        is_current = i == 0
        row = build_table_row(
            [
                [build_text(rp.label, bold=is_current)],
                _cell(float(rp.run_count), "run_count", is_current),
                _cell(rp.total_km, "total_km", is_current),
                _cell(rp.avg_power_w, "avg_power_w", is_current),
                _cell(rp.total_rss, "total_rss", is_current),
                _cell(rp.avg_rss_per_run, "avg_rss_per_run", is_current),
                _cell(rp.avg_critical_power_w, "avg_critical_power_w", is_current),
                _cell(rp.avg_cadence_spm, "avg_cadence_spm", is_current),
                _cell(rp.avg_stride_length_m, "avg_stride_length_m", is_current, decimals=2),
                _cell(rp.avg_ground_contact_ms, "avg_ground_contact_ms", is_current, higher=False),
                _cell(
                    rp.avg_vertical_oscillation_cm,
                    "avg_vertical_oscillation_cm", is_current, higher=False,
                ),
                _cell(rp.avg_leg_spring_stiffness, "avg_leg_spring_stiffness", is_current),
                _cell(rp.power_to_hr_ratio, "power_to_hr_ratio", is_current, decimals=2),
                _cell(rp.avg_rpe, "avg_rpe", is_current, higher=False),
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


# ---------------------------------------------------------------------------
# Training load & correlation section
# ---------------------------------------------------------------------------


def build_load_correlation_section(
    load: TrainingLoad,
    warnings: list[str],
    insight: str,
) -> list[dict[str, Any]]:
    """Build the training load & recovery section blocks."""
    blocks: list[dict[str, Any]] = []

    # ACWR callout colored by load status
    color_map = {
        "optimal": "green_background",
        "caution": "yellow_background",
        "danger": "red_background",
        "detraining": "gray_background",
    }
    acwr_color = color_map.get(load.load_status, "default")
    acwr_text = (
        f"ACWR: {load.acwr} — {load.load_status.upper()}\n"
        f"Acute (this week): {_format_num(load.acute_load)} RSS\n"
        f"Chronic (3-wk avg): {_format_num(load.chronic_load)} RSS"
    )
    blocks.append(build_callout(acwr_text, icon="chart", color=acwr_color))

    # Overreaching warnings
    for w in warnings:
        blocks.append(build_callout(w, icon="warning", color="red_background"))

    # Correlation insight
    if insight:
        blocks.append(build_callout(insight, icon="info", color="blue_background"))

    return blocks


# ---------------------------------------------------------------------------
# Subpage builders
# ---------------------------------------------------------------------------


def find_or_create_subpage(
    client: NotionClient, parent_page_id: str, title: str
) -> str:
    """Find existing subpage by title or create it. Returns page_id."""
    children = client.get_block_children(parent_page_id)
    for block in children:
        if block.get("type") == "child_page" and block["child_page"]["title"] == title:
            return block["id"].replace("-", "")
    page = client.create_page_under_page(parent_page_id, title)
    return page["id"].replace("-", "")


def build_subpage_dashboard(
    training_records: list[dict[str, Any]],
    health_records: list[dict[str, Any]],
    today: date,
    period_type: str,
    count: int,
    title: str,
) -> list[dict[str, Any]]:
    """Build the complete content blocks for a subpage report."""
    now_str = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
    blocks: list[dict[str, Any]] = []

    # Header
    blocks.append(
        build_callout(
            f"{title} — auto-updated {now_str}",
            icon="chart",
            color="blue_background",
        )
    )

    periods = get_period_boundaries(today, period_type, count)
    training_by_period = group_by_period(training_records, periods)
    health_by_period = group_by_period(health_records, periods)

    # Training section
    training_weeks = [
        calculate_training_week(records, label)
        for records, (_s, _e, label) in zip(training_by_period, periods, strict=True)
    ]
    blocks.append(build_heading_2("Training Trends"))
    blocks.append(build_training_table(training_weeks))
    blocks.append(build_divider())

    # Running section
    running_periods = [
        calculate_running_period(records, label)
        for records, (_s, _e, label) in zip(training_by_period, periods, strict=True)
    ]
    blocks.append(build_heading_2("Running Performance"))
    blocks.append(build_running_table(running_periods))
    blocks.append(build_divider())

    # Health section
    health_weeks = [
        calculate_health_week(records, label)
        for records, (_s, _e, label) in zip(health_by_period, periods, strict=True)
    ]
    blocks.append(build_heading_2("Health Trends"))
    blocks.append(build_health_table(health_weeks))

    return blocks


def build_full_dashboard(data: DashboardData) -> list[dict[str, Any]]:
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

    # --- 4-WEEK TRAINING TRENDS ---
    blocks.append(build_heading_2("4-Week Training Trends"))
    blocks.append(build_training_table(data.training_weeks))

    # 3-column training callouts
    blocks.append(
        build_column_list([
            build_column([
                build_callout(data.training_running_trend, icon="chart", color="green_background"),
            ]),
            build_column([
                build_callout(
                    data.training_strength_insight, icon="fire", color="orange_background",
                ),
            ]),
            build_column([
                build_callout(
                    data.training_recovery_insight, icon="heart", color="pink_background",
                ),
            ]),
        ])
    )
    blocks.append(build_callout(data.training_takeaway, icon="fire", color="yellow_background"))
    blocks.append(build_divider())

    # --- RUNNING PERFORMANCE ---
    blocks.append(build_heading_2("Running Performance"))
    blocks.append(build_running_table(data.running_periods))

    # 2-column running callouts
    blocks.append(
        build_column_list([
            build_column([
                build_callout(data.running_power_insight, icon="chart", color="blue_background"),
            ]),
            build_column([
                build_callout(
                    data.running_biomechanics_insight, icon="chart", color="purple_background",
                ),
            ]),
        ])
    )
    blocks.append(build_callout(data.running_takeaway, icon="chart", color="yellow_background"))
    blocks.append(build_divider())

    # --- HEALTH TRENDS ---
    blocks.append(build_heading_2("4-Week Health Trends"))
    blocks.append(build_health_table(data.health_weeks))

    # 3-column health callouts
    blocks.append(
        build_column_list([
            build_column([
                build_callout(data.health_sleep_insight, icon="info", color="blue_background"),
            ]),
            build_column([
                build_callout(data.health_hr_insight, icon="heart", color="green_background"),
            ]),
            build_column([
                build_callout(
                    data.health_recovery_insight, icon="chart", color="purple_background",
                ),
            ]),
        ])
    )
    blocks.append(build_callout(data.health_takeaway, icon="heart", color="pink_background"))
    blocks.append(build_divider())

    # --- TRAINING LOAD & RECOVERY ---
    blocks.append(build_heading_2("Training Load & Recovery"))
    blocks.extend(
        build_load_correlation_section(
            data.training_load,
            data.overreaching_warnings,
            data.correlation_insight,
        )
    )
    blocks.append(build_divider())

    # --- DATABASES ---
    blocks.append(build_heading_2("Databases"))
    db_cols = [
        build_column([
            build_paragraph([
                build_text("Training Sessions: "),
                {
                    "type": "mention",
                    "mention": {"type": "database", "database": {"id": data.training_db_id}},
                },
            ])
        ]),
        build_column([
            build_paragraph([
                build_text("Health Status Log: "),
                {
                    "type": "mention",
                    "mention": {"type": "database", "database": {"id": data.health_db_id}},
                },
            ])
        ]),
    ]
    if data.weekly_stats_db_id:
        db_cols.append(
            build_column([
                build_paragraph([
                    build_text("Weekly Statistics: "),
                    {
                        "type": "mention",
                        "mention": {
                            "type": "database",
                            "database": {"id": data.weekly_stats_db_id},
                        },
                    },
                ])
            ])
        )
    blocks.append(build_column_list(db_cols))
    blocks.append(build_divider())

    # --- REPORTS ---
    if data.subpage_ids:
        blocks.append(build_heading_2("Reports"))
        for _title, page_id in data.subpage_ids.items():
            blocks.append(
                build_paragraph([
                    {
                        "type": "mention",
                        "mention": {"type": "page", "page": {"id": page_id}},
                    },
                ])
            )
        blocks.append(build_divider())

    # --- TOGGLES ---
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
                        build_text("Stryd", bold=True),
                        build_text(" — GitHub Actions, every 6h"),
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

    # Metric definitions (expanded with running + ACWR defs)
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
                        build_text("Feeling %", bold=True),
                        build_text(
                            " — Percentage of sessions rated Good or Great"
                        ),
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
                        build_text("Power (W)", bold=True),
                        build_text(
                            " — Average running power from Stryd (watts)"
                        ),
                    ]
                ),
                build_paragraph(
                    [
                        build_text("RSS", bold=True),
                        build_text(
                            " — Running Stress Score from Stryd (training load per run)"
                        ),
                    ]
                ),
                build_paragraph(
                    [
                        build_text("ACWR", bold=True),
                        build_text(
                            " — Acute:Chronic Workload Ratio. <0.8 detraining, "
                            "0.8-1.3 optimal, 1.3-1.5 caution, >1.5 danger"
                        ),
                    ]
                ),
                build_paragraph(
                    [
                        build_text("Power:HR Ratio", bold=True),
                        build_text(
                            " — Running efficiency (higher = more power per heartbeat)"
                        ),
                    ]
                ),
                build_paragraph(
                    [
                        build_text("Cadence (spm)", bold=True),
                        build_text(" — Steps per minute while running"),
                    ]
                ),
                build_paragraph(
                    [
                        build_text("Stride Length (m)", bold=True),
                        build_text(" — Average stride length in meters"),
                    ]
                ),
                build_paragraph(
                    [
                        build_text("Ground Contact Time (ms)", bold=True),
                        build_text(
                            " — Time foot spends on ground per step (lower = better)"
                        ),
                    ]
                ),
                build_paragraph(
                    [
                        build_text("Vertical Oscillation (cm)", bold=True),
                        build_text(
                            " — Vertical bounce per step (lower = more efficient)"
                        ),
                    ]
                ),
                build_paragraph(
                    [
                        build_text("Leg Spring Stiffness", bold=True),
                        build_text(
                            " — Running economy metric (higher = better energy return)"
                        ),
                    ]
                ),
                build_paragraph(
                    [
                        build_text("RPE", bold=True),
                        build_text(
                            " — Rate of Perceived Exertion (1-10, from Stryd)"
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
                            " — Green = improving vs prior avg, "
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


def _compute_dashboard_data(
    training_records: list[dict[str, Any]],
    health_records: list[dict[str, Any]],
    today: date,
    config: DashboardConfig,
) -> DashboardData:
    """Compute all dashboard metrics from raw records (pure, no side effects)."""
    weeks = get_week_boundaries(today)

    # Group by week
    training_by_week = group_by_period(training_records, weeks)
    health_by_week = group_by_period(health_records, weeks)

    # Calculate weekly metrics
    training_weeks = [
        calculate_training_week(records, label)
        for records, (_s, _e, label) in zip(training_by_week, weeks, strict=True)
    ]
    health_weeks = [
        calculate_health_week(records, label)
        for records, (_s, _e, label) in zip(health_by_week, weeks, strict=True)
    ]
    running_periods = [
        calculate_running_period(records, label)
        for records, (_s, _e, label) in zip(training_by_week, weeks, strict=True)
    ]

    # Training load
    training_load = calculate_training_load(running_periods)
    overreaching_warnings = detect_overreaching(training_load, health_weeks)

    # Build DashboardData
    data = DashboardData(
        training_weeks=training_weeks,
        health_weeks=health_weeks,
        running_periods=running_periods,
        training_load=training_load,
        overreaching_warnings=overreaching_warnings,
        training_db_id=config.training_db_id,
        health_db_id=config.health_db_id,
    )

    # Generate all insights
    data.running_power_insight = generate_running_power_insight(running_periods)
    data.running_biomechanics_insight = generate_running_biomechanics_insight(running_periods)
    data.running_takeaway = generate_running_takeaway(running_periods)
    data.training_running_trend = generate_running_trend_insight(training_weeks, running_periods)
    data.training_strength_insight = generate_strength_insight(training_weeks)
    data.training_recovery_insight = generate_recovery_insight(training_weeks, health_weeks)
    data.training_takeaway = generate_training_takeaway(training_weeks)
    data.health_sleep_insight = generate_sleep_insight(health_weeks)
    data.health_hr_insight = generate_hr_insight(health_weeks)
    data.health_recovery_insight = generate_recovery_health_insight(health_weeks)
    data.health_takeaway = generate_health_takeaway(health_weeks)
    data.correlation_insight = generate_correlation_insights(
        training_weeks, health_weeks, running_periods, training_load
    )

    return data


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

    # Compute earliest date needed across all timeframes:
    # weeks(4), months(6), quarters(4), years(2) — years goes furthest back
    year_periods = get_period_boundaries(today, "year", 2)
    earliest_date = year_periods[-1][0]

    weeks = get_week_boundaries(today)
    logger.info("Fetching data from %s to %s", earliest_date, today)

    if args.dry_run:
        logger.info("[DRY RUN] Would fetch training and health data from Notion")
        logger.info("[DRY RUN] Week boundaries:")
        for start, end, label in weeks:
            logger.info("  %s: %s to %s", label, start, end)
        for period_type, count in [("month", 6), ("quarter", 4), ("year", 2)]:
            periods = get_period_boundaries(today, period_type, count)
            logger.info("[DRY RUN] %s boundaries:", period_type)
            for start, end, label in periods:
                logger.info("  %s: %s to %s", label, start, end)
        logger.info("[DRY RUN] No changes written to Notion")
        return

    try:
        client = NotionClient()
    except ConfigurationError as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from exc

    # Single fetch of all data
    training_records = fetch_training_data(client, config, earliest_date)
    health_records = fetch_health_data(client, config, earliest_date)

    logger.info(
        "Fetched %d training records, %d health records",
        len(training_records),
        len(health_records),
    )

    # Compute header page data
    data = _compute_dashboard_data(training_records, health_records, today, config)

    # Log metrics
    for tw in data.training_weeks:
        logger.info(
            "Training %s: %d sessions, %dmin, %.1fkg gym, %.1fkm run",
            tw.label,
            tw.sessions,
            tw.total_duration_min,
            tw.gym_volume,
            tw.running_km,
        )
    for rp in data.running_periods:
        logger.info(
            "Running %s: %d runs, %.1fkm, %.1fW power, %.1f RSS",
            rp.label,
            rp.run_count,
            rp.total_km,
            rp.avg_power_w,
            rp.total_rss,
        )
    for hw in data.health_weeks:
        logger.info(
            "Health %s: %.1fh sleep (%s), %.0f HR, %.0f steps",
            hw.label,
            hw.avg_sleep_hours,
            hw.sleep_quality_mode or "\u2014",
            hw.avg_resting_hr,
            hw.avg_steps,
        )
    logger.info(
        "Training load: ACWR %.2f (%s), acute=%.1f, chronic=%.1f",
        data.training_load.acwr,
        data.training_load.load_status,
        data.training_load.acute_load,
        data.training_load.chronic_load,
    )
    for w in data.overreaching_warnings:
        logger.warning("Overreaching: %s", w)

    # Find/create subpages and build their content
    subpage_configs = [
        ("Monthly Report", "month", 6),
        ("Quarterly Report", "quarter", 4),
        ("Yearly Report", "year", 2),
    ]
    for title, period_type, count in subpage_configs:
        page_id = find_or_create_subpage(client, config.dashboard_page_id, title)
        data.subpage_ids[title] = page_id
        logger.info("Subpage '%s': %s", title, page_id)

        subpage_blocks = build_subpage_dashboard(
            training_records, health_records, today, period_type, count, title
        )
        logger.info("Clearing subpage '%s'...", title)
        deleted = clear_page_blocks(client, page_id)
        logger.info("Deleted %d blocks from subpage '%s'", deleted, title)
        write_dashboard(client, page_id, subpage_blocks)
        logger.info("Subpage '%s' updated", title)

    # Build and write header page
    blocks = build_full_dashboard(data)

    logger.info("Clearing existing dashboard blocks...")
    deleted = clear_page_blocks(client, config.dashboard_page_id)
    logger.info("Deleted %d blocks", deleted)

    write_dashboard(client, config.dashboard_page_id, blocks)
    logger.info("Dashboard updated successfully")


if __name__ == "__main__":
    main()
