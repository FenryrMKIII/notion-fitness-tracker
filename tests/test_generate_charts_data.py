"""Tests for scripts/generate_charts_data.py — pure functions."""

from datetime import date

from scripts.generate_charts_data import build_charts_data, compute_rolling_acwr
from scripts.update_dashboard import RunningPeriod

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_training(
    dt: str,
    name: str = "Run",
    training_type: str = "Running",
    duration_min: float = 30,
    distance_km: float = 5.0,
    volume_kg: float = 0,
    feeling: str = "Good",
    avg_hr: float | None = 150,
    power_w: float | None = 250,
    rss: float | None = 50,
    source: str = "Garmin",
    **kwargs: float | None,
) -> dict[str, object]:
    return {
        "name": name,
        "date": dt,
        "training_type": training_type,
        "duration_min": duration_min,
        "distance_km": distance_km,
        "volume_kg": volume_kg,
        "feeling": feeling,
        "avg_hr": avg_hr,
        "power_w": power_w,
        "rss": rss,
        "critical_power_w": kwargs.get("critical_power_w"),
        "cadence_spm": kwargs.get("cadence_spm"),
        "stride_length_m": kwargs.get("stride_length_m"),
        "ground_contact_ms": kwargs.get("ground_contact_ms"),
        "vertical_oscillation_cm": kwargs.get("vertical_oscillation_cm"),
        "leg_spring_stiffness": kwargs.get("leg_spring_stiffness"),
        "rpe": kwargs.get("rpe"),
        "temperature_c": kwargs.get("temperature_c"),
        "wind_speed": kwargs.get("wind_speed"),
        "source": source,
    }


def _make_health(
    dt: str,
    sleep_hours: float = 7.5,
    sleep_quality: str = "GOOD",
    resting_hr: float = 55,
    steps: float = 8000,
    body_battery: float = 70,
) -> dict[str, object]:
    return {
        "date": dt,
        "sleep_hours": sleep_hours,
        "sleep_quality": sleep_quality,
        "resting_hr": resting_hr,
        "steps": steps,
        "body_battery": body_battery,
    }


# ---------------------------------------------------------------------------
# TestBuildChartsData
# ---------------------------------------------------------------------------


class TestBuildChartsData:
    def test_empty_data(self) -> None:
        result = build_charts_data([], [], date(2026, 2, 9))
        assert result["meta"]["total_training"] == 0
        assert result["meta"]["total_health"] == 0
        assert result["sessions"] == []
        assert result["health"] == []
        assert result["weekly"]["training"] == []

    def test_single_session(self) -> None:
        training = [_make_training("2026-02-03")]
        result = build_charts_data(training, [], date(2026, 2, 9))
        assert result["meta"]["total_training"] == 1
        assert result["meta"]["total_health"] == 0
        assert len(result["sessions"]) == 1
        assert result["sessions"][0]["name"] == "Run"
        assert result["sessions"][0]["date"] == "2026-02-03"

    def test_single_health(self) -> None:
        health = [_make_health("2026-02-03")]
        result = build_charts_data([], health, date(2026, 2, 9))
        assert result["meta"]["total_health"] == 1
        assert len(result["health"]) == 1
        assert result["health"][0]["sleep_hours"] == 7.5

    def test_session_serialization_fields(self) -> None:
        training = [_make_training("2026-02-03", power_w=260, rss=80)]
        result = build_charts_data(training, [], date(2026, 2, 9))
        s = result["sessions"][0]
        assert s["power_w"] == 260
        assert s["rss"] == 80
        assert s["training_type"] == "Running"
        assert s["source"] == "Garmin"

    def test_health_serialization_fields(self) -> None:
        health = [_make_health("2026-02-03", resting_hr=52, body_battery=85)]
        result = build_charts_data([], health, date(2026, 2, 9))
        h = result["health"][0]
        assert h["resting_hr"] == 52
        assert h["body_battery"] == 85

    def test_weekly_aggregates_populated(self) -> None:
        training = [
            _make_training("2026-02-03", rss=50),
            _make_training("2026-02-04", rss=60),
        ]
        health = [
            _make_health("2026-02-03"),
            _make_health("2026-02-04"),
        ]
        result = build_charts_data(training, health, date(2026, 2, 9))
        assert len(result["weekly"]["training"]) >= 1
        assert len(result["weekly"]["health"]) >= 1
        assert len(result["weekly"]["running"]) >= 1
        assert len(result["weekly"]["load"]) >= 1

    def test_weekly_training_values(self) -> None:
        # Two runs in the same week (Feb 3 Mon - Feb 9 Sun)
        training = [
            _make_training("2026-02-03", distance_km=5.0, duration_min=30),
            _make_training("2026-02-05", distance_km=10.0, duration_min=60),
        ]
        result = build_charts_data(training, [], date(2026, 2, 9))

        # Find the week containing Feb 3
        week = None
        for w in result["weekly"]["training"]:
            if w["week_start"] == "2026-02-02":
                week = w
                break

        assert week is not None
        assert week["sessions"] == 2
        assert week["running_km"] == 15.0
        assert week["running_count"] == 2


# ---------------------------------------------------------------------------
# TestComputeRollingAcwr
# ---------------------------------------------------------------------------


class TestComputeRollingAcwr:
    def test_empty(self) -> None:
        result = compute_rolling_acwr([], [])
        assert result == []

    def test_single_week(self) -> None:
        rp = RunningPeriod(label="W1", total_rss=100.0)
        result = compute_rolling_acwr([rp], [date(2026, 2, 3)])
        assert len(result) == 1
        assert result[0]["weekly_rss"] == 100.0
        assert result[0]["week_start"] == "2026-02-03"
        # With only 1 week: acute = 100, chronic = 100, ACWR = 1.0
        assert result[0]["acwr"] == 1.0

    def test_four_week_window(self) -> None:
        periods = [
            RunningPeriod(label=f"W{i}", total_rss=float(rss))
            for i, rss in enumerate([100, 120, 80, 200])
        ]
        starts = [
            date(2026, 1, 13),
            date(2026, 1, 20),
            date(2026, 1, 27),
            date(2026, 2, 3),
        ]
        result = compute_rolling_acwr(periods, starts)
        assert len(result) == 4

        # Week 4 (i=3): acute = 200, chronic = avg(100, 120, 80) = 100
        last = result[3]
        assert last["weekly_rss"] == 200.0
        assert last["acute_load"] == 200.0
        assert last["chronic_load"] == 100.0
        assert last["acwr"] == 2.0
        assert last["load_status"] == "danger"

    def test_rolling_window_shifts(self) -> None:
        periods = [
            RunningPeriod(label=f"W{i}", total_rss=float(rss))
            for i, rss in enumerate([50, 60, 70, 80, 90])
        ]
        starts = [
            date(2026, 1, 6),
            date(2026, 1, 13),
            date(2026, 1, 20),
            date(2026, 1, 27),
            date(2026, 2, 3),
        ]
        result = compute_rolling_acwr(periods, starts)
        assert len(result) == 5

        # Week 5 (i=4): acute = 90, chronic = avg(60, 70, 80) = 70
        w5 = result[4]
        assert w5["acute_load"] == 90.0
        assert w5["chronic_load"] == 70.0
        assert w5["acwr"] == round(90.0 / 70.0, 2)

    def test_load_status_zones(self) -> None:
        # Detraining: ACWR < 0.8 (acute 30 vs chronic 100)
        periods = [
            RunningPeriod(label="W1", total_rss=100.0),
            RunningPeriod(label="W2", total_rss=100.0),
            RunningPeriod(label="W3", total_rss=100.0),
            RunningPeriod(label="W4", total_rss=30.0),
        ]
        starts = [date(2026, 1, 13), date(2026, 1, 20), date(2026, 1, 27), date(2026, 2, 3)]
        result = compute_rolling_acwr(periods, starts)
        assert result[3]["load_status"] == "detraining"

        # Optimal: ACWR ~1.0 (acute 100 vs chronic 100)
        periods2 = [
            RunningPeriod(label="W1", total_rss=100.0),
            RunningPeriod(label="W2", total_rss=100.0),
            RunningPeriod(label="W3", total_rss=100.0),
            RunningPeriod(label="W4", total_rss=100.0),
        ]
        result2 = compute_rolling_acwr(periods2, starts)
        assert result2[3]["load_status"] == "optimal"


# ---------------------------------------------------------------------------
# TestMeta
# ---------------------------------------------------------------------------


class TestMeta:
    def test_date_range_detection(self) -> None:
        training = [
            _make_training("2026-01-15"),
            _make_training("2026-02-03"),
        ]
        health = [_make_health("2026-01-20")]
        result = build_charts_data(training, health, date(2026, 2, 9))
        assert result["meta"]["earliest"] == "2026-01-15"
        assert result["meta"]["latest"] == "2026-02-03"

    def test_record_counts(self) -> None:
        training = [_make_training("2026-02-03"), _make_training("2026-02-04")]
        health = [_make_health("2026-02-03")]
        result = build_charts_data(training, health, date(2026, 2, 9))
        assert result["meta"]["total_training"] == 2
        assert result["meta"]["total_health"] == 1

    def test_generated_at_present(self) -> None:
        result = build_charts_data([_make_training("2026-02-03")], [], date(2026, 2, 9))
        assert "generated_at" in result
        assert "T" in result["generated_at"]
