"""Tests for scripts/update_dashboard.py — all pure functions."""

import os
from datetime import date
from typing import Any
from unittest import mock

import pytest

from scripts.update_dashboard import (
    HealthWeek,
    TrainingWeek,
    _color_for_value,
    _format_num,
    _most_common,
    _safe_avg,
    build_callout,
    build_divider,
    build_full_dashboard,
    build_heading_2,
    build_health_table,
    build_paragraph,
    build_table_row,
    build_text,
    build_toggle,
    build_training_table,
    calculate_health_week,
    calculate_training_week,
    extract_health_props,
    extract_training_props,
    generate_health_insights,
    generate_health_takeaway,
    generate_training_insights,
    generate_training_takeaway,
    get_env_config,
    get_week_boundaries,
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
            assert "–" in label

    def test_current_week_includes_today(self) -> None:
        today = date(2026, 2, 5)  # Thursday
        weeks = get_week_boundaries(today)
        monday, sunday, _ = weeks[0]
        assert monday <= today <= sunday


# ---------------------------------------------------------------------------
# group_by_week
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
        tw = calculate_training_week(records, "Feb 03 – Feb 09")
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
# Insight generation
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
# build_full_dashboard
# ---------------------------------------------------------------------------


class TestBuildFullDashboard:
    def test_returns_blocks(self) -> None:
        tw = [TrainingWeek(label="W1", sessions=1)]
        hw = [HealthWeek(label="W1", entries=1)]
        blocks = build_full_dashboard(
            tw, hw,
            ["insight1"], ["insight2"],
            "takeaway1", "takeaway2",
            "train-db-id", "health-db-id",
        )
        assert isinstance(blocks, list)
        assert len(blocks) > 10  # header + sections + toggles + dividers

        # Check structure: first block is a callout (header)
        assert blocks[0]["type"] == "callout"
        # Should have heading_2 blocks
        headings = [b for b in blocks if b.get("type") == "heading_2"]
        assert len(headings) >= 2

    def test_contains_database_mentions(self) -> None:
        tw = [TrainingWeek(label="W1")]
        hw = [HealthWeek(label="W1")]
        blocks = build_full_dashboard(
            tw, hw, [], [], "", "", "train-id", "health-id",
        )
        # Find paragraph blocks that have mentions
        mention_blocks = []
        for b in blocks:
            if b.get("type") == "paragraph":
                for rt in b.get("paragraph", {}).get("rich_text", []):
                    if rt.get("type") == "mention":
                        mention_blocks.append(rt)
        assert len(mention_blocks) == 2


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
