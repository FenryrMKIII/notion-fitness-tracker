"""Tests for scripts/update_dashboard.py — all pure functions."""

import os
from datetime import date
from typing import Any
from unittest import mock

import pytest

from scripts.update_dashboard import (
    DashboardData,
    HealthWeek,
    RunningPeriod,
    TrainingLoad,
    TrainingWeek,
    _color_for_value,
    _format_num,
    _most_common,
    _safe_avg,
    build_callout,
    build_column,
    build_column_list,
    build_divider,
    build_full_dashboard,
    build_heading_2,
    build_health_table,
    build_load_correlation_section,
    build_paragraph,
    build_running_table,
    build_subpage_dashboard,
    build_table_row,
    build_text,
    build_toggle,
    build_training_table,
    calculate_health_week,
    calculate_running_period,
    calculate_training_load,
    calculate_training_week,
    detect_overreaching,
    extract_health_props,
    extract_training_props,
    generate_correlation_insights,
    generate_health_insights,
    generate_health_takeaway,
    generate_hr_insight,
    generate_recovery_health_insight,
    generate_recovery_insight,
    generate_running_biomechanics_insight,
    generate_running_power_insight,
    generate_running_takeaway,
    generate_running_trend_insight,
    generate_sleep_insight,
    generate_strength_insight,
    generate_training_insights,
    generate_training_takeaway,
    get_env_config,
    get_period_boundaries,
    get_week_boundaries,
    group_by_period,
    group_by_week,
    trend_direction,
)

# ---------------------------------------------------------------------------
# get_env_config
# ---------------------------------------------------------------------------


class TestGetEnvConfig:
    def test_all_vars_present(self) -> None:
        env = {
            "NOTION_TRAINING_DB_ID": "train-id",
            "NOTION_HEALTH_DB_ID": "health-id",
            "NOTION_DASHBOARD_PAGE_ID": "page-id",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            cfg = get_env_config()
        assert cfg.training_db_id == "train-id"
        assert cfg.health_db_id == "health-id"
        assert cfg.dashboard_page_id == "page-id"

    def test_missing_vars_raises(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True), pytest.raises(
            Exception, match="Missing required"
        ):
            get_env_config()

    def test_partial_missing(self) -> None:
        env = {"NOTION_TRAINING_DB_ID": "train-id"}
        with mock.patch.dict(os.environ, env, clear=True), pytest.raises(
            Exception, match="NOTION_HEALTH_DB_ID"
        ):
            get_env_config()


# ---------------------------------------------------------------------------
# get_week_boundaries
# ---------------------------------------------------------------------------


class TestGetWeekBoundaries:
    def test_returns_4_weeks(self) -> None:
        weeks = get_week_boundaries(date(2026, 2, 8))  # Sunday
        assert len(weeks) == 4

    def test_weeks_are_monday_to_sunday(self) -> None:
        weeks = get_week_boundaries(date(2026, 2, 5))  # Thursday
        for monday, sunday, _ in weeks:
            assert monday.weekday() == 0  # Monday
            assert sunday.weekday() == 6  # Sunday

    def test_most_recent_first(self) -> None:
        weeks = get_week_boundaries(date(2026, 2, 5))
        mondays = [m for m, _s, _l in weeks]
        assert mondays == sorted(mondays, reverse=True)

    def test_labels_contain_dates(self) -> None:
        weeks = get_week_boundaries(date(2026, 2, 5))
        for _m, _s, label in weeks:
            assert "\u2013" in label

    def test_current_week_includes_today(self) -> None:
        today = date(2026, 2, 5)  # Thursday
        weeks = get_week_boundaries(today)
        monday, sunday, _ = weeks[0]
        assert monday <= today <= sunday


# ---------------------------------------------------------------------------
# get_period_boundaries (month / quarter / year)
# ---------------------------------------------------------------------------


class TestGetPeriodBoundaries:
    def test_month_count_and_labels(self) -> None:
        periods = get_period_boundaries(date(2026, 3, 15), "month", 6)
        assert len(periods) == 6
        assert periods[0][2] == "Mar 2026"
        assert periods[5][2] == "Oct 2025"

    def test_month_start_end(self) -> None:
        periods = get_period_boundaries(date(2026, 2, 15), "month", 1)
        start, end, _ = periods[0]
        assert start == date(2026, 2, 1)
        assert end == date(2026, 2, 28)

    def test_quarter_count_and_labels(self) -> None:
        periods = get_period_boundaries(date(2026, 5, 1), "quarter", 4)
        assert len(periods) == 4
        assert periods[0][2] == "Q2 2026"
        assert periods[1][2] == "Q1 2026"
        assert periods[2][2] == "Q4 2025"
        assert periods[3][2] == "Q3 2025"

    def test_quarter_boundaries(self) -> None:
        periods = get_period_boundaries(date(2026, 7, 15), "quarter", 1)
        start, end, label = periods[0]
        assert label == "Q3 2026"
        assert start == date(2026, 7, 1)
        assert end == date(2026, 9, 30)

    def test_year_count_and_labels(self) -> None:
        periods = get_period_boundaries(date(2026, 6, 1), "year", 2)
        assert len(periods) == 2
        assert periods[0][2] == "2026"
        assert periods[1][2] == "2025"

    def test_year_boundaries(self) -> None:
        periods = get_period_boundaries(date(2026, 1, 1), "year", 1)
        start, end, _ = periods[0]
        assert start == date(2026, 1, 1)
        assert end == date(2026, 12, 31)

    def test_month_wraps_year(self) -> None:
        periods = get_period_boundaries(date(2026, 1, 15), "month", 3)
        labels = [p[2] for p in periods]
        assert labels == ["Jan 2026", "Dec 2025", "Nov 2025"]


# ---------------------------------------------------------------------------
# group_by_week / group_by_period
# ---------------------------------------------------------------------------


class TestGroupByWeek:
    def test_basic_grouping(self) -> None:
        weeks = get_week_boundaries(date(2026, 2, 8))
        records = [
            {"date": "2026-02-03"},  # Week of Feb 2
            {"date": "2026-02-07"},  # Week of Feb 2
            {"date": "2026-01-27"},  # Week of Jan 26
        ]
        buckets = group_by_week(records, weeks)
        assert len(buckets[0]) == 2  # current week
        assert len(buckets[1]) == 1  # prior week

    def test_records_outside_range_excluded(self) -> None:
        weeks = get_week_boundaries(date(2026, 2, 8))
        records = [{"date": "2025-01-01"}]
        buckets = group_by_week(records, weeks)
        total = sum(len(b) for b in buckets)
        assert total == 0

    def test_none_date_skipped(self) -> None:
        weeks = get_week_boundaries(date(2026, 2, 8))
        records = [{"date": None}, {"date": "2026-02-03"}]
        buckets = group_by_week(records, weeks)
        total = sum(len(b) for b in buckets)
        assert total == 1

    def test_date_objects_accepted(self) -> None:
        weeks = get_week_boundaries(date(2026, 2, 8))
        records = [{"date": date(2026, 2, 3)}]
        buckets = group_by_week(records, weeks)
        total = sum(len(b) for b in buckets)
        assert total == 1


class TestGroupByPeriod:
    def test_monthly_grouping(self) -> None:
        periods = get_period_boundaries(date(2026, 2, 15), "month", 2)
        records = [
            {"date": "2026-02-10"},
            {"date": "2026-01-15"},
        ]
        buckets = group_by_period(records, periods)
        assert len(buckets[0]) == 1
        assert len(buckets[1]) == 1

    def test_yearly_grouping(self) -> None:
        periods = get_period_boundaries(date(2026, 6, 1), "year", 2)
        records = [
            {"date": "2026-03-01"},
            {"date": "2025-06-15"},
        ]
        buckets = group_by_period(records, periods)
        assert len(buckets[0]) == 1
        assert len(buckets[1]) == 1


# ---------------------------------------------------------------------------
# extract_training_props
# ---------------------------------------------------------------------------


class TestExtractTrainingProps:
    def test_full_page(self) -> None:
        page: dict[str, Any] = {
            "properties": {
                "Name": {"title": [{"plain_text": "Morning Run"}]},
                "Date": {"date": {"start": "2026-02-03"}},
                "Training Type": {"select": {"name": "Running"}},
                "Duration (min)": {"number": 45},
                "Distance (km)": {"number": 8.5},
                "Volume (kg)": {"number": 0},
                "Feeling": {"select": {"name": "Good"}},
            }
        }
        props = extract_training_props(page)
        assert props["name"] == "Morning Run"
        assert props["date"] == "2026-02-03"
        assert props["training_type"] == "Running"
        assert props["duration_min"] == 45.0
        assert props["distance_km"] == 8.5
        assert props["feeling"] == "Good"

    def test_empty_page(self) -> None:
        page: dict[str, Any] = {"properties": {}}
        props = extract_training_props(page)
        assert props["name"] == ""
        assert props["date"] is None
        assert props["training_type"] is None

    def test_missing_properties_key(self) -> None:
        props = extract_training_props({})
        assert props["name"] == ""

    def test_extended_running_properties(self) -> None:
        page: dict[str, Any] = {
            "properties": {
                "Name": {"title": [{"plain_text": "Tempo Run"}]},
                "Date": {"date": {"start": "2026-02-03"}},
                "Training Type": {"select": {"name": "Running"}},
                "Duration (min)": {"number": 50},
                "Distance (km)": {"number": 10.0},
                "Volume (kg)": {"number": None},
                "Feeling": {"select": {"name": "Good"}},
                "Power (W)": {"number": 250},
                "RSS": {"number": 85.5},
                "Critical Power (W)": {"number": 240},
                "Cadence (spm)": {"number": 178},
                "Stride Length (m)": {"number": 1.15},
                "Ground Contact (ms)": {"number": 215},
                "Vertical Oscillation (cm)": {"number": 7.2},
                "Leg Spring Stiffness": {"number": 10.5},
                "RPE": {"number": 6},
                "Temperature (C)": {"number": 12},
                "Wind Speed": {"number": 15},
                "Source": {"select": {"name": "Garmin"}},
                "Avg Heart Rate": {"number": 155},
            }
        }
        props = extract_training_props(page)
        assert props["power_w"] == 250.0
        assert props["rss"] == 85.5
        assert props["critical_power_w"] == 240.0
        assert props["cadence_spm"] == 178.0
        assert props["stride_length_m"] == 1.15
        assert props["ground_contact_ms"] == 215.0
        assert props["vertical_oscillation_cm"] == 7.2
        assert props["leg_spring_stiffness"] == 10.5
        assert props["rpe"] == 6.0
        assert props["temperature_c"] == 12.0
        assert props["wind_speed"] == 15.0
        assert props["source"] == "Garmin"
        assert props["avg_hr"] == 155.0

    def test_extended_properties_default_none(self) -> None:
        page: dict[str, Any] = {"properties": {}}
        props = extract_training_props(page)
        assert props["power_w"] is None
        assert props["rss"] is None
        assert props["rpe"] is None
        assert props["source"] is None
        assert props["avg_hr"] is None

    def test_partial_running_properties(self) -> None:
        """Some running properties present, others missing."""
        page: dict[str, Any] = {
            "properties": {
                "Name": {"title": [{"plain_text": "Easy Run"}]},
                "Power (W)": {"number": 200},
                "RPE": {"number": None},
            }
        }
        props = extract_training_props(page)
        assert props["power_w"] == 200.0
        assert props["rpe"] is None

    def test_source_property_extraction(self) -> None:
        page: dict[str, Any] = {
            "properties": {
                "Name": {"title": [{"plain_text": "Run"}]},
                "Source": {"select": {"name": "Stryd"}},
            }
        }
        props = extract_training_props(page)
        assert props["source"] == "Stryd"

    def test_avg_hr_extraction(self) -> None:
        page: dict[str, Any] = {
            "properties": {
                "Name": {"title": [{"plain_text": "Run"}]},
                "Avg Heart Rate": {"number": 162},
            }
        }
        props = extract_training_props(page)
        assert props["avg_hr"] == 162.0


# ---------------------------------------------------------------------------
# extract_health_props
# ---------------------------------------------------------------------------


class TestExtractHealthProps:
    def test_full_page(self) -> None:
        page: dict[str, Any] = {
            "properties": {
                "Date": {"date": {"start": "2026-02-03"}},
                "Sleep Duration (h)": {"number": 7.5},
                "Sleep Quality": {"select": {"name": "GOOD"}},
                "Resting HR": {"number": 55},
                "Steps": {"number": 9200},
                "Body Battery": {"number": 70},
                "Status": {"select": {"name": "Normal"}},
            }
        }
        props = extract_health_props(page)
        assert props["date"] == "2026-02-03"
        assert props["sleep_hours"] == 7.5
        assert props["sleep_quality"] == "GOOD"
        assert props["resting_hr"] == 55.0
        assert props["status"] == "Normal"

    def test_empty_page(self) -> None:
        page: dict[str, Any] = {"properties": {}}
        props = extract_health_props(page)
        assert props["sleep_hours"] is None
        assert props["sleep_quality"] is None
        assert props["status"] is None


# ---------------------------------------------------------------------------
# calculate_training_week
# ---------------------------------------------------------------------------


class TestCalculateTrainingWeek:
    def test_basic_metrics(self) -> None:
        records = [
            {
                "date": "2026-02-03",
                "training_type": "Running",
                "duration_min": 45,
                "distance_km": 8.0,
                "volume_kg": 0,
                "feeling": "Good",
            },
            {
                "date": "2026-02-04",
                "training_type": "Gym-Strength",
                "duration_min": 60,
                "distance_km": 0,
                "volume_kg": 5000,
                "feeling": "Great",
            },
        ]
        tw = calculate_training_week(records, "Feb 03 \u2013 Feb 09")
        assert tw.sessions == 2
        assert tw.active_days == 2
        assert tw.running_km == 8.0
        assert tw.running_count == 1
        assert tw.gym_sessions == 1
        assert tw.gym_volume == 5000.0
        assert tw.gym_volume_per_session == 5000.0
        assert tw.total_duration_min == 105
        assert tw.feeling_avg == 4.5  # (4+5)/2

    def test_empty_week(self) -> None:
        tw = calculate_training_week([], "Empty Week")
        assert tw.sessions == 0
        assert tw.active_days == 0
        assert tw.running_km == 0.0
        assert tw.gym_volume == 0.0
        assert tw.feeling_avg == 0.0
        assert tw.gym_volume_per_session == 0.0

    def test_tough_sessions(self) -> None:
        records = [
            {"date": "2026-02-03", "training_type": "Running", "duration_min": 30,
             "distance_km": 5, "volume_kg": 0, "feeling": "Tired"},
            {"date": "2026-02-04", "training_type": "Running", "duration_min": 30,
             "distance_km": 5, "volume_kg": 0, "feeling": "Exhausted"},
        ]
        tw = calculate_training_week(records, "test")
        assert tw.tough_sessions == 2

    def test_same_day_multiple_sessions(self) -> None:
        records = [
            {"date": "2026-02-03", "training_type": "Running", "duration_min": 30,
             "distance_km": 5, "volume_kg": 0, "feeling": "Good"},
            {"date": "2026-02-03", "training_type": "Gym-Strength", "duration_min": 60,
             "distance_km": 0, "volume_kg": 3000, "feeling": "Good"},
        ]
        tw = calculate_training_week(records, "test")
        assert tw.sessions == 2
        assert tw.active_days == 1  # same day

    def test_none_values_handled(self) -> None:
        records = [
            {"date": "2026-02-03", "training_type": None, "duration_min": None,
             "distance_km": None, "volume_kg": None, "feeling": None},
        ]
        tw = calculate_training_week(records, "test")
        assert tw.sessions == 1
        assert tw.total_duration_min == 0
        assert tw.feeling_avg == 0.0

    def test_longest_run(self) -> None:
        records = [
            {"date": "2026-02-03", "training_type": "Running", "duration_min": 30,
             "distance_km": 5.0, "volume_kg": 0, "feeling": None},
            {"date": "2026-02-04", "training_type": "Running", "duration_min": 60,
             "distance_km": 12.5, "volume_kg": 0, "feeling": None},
        ]
        tw = calculate_training_week(records, "test")
        assert tw.longest_run_km == 12.5


# ---------------------------------------------------------------------------
# feeling_pct
# ---------------------------------------------------------------------------


class TestFeelingPct:
    def test_all_good_great(self) -> None:
        records = [
            {"date": "2026-02-03", "training_type": "Running", "duration_min": 30,
             "distance_km": 5, "volume_kg": 0, "feeling": "Good"},
            {"date": "2026-02-04", "training_type": "Running", "duration_min": 30,
             "distance_km": 5, "volume_kg": 0, "feeling": "Great"},
        ]
        tw = calculate_training_week(records, "test")
        assert tw.feeling_pct == 100.0

    def test_mixed_feelings(self) -> None:
        records = [
            {"date": "2026-02-03", "training_type": "Running", "duration_min": 30,
             "distance_km": 5, "volume_kg": 0, "feeling": "Good"},
            {"date": "2026-02-04", "training_type": "Running", "duration_min": 30,
             "distance_km": 5, "volume_kg": 0, "feeling": "Okay"},
            {"date": "2026-02-05", "training_type": "Running", "duration_min": 30,
             "distance_km": 5, "volume_kg": 0, "feeling": "Tired"},
            {"date": "2026-02-06", "training_type": "Running", "duration_min": 30,
             "distance_km": 5, "volume_kg": 0, "feeling": "Great"},
        ]
        tw = calculate_training_week(records, "test")
        assert tw.feeling_pct == 50.0  # 2 out of 4

    def test_no_feelings(self) -> None:
        records = [
            {"date": "2026-02-03", "training_type": "Running", "duration_min": 30,
             "distance_km": 5, "volume_kg": 0, "feeling": None},
        ]
        tw = calculate_training_week(records, "test")
        assert tw.feeling_pct == 0.0

    def test_all_tough(self) -> None:
        records = [
            {"date": "2026-02-03", "training_type": "Running", "duration_min": 30,
             "distance_km": 5, "volume_kg": 0, "feeling": "Tired"},
            {"date": "2026-02-04", "training_type": "Running", "duration_min": 30,
             "distance_km": 5, "volume_kg": 0, "feeling": "Exhausted"},
        ]
        tw = calculate_training_week(records, "test")
        assert tw.feeling_pct == 0.0


# ---------------------------------------------------------------------------
# calculate_running_period
# ---------------------------------------------------------------------------


class TestCalculateRunningPeriod:
    def _make_run(
        self, **kwargs: float | int | str | None
    ) -> dict[str, Any]:
        base: dict[str, Any] = {
            "date": "2026-02-03",
            "training_type": "Running",
            "duration_min": 45,
            "distance_km": 8.0,
            "volume_kg": 0,
            "feeling": "Good",
            "power_w": 250,
            "rss": 80,
            "critical_power_w": 240,
            "cadence_spm": 178,
            "stride_length_m": 1.15,
            "ground_contact_ms": 215,
            "vertical_oscillation_cm": 7.2,
            "leg_spring_stiffness": 10.5,
            "rpe": 6,
            "avg_hr": 155,
            "temperature_c": 12,
            "wind_speed": 15,
            "source": "Garmin",
        }
        base.update(kwargs)
        return base

    def test_basic_running_period(self) -> None:
        records = [self._make_run(), self._make_run(distance_km=10.0)]
        rp = calculate_running_period(records, "W1")
        assert rp.run_count == 2
        assert rp.total_km == 18.0
        assert rp.total_duration_min == 90
        assert rp.avg_power_w == 250.0
        assert rp.total_rss == 160.0
        assert rp.avg_rss_per_run == 80.0

    def test_empty_records(self) -> None:
        rp = calculate_running_period([], "empty")
        assert rp.run_count == 0
        assert rp.total_km == 0.0
        assert rp.avg_power_w == 0.0

    def test_no_running_records(self) -> None:
        records = [
            {"date": "2026-02-03", "training_type": "Gym-Strength",
             "duration_min": 60, "distance_km": 0, "volume_kg": 5000,
             "feeling": "Good"},
        ]
        rp = calculate_running_period(records, "W1")
        assert rp.run_count == 0
        assert rp.total_km == 0.0

    def test_power_to_hr_ratio(self) -> None:
        records = [self._make_run(power_w=200, avg_hr=160)]
        rp = calculate_running_period(records, "W1")
        assert rp.power_to_hr_ratio == 1.25

    def test_power_to_hr_zero_hr(self) -> None:
        records = [self._make_run(avg_hr=None)]
        rp = calculate_running_period(records, "W1")
        assert rp.power_to_hr_ratio == 0.0

    def test_avg_pace(self) -> None:
        records = [self._make_run(duration_min=50, distance_km=10.0)]
        rp = calculate_running_period(records, "W1")
        assert rp.avg_pace_min_per_km == 5.0

    def test_avg_pace_zero_distance(self) -> None:
        records = [self._make_run(distance_km=0)]
        rp = calculate_running_period(records, "W1")
        assert rp.avg_pace_min_per_km == 0.0

    def test_none_power_values(self) -> None:
        records = [self._make_run(power_w=None, rss=None, cadence_spm=None)]
        rp = calculate_running_period(records, "W1")
        assert rp.avg_power_w == 0.0
        assert rp.total_rss == 0.0
        assert rp.avg_cadence_spm == 0.0


# ---------------------------------------------------------------------------
# calculate_health_week
# ---------------------------------------------------------------------------


class TestMostCommon:
    def test_single_value(self) -> None:
        assert _most_common(["GOOD"]) == "GOOD"

    def test_mode(self) -> None:
        assert _most_common(["GOOD", "FAIR", "GOOD"]) == "GOOD"

    def test_empty(self) -> None:
        assert _most_common([]) == ""

    def test_tie_returns_one(self) -> None:
        result = _most_common(["GOOD", "FAIR"])
        assert result in ("GOOD", "FAIR")


class TestCalculateHealthWeek:
    def test_basic_averages(self) -> None:
        records = [
            {"sleep_hours": 7.0, "sleep_quality": "GOOD", "resting_hr": 55,
             "steps": 8000, "body_battery": 65, "status": "Normal"},
            {"sleep_hours": 8.0, "sleep_quality": "EXCELLENT", "resting_hr": 52,
             "steps": 10000, "body_battery": 80, "status": "Normal"},
        ]
        hw = calculate_health_week(records, "test")
        assert hw.entries == 2
        assert hw.avg_sleep_hours == 7.5
        assert hw.sleep_quality_mode in ("GOOD", "EXCELLENT")
        assert hw.avg_resting_hr == 53.5
        assert hw.avg_steps == 9000.0
        assert hw.avg_body_battery == 72.5

    def test_sleep_quality_mode(self) -> None:
        records = [
            {"sleep_hours": 7.0, "sleep_quality": "GOOD", "resting_hr": None,
             "steps": None, "body_battery": None, "status": None},
            {"sleep_hours": 7.5, "sleep_quality": "GOOD", "resting_hr": None,
             "steps": None, "body_battery": None, "status": None},
            {"sleep_hours": 8.0, "sleep_quality": "EXCELLENT", "resting_hr": None,
             "steps": None, "body_battery": None, "status": None},
        ]
        hw = calculate_health_week(records, "test")
        assert hw.sleep_quality_mode == "GOOD"

    def test_empty_week(self) -> None:
        hw = calculate_health_week([], "empty")
        assert hw.entries == 0
        assert hw.avg_sleep_hours == 0.0
        assert hw.sleep_quality_mode == ""

    def test_none_values_excluded(self) -> None:
        records = [
            {"sleep_hours": 7.0, "sleep_quality": None, "resting_hr": None,
             "steps": None, "body_battery": None, "status": None},
        ]
        hw = calculate_health_week(records, "test")
        assert hw.avg_sleep_hours == 7.0
        assert hw.sleep_quality_mode == ""

    def test_status_counts(self) -> None:
        records = [
            {"sleep_hours": None, "sleep_quality": None, "resting_hr": None,
             "steps": None, "body_battery": None, "status": "Sick"},
            {"sleep_hours": None, "sleep_quality": None, "resting_hr": None,
             "steps": None, "body_battery": None, "status": "Sick"},
            {"sleep_hours": None, "sleep_quality": None, "resting_hr": None,
             "steps": None, "body_battery": None, "status": "Injured"},
            {"sleep_hours": None, "sleep_quality": None, "resting_hr": None,
             "steps": None, "body_battery": None, "status": "Rest Day"},
        ]
        hw = calculate_health_week(records, "test")
        assert hw.sick_days == 2
        assert hw.injured_days == 1
        assert hw.rest_days == 1


# ---------------------------------------------------------------------------
# Training load & ACWR
# ---------------------------------------------------------------------------


class TestCalculateTrainingLoad:
    def test_optimal_load(self) -> None:
        periods = [
            RunningPeriod(label="W1", total_rss=100),
            RunningPeriod(label="W2", total_rss=90),
            RunningPeriod(label="W3", total_rss=95),
            RunningPeriod(label="W4", total_rss=100),
        ]
        tl = calculate_training_load(periods)
        assert tl.acute_load == 100.0
        assert tl.chronic_load == 95.0  # (90+95+100)/3
        assert 0.8 <= tl.acwr <= 1.3
        assert tl.load_status == "optimal"

    def test_danger_load(self) -> None:
        periods = [
            RunningPeriod(label="W1", total_rss=200),
            RunningPeriod(label="W2", total_rss=80),
            RunningPeriod(label="W3", total_rss=80),
            RunningPeriod(label="W4", total_rss=80),
        ]
        tl = calculate_training_load(periods)
        assert tl.acwr > 1.5
        assert tl.load_status == "danger"

    def test_detraining(self) -> None:
        periods = [
            RunningPeriod(label="W1", total_rss=30),
            RunningPeriod(label="W2", total_rss=100),
            RunningPeriod(label="W3", total_rss=100),
            RunningPeriod(label="W4", total_rss=100),
        ]
        tl = calculate_training_load(periods)
        assert tl.acwr < 0.8
        assert tl.load_status == "detraining"

    def test_caution_load(self) -> None:
        periods = [
            RunningPeriod(label="W1", total_rss=140),
            RunningPeriod(label="W2", total_rss=100),
            RunningPeriod(label="W3", total_rss=100),
            RunningPeriod(label="W4", total_rss=100),
        ]
        tl = calculate_training_load(periods)
        assert 1.3 < tl.acwr <= 1.5
        assert tl.load_status == "caution"

    def test_empty_periods(self) -> None:
        tl = calculate_training_load([])
        assert tl.acwr == 0.0
        assert tl.load_status == ""

    def test_single_period(self) -> None:
        periods = [RunningPeriod(label="W1", total_rss=100)]
        tl = calculate_training_load(periods)
        assert tl.acwr == 1.0
        assert tl.load_status == "optimal"


# ---------------------------------------------------------------------------
# Overreaching detection
# ---------------------------------------------------------------------------


class TestDetectOverreaching:
    def test_no_warnings_optimal(self) -> None:
        load = TrainingLoad(acwr=1.0, load_status="optimal")
        hws = [HealthWeek(avg_body_battery=70), HealthWeek(avg_body_battery=70)]
        assert detect_overreaching(load, hws) == []

    def test_warning_battery_declining(self) -> None:
        load = TrainingLoad(acwr=1.4, load_status="caution")
        hws = [
            HealthWeek(avg_body_battery=50, avg_sleep_hours=7, avg_resting_hr=55),
            HealthWeek(avg_body_battery=70, avg_sleep_hours=7, avg_resting_hr=55),
        ]
        warnings = detect_overreaching(load, hws)
        assert len(warnings) >= 1
        assert "battery" in warnings[0].lower()

    def test_warning_sleep_declining(self) -> None:
        load = TrainingLoad(acwr=1.4, load_status="caution")
        hws = [
            HealthWeek(avg_body_battery=70, avg_sleep_hours=5.5, avg_resting_hr=55),
            HealthWeek(avg_body_battery=70, avg_sleep_hours=7.5, avg_resting_hr=55),
        ]
        warnings = detect_overreaching(load, hws)
        assert any("sleep" in w.lower() for w in warnings)

    def test_warning_hr_elevated(self) -> None:
        load = TrainingLoad(acwr=1.4, load_status="caution")
        hws = [
            HealthWeek(avg_body_battery=70, avg_sleep_hours=7, avg_resting_hr=66),
            HealthWeek(avg_body_battery=70, avg_sleep_hours=7, avg_resting_hr=55),
        ]
        warnings = detect_overreaching(load, hws)
        assert any("hr" in w.lower() for w in warnings)

    def test_no_warnings_insufficient_data(self) -> None:
        load = TrainingLoad(acwr=1.5, load_status="caution")
        hws = [HealthWeek(avg_body_battery=50)]
        assert detect_overreaching(load, hws) == []


# ---------------------------------------------------------------------------
# trend_direction
# ---------------------------------------------------------------------------


class TestTrendDirection:
    def test_up(self) -> None:
        assert trend_direction(110, 100) == "up"

    def test_down(self) -> None:
        assert trend_direction(90, 100) == "down"

    def test_stable(self) -> None:
        assert trend_direction(102, 100) == "stable"

    def test_zero_prev_with_current(self) -> None:
        assert trend_direction(5, 0) == "up"

    def test_zero_both(self) -> None:
        assert trend_direction(0, 0) == "stable"

    def test_exact_threshold_up(self) -> None:
        # 5.1% increase
        assert trend_direction(105.1, 100) == "up"

    def test_exact_threshold_down(self) -> None:
        # 5.1% decrease
        assert trend_direction(94.9, 100) == "down"


# ---------------------------------------------------------------------------
# _color_for_value
# ---------------------------------------------------------------------------


class TestColorForValue:
    def test_higher_is_better_up(self) -> None:
        assert _color_for_value(110, 100, higher_is_better=True) == "green"

    def test_higher_is_better_down(self) -> None:
        assert _color_for_value(90, 100, higher_is_better=True) == "red"

    def test_lower_is_better_up(self) -> None:
        assert _color_for_value(110, 100, higher_is_better=False) == "red"

    def test_lower_is_better_down(self) -> None:
        assert _color_for_value(90, 100, higher_is_better=False) == "green"

    def test_stable(self) -> None:
        assert _color_for_value(100, 100, higher_is_better=True) == "default"


# ---------------------------------------------------------------------------
# _safe_avg
# ---------------------------------------------------------------------------


class TestSafeAvg:
    def test_normal(self) -> None:
        assert _safe_avg([10.0, 20.0]) == 15.0

    def test_empty(self) -> None:
        assert _safe_avg([]) == 0.0

    def test_single(self) -> None:
        assert _safe_avg([5.0]) == 5.0


# ---------------------------------------------------------------------------
# Block builder tests
# ---------------------------------------------------------------------------


class TestBuildText:
    def test_simple(self) -> None:
        rt = build_text("hello")
        assert rt["text"]["content"] == "hello"
        assert "annotations" not in rt

    def test_bold(self) -> None:
        rt = build_text("hello", bold=True)
        assert rt["annotations"]["bold"] is True

    def test_color(self) -> None:
        rt = build_text("hello", color="green")
        assert rt["annotations"]["color"] == "green"


class TestBuildHeading:
    def test_heading_2(self) -> None:
        block = build_heading_2("Title")
        assert block["type"] == "heading_2"
        assert block["heading_2"]["rich_text"][0]["text"]["content"] == "Title"


class TestBuildCallout:
    def test_basic(self) -> None:
        block = build_callout("Some text", icon="check")
        assert block["type"] == "callout"
        assert block["callout"]["rich_text"][0]["text"]["content"] == "Some text"


class TestBuildTable:
    def test_table_row(self) -> None:
        row = build_table_row([[build_text("A")], [build_text("B")]])
        assert row["type"] == "table_row"
        assert len(row["table_row"]["cells"]) == 2

    def test_training_table_structure(self) -> None:
        weeks = [
            TrainingWeek(label="Week 1", sessions=3),
            TrainingWeek(label="Week 2", sessions=2),
        ]
        table = build_training_table(weeks)
        assert table["type"] == "table"
        assert table["table"]["has_column_header"] is True
        # header + 2 data rows
        assert len(table["table"]["children"]) == 3

    def test_training_table_has_11_columns(self) -> None:
        """Training table now has 11 columns (added Runs, replaced Feeling with Feeling %)."""
        weeks = [TrainingWeek(label="W1")]
        table = build_training_table(weeks)
        assert table["table"]["table_width"] == 11

    def test_health_table_structure(self) -> None:
        weeks = [
            HealthWeek(label="Week 1", entries=5),
            HealthWeek(label="Week 2", entries=7),
        ]
        table = build_health_table(weeks)
        assert table["type"] == "table"
        assert len(table["table"]["children"]) == 3

    def test_training_table_coloring(self) -> None:
        """Current week row should have colored values when prior weeks exist."""
        weeks = [
            TrainingWeek(label="Current", sessions=5, gym_volume=10000),
            TrainingWeek(label="Prior 1", sessions=2, gym_volume=5000),
            TrainingWeek(label="Prior 2", sessions=2, gym_volume=5000),
        ]
        table = build_training_table(weeks)
        # Row 1 (index 1 in children, after header) is the current week
        current_row = table["table"]["children"][1]
        # Sessions cell (index 1) should be green (5 vs avg 2)
        sessions_cell = current_row["table_row"]["cells"][1]
        assert sessions_cell[0].get("annotations", {}).get("color") == "green"


# ---------------------------------------------------------------------------
# Column layout builders
# ---------------------------------------------------------------------------


class TestColumnBuilders:
    def test_column_list_structure(self) -> None:
        col = build_column([build_callout("text")])
        cl = build_column_list([col])
        assert cl["type"] == "column_list"
        assert len(cl["column_list"]["children"]) == 1

    def test_column_structure(self) -> None:
        col = build_column([build_callout("text")])
        assert col["type"] == "column"
        assert len(col["column"]["children"]) == 1

    def test_two_column_layout(self) -> None:
        cl = build_column_list([
            build_column([build_callout("A")]),
            build_column([build_callout("B")]),
        ])
        assert len(cl["column_list"]["children"]) == 2

    def test_three_column_layout(self) -> None:
        cl = build_column_list([
            build_column([build_callout("A")]),
            build_column([build_callout("B")]),
            build_column([build_callout("C")]),
        ])
        assert len(cl["column_list"]["children"]) == 3

    def test_column_with_multiple_children(self) -> None:
        col = build_column([build_callout("A"), build_callout("B")])
        assert len(col["column"]["children"]) == 2


# ---------------------------------------------------------------------------
# Running table
# ---------------------------------------------------------------------------


class TestBuildRunningTable:
    def test_structure(self) -> None:
        periods = [
            RunningPeriod(label="W1", run_count=3),
            RunningPeriod(label="W2", run_count=2),
        ]
        table = build_running_table(periods)
        assert table["type"] == "table"
        assert table["table"]["table_width"] == 14
        assert len(table["table"]["children"]) == 3  # header + 2 rows

    def test_coloring(self) -> None:
        periods = [
            RunningPeriod(label="W1", avg_power_w=260),
            RunningPeriod(label="W2", avg_power_w=200),
            RunningPeriod(label="W3", avg_power_w=200),
        ]
        table = build_running_table(periods)
        # Power is col 3 (0-indexed), current row is index 1
        current_row = table["table"]["children"][1]
        power_cell = current_row["table_row"]["cells"][3]
        assert power_cell[0].get("annotations", {}).get("color") == "green"

    def test_empty_periods(self) -> None:
        table = build_running_table([])
        assert table["table"]["table_width"] == 14
        assert len(table["table"]["children"]) == 1  # header only

    def test_single_period(self) -> None:
        periods = [RunningPeriod(label="W1", run_count=2, avg_power_w=250)]
        table = build_running_table(periods)
        assert len(table["table"]["children"]) == 2


# ---------------------------------------------------------------------------
# Load correlation section
# ---------------------------------------------------------------------------


class TestBuildLoadCorrelationSection:
    def test_optimal_section(self) -> None:
        load = TrainingLoad(
            acwr=1.1, load_status="optimal",
            acute_load=100, chronic_load=90,
        )
        blocks = build_load_correlation_section(load, [], "Good adaptation")
        assert len(blocks) >= 2  # ACWR callout + insight
        assert blocks[0]["type"] == "callout"
        assert "green_background" in blocks[0]["callout"]["color"]

    def test_danger_section(self) -> None:
        load = TrainingLoad(
            acwr=1.6, load_status="danger",
            acute_load=200, chronic_load=120,
        )
        blocks = build_load_correlation_section(
            load, ["Battery declining"], "Watch for overtraining"
        )
        assert blocks[0]["callout"]["color"] == "red_background"
        # Warning callout present
        assert any("Battery" in b["callout"]["rich_text"][0]["text"]["content"]
                    for b in blocks if b["type"] == "callout")

    def test_with_warnings(self) -> None:
        load = TrainingLoad(acwr=1.4, load_status="caution",
                            acute_load=140, chronic_load=100)
        blocks = build_load_correlation_section(
            load, ["warn1", "warn2"], ""
        )
        warning_blocks = [b for b in blocks
                          if b["type"] == "callout" and "red" in b["callout"]["color"]]
        assert len(warning_blocks) == 2


class TestBuildToggle:
    def test_toggle(self) -> None:
        block = build_toggle("Title", [build_paragraph([build_text("Child")])])
        assert block["type"] == "toggle"
        assert len(block["toggle"]["children"]) == 1


class TestBuildDivider:
    def test_divider(self) -> None:
        block = build_divider()
        assert block["type"] == "divider"


# ---------------------------------------------------------------------------
# Insight generation (existing)
# ---------------------------------------------------------------------------


class TestGenerateTrainingInsights:
    def test_with_prior_weeks(self) -> None:
        weeks = [
            TrainingWeek(label="W1", sessions=5, total_duration_min=300,
                         gym_volume=10000, running_km=20),
            TrainingWeek(label="W2", sessions=3, total_duration_min=200,
                         gym_volume=8000, running_km=15),
            TrainingWeek(label="W3", sessions=3, total_duration_min=200,
                         gym_volume=8000, running_km=15),
        ]
        insights = generate_training_insights(weeks)
        assert len(insights) == 4
        assert "Sessions" in insights[0]
        assert "Duration" in insights[1]

    def test_single_week(self) -> None:
        weeks = [TrainingWeek(label="W1", sessions=3)]
        insights = generate_training_insights(weeks)
        assert len(insights) == 4
        assert "3" in insights[0]

    def test_empty(self) -> None:
        assert generate_training_insights([]) == []


class TestGenerateHealthInsights:
    def test_with_prior_weeks(self) -> None:
        weeks = [
            HealthWeek(label="W1", avg_sleep_hours=7.5, avg_resting_hr=55,
                       avg_steps=9000, avg_body_battery=70),
            HealthWeek(label="W2", avg_sleep_hours=7.0, avg_resting_hr=58,
                       avg_steps=8000, avg_body_battery=65),
        ]
        insights = generate_health_insights(weeks)
        assert len(insights) == 4
        assert "Sleep" in insights[0]

    def test_empty(self) -> None:
        assert generate_health_insights([]) == []


class TestGenerateTrainingTakeaway:
    def test_with_data(self) -> None:
        weeks = [
            TrainingWeek(label="W1", sessions=4, active_days=3,
                         gym_volume=8000, running_km=15, feeling_avg=4.2),
        ]
        takeaway = generate_training_takeaway(weeks)
        assert "4 sessions" in takeaway
        assert "8000kg" in takeaway.replace(",", "")

    def test_no_sessions(self) -> None:
        weeks = [TrainingWeek(label="W1")]
        takeaway = generate_training_takeaway(weeks)
        assert "No training data" in takeaway

    def test_empty(self) -> None:
        assert "No training data" in generate_training_takeaway([])


class TestGenerateHealthTakeaway:
    def test_with_data(self) -> None:
        weeks = [
            HealthWeek(label="W1", avg_sleep_hours=7.5, avg_resting_hr=55,
                       avg_steps=9000, entries=7),
        ]
        takeaway = generate_health_takeaway(weeks)
        assert "7.5h" in takeaway

    def test_no_data(self) -> None:
        weeks = [HealthWeek(label="W1")]
        assert "No health data" in generate_health_takeaway(weeks)


# ---------------------------------------------------------------------------
# New themed insight generators
# ---------------------------------------------------------------------------


class TestRunningPowerInsight:
    def test_with_data(self) -> None:
        periods = [
            RunningPeriod(label="W1", run_count=3, avg_power_w=250,
                          total_rss=120, avg_rss_per_run=40, power_to_hr_ratio=1.5),
            RunningPeriod(label="W2", run_count=2, avg_power_w=240,
                          total_rss=100, avg_rss_per_run=50),
        ]
        result = generate_running_power_insight(periods)
        assert "250" in result
        assert "RSS" in result
        assert "Power:HR" in result

    def test_no_data(self) -> None:
        result = generate_running_power_insight([])
        assert "No running data" in result

    def test_no_runs(self) -> None:
        periods = [RunningPeriod(label="W1", run_count=0)]
        result = generate_running_power_insight(periods)
        assert "No running data" in result


class TestRunningBiomechanicsInsight:
    def test_with_data(self) -> None:
        periods = [
            RunningPeriod(label="W1", run_count=3, avg_cadence_spm=178,
                          avg_stride_length_m=1.15, avg_ground_contact_ms=215,
                          avg_vertical_oscillation_cm=7.2, avg_leg_spring_stiffness=10.5),
        ]
        result = generate_running_biomechanics_insight(periods)
        assert "Cadence" in result
        assert "178" in result

    def test_no_data(self) -> None:
        result = generate_running_biomechanics_insight([])
        assert "No running" in result


class TestRunningTakeaway:
    def test_with_data(self) -> None:
        periods = [
            RunningPeriod(label="W1", run_count=3, total_km=25,
                          avg_power_w=250, avg_pace_min_per_km=5.5, avg_rpe=6),
        ]
        result = generate_running_takeaway(periods)
        assert "3 runs" in result
        assert "25km" in result

    def test_no_runs(self) -> None:
        periods = [RunningPeriod(label="W1", run_count=0)]
        result = generate_running_takeaway(periods)
        assert "No runs" in result


class TestSleepInsight:
    def test_with_data(self) -> None:
        weeks = [
            HealthWeek(label="W1", entries=7, avg_sleep_hours=7.5,
                       sleep_quality_mode="GOOD"),
            HealthWeek(label="W2", entries=7, avg_sleep_hours=7.0),
        ]
        result = generate_sleep_insight(weeks)
        assert "7.5" in result
        assert "GOOD" in result

    def test_no_data(self) -> None:
        result = generate_sleep_insight([])
        assert "No sleep data" in result


class TestHrInsight:
    def test_with_data(self) -> None:
        weeks = [
            HealthWeek(label="W1", entries=7, avg_resting_hr=55),
            HealthWeek(label="W2", entries=7, avg_resting_hr=58),
        ]
        result = generate_hr_insight(weeks)
        assert "55" in result

    def test_no_data(self) -> None:
        result = generate_hr_insight([])
        assert "No HR data" in result


class TestRecoveryHealthInsight:
    def test_with_data(self) -> None:
        weeks = [
            HealthWeek(label="W1", entries=7, avg_body_battery=70, avg_steps=9000),
            HealthWeek(label="W2", entries=7, avg_body_battery=65, avg_steps=8000),
        ]
        result = generate_recovery_health_insight(weeks)
        assert "70" in result
        assert "Steps" in result

    def test_no_data(self) -> None:
        result = generate_recovery_health_insight([])
        assert "No recovery data" in result


class TestRunningTrendInsight:
    def test_with_data(self) -> None:
        weeks = [
            TrainingWeek(label="W1", running_km=25, longest_run_km=12),
            TrainingWeek(label="W2", running_km=20),
        ]
        periods = [
            RunningPeriod(label="W1", run_count=3, total_km=25, avg_power_w=250),
        ]
        result = generate_running_trend_insight(weeks, periods)
        assert "3 runs" in result
        assert "25km" in result

    def test_no_data(self) -> None:
        result = generate_running_trend_insight([], [])
        assert "No running data" in result


class TestStrengthInsight:
    def test_with_data(self) -> None:
        weeks = [
            TrainingWeek(label="W1", gym_sessions=3, gym_volume=15000,
                         gym_volume_per_session=5000),
            TrainingWeek(label="W2", gym_sessions=2, gym_volume=10000),
        ]
        result = generate_strength_insight(weeks)
        assert "3 sessions" in result
        assert "15000" in result

    def test_no_gym(self) -> None:
        weeks = [TrainingWeek(label="W1", gym_sessions=0)]
        result = generate_strength_insight(weeks)
        assert "No gym" in result


class TestRecoveryInsight:
    def test_with_data(self) -> None:
        weeks = [TrainingWeek(label="W1", feeling_pct=75, tough_sessions=1)]
        health = [HealthWeek(label="W1", entries=7, avg_body_battery=70,
                             avg_resting_hr=55)]
        result = generate_recovery_insight(weeks, health)
        assert "75" in result
        assert "battery" in result.lower()

    def test_no_data(self) -> None:
        result = generate_recovery_insight([], [])
        assert "No data" in result


class TestCorrelationInsights:
    def test_optimal_load(self) -> None:
        load = TrainingLoad(acwr=1.1, load_status="optimal")
        result = generate_correlation_insights([], [], [], load)
        assert "optimal" in result.lower()

    def test_volume_up_battery_down(self) -> None:
        weeks = [
            TrainingWeek(label="W1", total_duration_min=400),
            TrainingWeek(label="W2", total_duration_min=200),
        ]
        health = [
            HealthWeek(label="W1", avg_body_battery=50),
            HealthWeek(label="W2", avg_body_battery=70),
        ]
        load = TrainingLoad(acwr=1.1, load_status="optimal")
        result = generate_correlation_insights(weeks, health, [], load)
        assert "overtraining" in result.lower()

    def test_insufficient_data(self) -> None:
        result = generate_correlation_insights([], [], [], TrainingLoad())
        assert "Insufficient" in result


# ---------------------------------------------------------------------------
# build_full_dashboard (v2 with DashboardData)
# ---------------------------------------------------------------------------


class TestBuildFullDashboard:
    def _make_data(self, **kwargs: object) -> DashboardData:
        defaults: dict[str, Any] = {
            "training_weeks": [TrainingWeek(label="W1", sessions=1)],
            "health_weeks": [HealthWeek(label="W1", entries=1)],
            "running_periods": [RunningPeriod(label="W1")],
            "training_load": TrainingLoad(
                acwr=1.0, load_status="optimal",
                acute_load=100, chronic_load=100,
            ),
            "overreaching_warnings": [],
            "training_db_id": "train-db-id",
            "health_db_id": "health-db-id",
            "running_power_insight": "power insight",
            "running_biomechanics_insight": "bio insight",
            "running_takeaway": "running takeaway",
            "training_running_trend": "running trend",
            "training_strength_insight": "strength insight",
            "training_recovery_insight": "recovery insight",
            "training_takeaway": "training takeaway",
            "health_sleep_insight": "sleep insight",
            "health_hr_insight": "hr insight",
            "health_recovery_insight": "health recovery",
            "health_takeaway": "health takeaway",
            "correlation_insight": "correlation",
        }
        defaults.update(kwargs)
        return DashboardData(**defaults)

    def test_returns_blocks(self) -> None:
        data = self._make_data()
        blocks = build_full_dashboard(data)
        assert isinstance(blocks, list)
        assert len(blocks) > 10

        # First block is a callout (header)
        assert blocks[0]["type"] == "callout"
        # Should have heading_2 blocks
        headings = [b for b in blocks if b.get("type") == "heading_2"]
        assert len(headings) >= 4  # Training, Running, Health, Load

    def test_contains_database_mentions(self) -> None:
        data = self._make_data()
        blocks = build_full_dashboard(data)
        # Find mentions in column layouts
        mention_count = _count_mentions_deep(blocks)
        assert mention_count >= 2

    def test_contains_column_layouts(self) -> None:
        data = self._make_data()
        blocks = build_full_dashboard(data)
        column_lists = [b for b in blocks if b.get("type") == "column_list"]
        assert len(column_lists) >= 3  # training, running, health callouts + db links

    def test_contains_running_table(self) -> None:
        data = self._make_data()
        blocks = build_full_dashboard(data)
        tables = [b for b in blocks if b.get("type") == "table"]
        assert len(tables) >= 3  # training + running + health

    def test_contains_metric_definitions(self) -> None:
        data = self._make_data()
        blocks = build_full_dashboard(data)
        toggles = [b for b in blocks if b.get("type") == "toggle"]
        toggle_titles = [
            b["toggle"]["rich_text"][0]["text"]["content"] for b in toggles
        ]
        assert "Metric Definitions" in toggle_titles

    def test_metric_definitions_include_running_metrics(self) -> None:
        data = self._make_data()
        blocks = build_full_dashboard(data)
        metric_toggle = None
        for b in blocks:
            if b.get("type") == "toggle":
                title = b["toggle"]["rich_text"][0]["text"]["content"]
                if title == "Metric Definitions":
                    metric_toggle = b
                    break
        assert metric_toggle is not None
        texts = " ".join(
            rt["text"]["content"]
            for child in metric_toggle["toggle"]["children"]
            for rt in child.get("paragraph", {}).get("rich_text", [])
        )
        assert "ACWR" in texts
        assert "Power (W)" in texts
        assert "RSS" in texts

    def test_subpage_links_when_present(self) -> None:
        data = self._make_data(subpage_ids={"Monthly Report": "page-123"})
        blocks = build_full_dashboard(data)
        headings = [b for b in blocks if b.get("type") == "heading_2"]
        heading_texts = [
            b["heading_2"]["rich_text"][0]["text"]["content"] for b in headings
        ]
        assert "Reports" in heading_texts


# ---------------------------------------------------------------------------
# Subpage builders
# ---------------------------------------------------------------------------


class TestBuildSubpageDashboard:
    def test_returns_blocks(self) -> None:
        records = [
            {"date": "2026-02-03", "training_type": "Running",
             "duration_min": 45, "distance_km": 8.0, "volume_kg": 0,
             "feeling": "Good", "power_w": 250, "rss": 80,
             "critical_power_w": 240, "cadence_spm": 178,
             "stride_length_m": 1.15, "ground_contact_ms": 215,
             "vertical_oscillation_cm": 7.2, "leg_spring_stiffness": 10.5,
             "rpe": 6, "avg_hr": 155, "temperature_c": 12,
             "wind_speed": 15, "source": "Garmin"},
        ]
        health = [
            {"date": "2026-02-03", "sleep_hours": 7.5, "sleep_quality": "GOOD",
             "resting_hr": 55, "steps": 9000, "body_battery": 70,
             "status": None},
        ]
        blocks = build_subpage_dashboard(
            records, health, date(2026, 2, 9), "month", 2, "Monthly Report"
        )
        assert isinstance(blocks, list)
        assert len(blocks) > 5
        # Should have headings for sections
        headings = [b for b in blocks if b.get("type") == "heading_2"]
        assert len(headings) == 3  # Training, Running, Health

    def test_empty_data(self) -> None:
        blocks = build_subpage_dashboard(
            [], [], date(2026, 2, 9), "month", 2, "Monthly Report"
        )
        assert isinstance(blocks, list)
        assert len(blocks) > 0

    def test_quarterly_periods(self) -> None:
        blocks = build_subpage_dashboard(
            [], [], date(2026, 2, 9), "quarter", 4, "Quarterly Report"
        )
        tables = [b for b in blocks if b.get("type") == "table"]
        # Each table should have header + 4 data rows = 5 rows
        for table in tables:
            assert len(table["table"]["children"]) == 5

    def test_yearly_periods(self) -> None:
        blocks = build_subpage_dashboard(
            [], [], date(2026, 2, 9), "year", 2, "Yearly Report"
        )
        tables = [b for b in blocks if b.get("type") == "table"]
        for table in tables:
            assert len(table["table"]["children"]) == 3  # header + 2

    def test_header_callout(self) -> None:
        blocks = build_subpage_dashboard(
            [], [], date(2026, 2, 9), "month", 2, "Monthly Report"
        )
        assert blocks[0]["type"] == "callout"
        assert "Monthly Report" in blocks[0]["callout"]["rich_text"][0]["text"]["content"]


# ---------------------------------------------------------------------------
# find_or_create_subpage
# ---------------------------------------------------------------------------


class TestFindOrCreateSubpage:
    def test_finds_existing(self) -> None:
        from scripts.update_dashboard import find_or_create_subpage

        mock_client = mock.MagicMock()
        mock_client.get_block_children.return_value = [
            {
                "type": "child_page",
                "child_page": {"title": "Monthly Report"},
                "id": "abc-123-def",
            }
        ]
        result = find_or_create_subpage(mock_client, "parent-id", "Monthly Report")
        assert result == "abc123def"
        mock_client.create_page_under_page.assert_not_called()

    def test_creates_when_not_found(self) -> None:
        from scripts.update_dashboard import find_or_create_subpage

        mock_client = mock.MagicMock()
        mock_client.get_block_children.return_value = []
        mock_client.create_page_under_page.return_value = {
            "id": "new-page-id-123"
        }
        result = find_or_create_subpage(mock_client, "parent-id", "Monthly Report")
        assert result == "newpageid123"
        mock_client.create_page_under_page.assert_called_once_with(
            "parent-id", "Monthly Report"
        )

    def test_skips_non_child_page_blocks(self) -> None:
        from scripts.update_dashboard import find_or_create_subpage

        mock_client = mock.MagicMock()
        mock_client.get_block_children.return_value = [
            {"type": "paragraph", "id": "p1"},
            {
                "type": "child_page",
                "child_page": {"title": "Wrong Title"},
                "id": "wrong-id",
            },
        ]
        mock_client.create_page_under_page.return_value = {"id": "new-id"}
        result = find_or_create_subpage(mock_client, "parent-id", "Monthly Report")
        assert result == "newid"

    def test_matches_exact_title(self) -> None:
        from scripts.update_dashboard import find_or_create_subpage

        mock_client = mock.MagicMock()
        mock_client.get_block_children.return_value = [
            {
                "type": "child_page",
                "child_page": {"title": "Monthly Report Extra"},
                "id": "wrong-id",
            },
            {
                "type": "child_page",
                "child_page": {"title": "Monthly Report"},
                "id": "correct-id",
            },
        ]
        result = find_or_create_subpage(mock_client, "parent-id", "Monthly Report")
        assert result == "correctid"


# ---------------------------------------------------------------------------
# _format_num
# ---------------------------------------------------------------------------


class TestFormatNum:
    def test_whole_number(self) -> None:
        assert _format_num(5.0) == "5"

    def test_decimal(self) -> None:
        assert _format_num(5.5) == "5.5"

    def test_zero(self) -> None:
        assert _format_num(0.0) == "0"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _count_mentions_deep(blocks: list[dict[str, Any]]) -> int:
    """Recursively count all mention elements in blocks."""
    count = 0
    for block in blocks:
        block_type = block.get("type", "")
        content = block.get(block_type, {})
        if isinstance(content, dict):
            for rt in content.get("rich_text", []):
                if rt.get("type") == "mention":
                    count += 1
            for child in content.get("children", []):
                count += _count_mentions_deep([child])
    return count
