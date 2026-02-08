"""Tests for scripts.stryd_sync helper functions."""

from datetime import UTC, datetime

from scripts.stryd_sync import (
    FEEL_MAPPING,
    _safe_float,
    _safe_int,
    _safe_round,
    build_stryd_create_properties,
    build_stryd_update_properties,
    extract_date,
    extract_feel,
    extract_power_metrics,
    extract_rpe,
    extract_timestamp,
)

# ---------------------------------------------------------------------------
# Sample Stryd activity data (based on real API response)
# ---------------------------------------------------------------------------

SAMPLE_ACTIVITY: dict = {
    "timestamp": 1738900800,  # 2025-02-07T00:00:00Z
    "name": "Day 38 - Long Run",
    "rpe": 5,
    "feel": "normal",
    "type": "long",
    "source": "garmin",
    "surface_type": "trail",
    "ftp": 245.5,
    "stress": 78.3,
    "average_power": 230.0,
    "max_power": 400,
    "average_heart_rate": 145,
    "max_heart_rate": 170,
    "distance": 11584.4,
    "moving_time": 4642,
    "elapsed_time": 4650,
    "total_elevation_gain": 120.5,
    "total_elevation_loss": -115.2,
    "max_elevation": 350.0,
    "min_elevation": 230.0,
    "average_cadence": 178,
    "max_cadence": 192,
    "min_cadence": 160,
    "average_stride_length": 1.15,
    "max_stride_length": 1.35,
    "min_stride_length": 0.95,
    "average_ground_time": 235.5,
    "max_ground_time": 280,
    "min_ground_time": 200,
    "average_oscillation": 8.2,
    "max_oscillation": 10.5,
    "min_oscillation": 6.8,
    "average_leg_spring": 10.3,
    "max_vertical_stiffness": 12.1,
    "stryds": 10261.9,
    "elevation": 120.0,
    "temperature": 12.5,
    "humidity": 65,
    "windBearing": 180,
    "windSpeed": 15.3,
    "windGust": 22.1,
    "dewPoint": 5.2,
}


# ---------------------------------------------------------------------------
# extract_timestamp / extract_date
# ---------------------------------------------------------------------------


class TestExtractTimestamp:
    def test_normal(self) -> None:
        dt = extract_timestamp(SAMPLE_ACTIVITY)
        assert dt.year == 2025
        assert dt.month == 2
        assert dt.day == 7
        assert dt.tzinfo == UTC

    def test_missing_timestamp(self) -> None:
        dt = extract_timestamp({})
        assert dt == datetime(1970, 1, 1, tzinfo=UTC)


class TestExtractDate:
    def test_normal(self) -> None:
        d = extract_date(SAMPLE_ACTIVITY)
        assert d.isoformat() == "2025-02-07"

    def test_missing(self) -> None:
        d = extract_date({})
        assert d.isoformat() == "1970-01-01"


# ---------------------------------------------------------------------------
# extract_power_metrics
# ---------------------------------------------------------------------------


class TestExtractPowerMetrics:
    def test_all_fields(self) -> None:
        metrics = extract_power_metrics(SAMPLE_ACTIVITY)
        assert metrics["power"] == 230.0
        assert metrics["ftp"] == 245.5
        assert metrics["rss"] == 78.3
        assert metrics["cadence"] == 178
        assert metrics["stride_length"] == 1.15
        assert metrics["ground_contact"] == 235.5
        assert metrics["vertical_oscillation"] == 8.2
        assert metrics["leg_spring_stiffness"] == 10.3
        assert metrics["temperature"] == 12.5
        assert metrics["wind_speed"] == 15.3
        assert metrics["elevation_gain"] == 120.5

    def test_empty_activity(self) -> None:
        metrics = extract_power_metrics({})
        assert all(v is None for v in metrics.values())

    def test_zero_values_become_none(self) -> None:
        activity = {"average_power": 0, "ftp": 0, "stress": 0}
        metrics = extract_power_metrics(activity)
        assert metrics["power"] is None
        assert metrics["ftp"] is None
        assert metrics["rss"] is None

    def test_uses_average_power_not_stryds(self) -> None:
        """stryds is cumulative; average_power is the correct field."""
        activity = {"average_power": 231.5, "stryds": 10261.9}
        metrics = extract_power_metrics(activity)
        assert metrics["power"] == 231.5


# ---------------------------------------------------------------------------
# extract_rpe / extract_feel
# ---------------------------------------------------------------------------


class TestExtractRpe:
    def test_rpe_field(self) -> None:
        assert extract_rpe({"rpe": 7}) == 7

    def test_zero_means_not_entered(self) -> None:
        assert extract_rpe({"rpe": 0}) is None

    def test_no_rpe_key(self) -> None:
        assert extract_rpe({}) is None

    def test_from_sample(self) -> None:
        assert extract_rpe(SAMPLE_ACTIVITY) == 5

    def test_float_rpe_converted_to_int(self) -> None:
        assert extract_rpe({"rpe": 7.5}) == 7


class TestExtractFeel:
    def test_great(self) -> None:
        assert extract_feel({"feel": "great"}) == "Great"

    def test_good(self) -> None:
        assert extract_feel({"feel": "good"}) == "Good"

    def test_normal_maps_to_good(self) -> None:
        assert extract_feel({"feel": "normal"}) == "Good"

    def test_bad_maps_to_tired(self) -> None:
        assert extract_feel({"feel": "bad"}) == "Tired"

    def test_terrible_maps_to_exhausted(self) -> None:
        assert extract_feel({"feel": "terrible"}) == "Exhausted"

    def test_empty_string(self) -> None:
        assert extract_feel({"feel": ""}) is None

    def test_missing_key(self) -> None:
        assert extract_feel({}) is None

    def test_unknown_value(self) -> None:
        assert extract_feel({"feel": "meh"}) is None

    def test_from_sample(self) -> None:
        assert extract_feel(SAMPLE_ACTIVITY) == "Good"

    def test_all_mapping_keys(self) -> None:
        for stryd_val, notion_val in FEEL_MAPPING.items():
            assert extract_feel({"feel": stryd_val}) == notion_val

    def test_rpe_does_not_affect_feel(self) -> None:
        """RPE and Feeling are independent — RPE never maps to Feeling."""
        assert extract_feel({"rpe": 10}) is None
        assert extract_feel({"rpe": 1}) is None


# ---------------------------------------------------------------------------
# _safe_float / _safe_int / _safe_round
# ---------------------------------------------------------------------------


class TestSafeFloat:
    def test_number(self) -> None:
        assert _safe_float(42.5) == 42.5

    def test_zero(self) -> None:
        assert _safe_float(0) is None

    def test_negative(self) -> None:
        assert _safe_float(-5) is None

    def test_none(self) -> None:
        assert _safe_float(None) is None

    def test_string_number(self) -> None:
        assert _safe_float("3.14") == 3.14

    def test_invalid_string(self) -> None:
        assert _safe_float("abc") is None


class TestSafeInt:
    def test_number(self) -> None:
        assert _safe_int(42) == 42

    def test_zero(self) -> None:
        assert _safe_int(0) is None

    def test_none(self) -> None:
        assert _safe_int(None) is None

    def test_float_truncated(self) -> None:
        assert _safe_int(7.9) == 7


class TestSafeRound:
    def test_round_2(self) -> None:
        assert _safe_round(1.1567, 2) == 1.16

    def test_none(self) -> None:
        assert _safe_round(None, 2) is None

    def test_zero(self) -> None:
        assert _safe_round(0, 2) is None


# ---------------------------------------------------------------------------
# build_stryd_update_properties
# ---------------------------------------------------------------------------


class TestBuildStrydUpdateProperties:
    def test_all_metrics(self) -> None:
        metrics = extract_power_metrics(SAMPLE_ACTIVITY)
        props = build_stryd_update_properties(metrics)
        assert props["Power (W)"]["number"] == 230.0
        assert props["RSS"]["number"] == 78.3
        assert props["Critical Power (W)"]["number"] == 245.5
        assert props["Cadence (spm)"]["number"] == 178
        assert props["Stride Length (m)"]["number"] == 1.15
        assert props["Ground Contact (ms)"]["number"] == 235.5
        assert props["Vertical Oscillation (cm)"]["number"] == 8.2
        assert props["Leg Spring Stiffness"]["number"] == 10.3
        assert props["Temperature (C)"]["number"] == 12.5
        assert props["Wind Speed"]["number"] == 15.3

    def test_empty_metrics(self) -> None:
        metrics = extract_power_metrics({})
        props = build_stryd_update_properties(metrics)
        assert props == {}

    def test_with_rpe(self) -> None:
        metrics = {"power": 230.0}
        props = build_stryd_update_properties(metrics, rpe=7)
        assert props["Power (W)"]["number"] == 230.0
        assert props["RPE"]["number"] == 7

    def test_with_feel(self) -> None:
        metrics = {"power": 230.0}
        props = build_stryd_update_properties(metrics, feel="Good")
        assert props["Feeling"]["select"]["name"] == "Good"

    def test_none_rpe_excluded(self) -> None:
        metrics = {"power": 230.0}
        props = build_stryd_update_properties(metrics, rpe=None)
        assert "RPE" not in props

    def test_none_feel_excluded(self) -> None:
        metrics = {"power": 230.0}
        props = build_stryd_update_properties(metrics, feel=None)
        assert "Feeling" not in props

    def test_partial_metrics(self) -> None:
        metrics = {"power": 200.0, "rss": None, "ftp": 240.0}
        props = build_stryd_update_properties(metrics)
        assert "Power (W)" in props
        assert "Critical Power (W)" in props
        assert "RSS" not in props


# ---------------------------------------------------------------------------
# build_stryd_create_properties
# ---------------------------------------------------------------------------


class TestBuildStrydCreateProperties:
    def test_creates_full_entry(self) -> None:
        metrics = extract_power_metrics(SAMPLE_ACTIVITY)
        props = build_stryd_create_properties(SAMPLE_ACTIVITY, metrics)
        assert props["Name"]["title"][0]["text"]["content"] == "Day 38 - Long Run"
        assert props["Date"]["date"]["start"] == "2025-02-07"
        assert props["Training Type"]["select"]["name"] == "Running"
        assert props["Source"]["select"]["name"] == "Stryd"
        assert "stryd-" in props["External ID"]["rich_text"][0]["text"]["content"]
        assert props["Power (W)"]["number"] == 230.0
        assert props["Duration (min)"]["number"] == 77  # 4642 / 60
        assert props["Distance (km)"]["number"] == 11.58
        assert props["Avg Heart Rate"]["number"] == 145

    def test_notes_contain_surface_and_type(self) -> None:
        metrics = {"elevation_gain": 120.5, "power": 200.0}
        props = build_stryd_create_properties(SAMPLE_ACTIVITY, metrics)
        notes = props["Notes"]["rich_text"][0]["text"]["content"]
        assert "trail" in notes
        assert "long" in notes
        assert "120.5m" in notes

    def test_no_name_falls_back(self) -> None:
        activity = {**SAMPLE_ACTIVITY, "name": ""}
        metrics = extract_power_metrics(activity)
        props = build_stryd_create_properties(activity, metrics)
        assert props["Name"]["title"][0]["text"]["content"] == "Stryd Run"

    def test_with_rpe_and_feel(self) -> None:
        metrics = {"power": 200.0, "elevation_gain": None}
        props = build_stryd_create_properties(
            SAMPLE_ACTIVITY, metrics, rpe=8, feel="Great"
        )
        assert props["RPE"]["number"] == 8
        assert props["Feeling"]["select"]["name"] == "Great"

    def test_external_id_format(self) -> None:
        metrics = extract_power_metrics(SAMPLE_ACTIVITY)
        props = build_stryd_create_properties(SAMPLE_ACTIVITY, metrics)
        ext_id = props["External ID"]["rich_text"][0]["text"]["content"]
        assert ext_id == f"stryd-{SAMPLE_ACTIVITY['timestamp']}"
