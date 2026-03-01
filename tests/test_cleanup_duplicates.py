"""Tests for scripts.cleanup_duplicates scoring and dedup logic."""

from typing import Any

from scripts.cleanup_duplicates import (
    find_duplicates,
    get_entry_date,
    get_entry_name,
    get_entry_source,
    get_power_properties,
    has_power_data,
    score_entry,
)


def _make_page(
    name: str = "Run",
    date: str = "2025-01-01",
    source: str = "Garmin",
    distance: float | None = None,
    hr: int | None = None,
    power: float | None = None,
    rss: float | None = None,
    critical_power: float | None = None,
    cadence: float | None = None,
    feeling: str | None = None,
    rpe: int | None = None,
    external_id: str = "",
) -> dict[str, Any]:
    """Build a minimal Notion page dict for testing."""
    props: dict[str, Any] = {
        "Name": {"type": "title", "title": [{"text": {"content": name}}]},
        "Date": {"type": "date", "date": {"start": date}},
        "Training Type": {"type": "select", "select": {"name": "Running"}},
        "Source": {"type": "select", "select": {"name": source}},
    }
    if external_id:
        props["External ID"] = {
            "type": "rich_text",
            "rich_text": [{"text": {"content": external_id}}],
        }
    if distance is not None:
        props["Distance (km)"] = {"type": "number", "number": distance}
    if hr is not None:
        props["Avg Heart Rate"] = {"type": "number", "number": hr}
    if power is not None:
        props["Power (W)"] = {"type": "number", "number": power}
    if rss is not None:
        props["RSS"] = {"type": "number", "number": rss}
    if critical_power is not None:
        props["Critical Power (W)"] = {"type": "number", "number": critical_power}
    if cadence is not None:
        props["Cadence (spm)"] = {"type": "number", "number": cadence}
    if feeling is not None:
        props["Feeling"] = {"type": "select", "select": {"name": feeling}}
    if rpe is not None:
        props["RPE"] = {"type": "number", "number": rpe}
    return {"id": f"page-{name.replace(' ', '-')}", "properties": props}


# ---------------------------------------------------------------------------
# score_entry
# ---------------------------------------------------------------------------


class TestScoreEntry:
    def test_power_entry_scores_higher(self) -> None:
        """Entry with power data gets the +3 bonus."""
        plain = _make_page("Run A", distance=10.0, hr=145)
        with_power = _make_page("Run B", distance=10.0, hr=145, power=230.0)
        assert score_entry(with_power) > score_entry(plain)

    def test_hr_entry_scores_higher(self) -> None:
        """Entry with HR gets the +2 bonus."""
        no_hr = _make_page("Run A", distance=10.0)
        with_hr = _make_page("Run B", distance=10.0, hr=150)
        assert score_entry(with_hr) > score_entry(no_hr)

    def test_micro_segment_scores_lowest(self) -> None:
        """A tiny 0.01km entry misses the distance bonus."""
        micro = _make_page("Micro", distance=0.01)
        normal = _make_page("Normal", distance=10.0)
        assert score_entry(normal) > score_entry(micro)

    def test_equal_entries_stable(self) -> None:
        """Two identical entries score the same — ordering is stable."""
        a = _make_page("Run A", distance=10.0, hr=145)
        b = _make_page("Run B", distance=10.0, hr=145)
        assert score_entry(a) == score_entry(b)


# ---------------------------------------------------------------------------
# find_duplicates
# ---------------------------------------------------------------------------


class TestFindDuplicates:
    def test_two_entries_same_date(self) -> None:
        """Two entries on the same date: keeper has more data."""
        p1 = _make_page("Afternoon Run", date="2025-01-01", distance=10.0)
        p2 = _make_page("Stryd Workout", date="2025-01-01", distance=10.0, power=230.0, hr=145)
        result = find_duplicates([p1, p2])
        assert len(result) == 1
        keeper, to_archive = result[0]
        assert get_entry_name(keeper) == "Stryd Workout"
        assert len(to_archive) == 1
        assert get_entry_name(to_archive[0]) == "Afternoon Run"

    def test_no_duplicates(self) -> None:
        """Entries on different dates — no duplicates."""
        p1 = _make_page("Run A", date="2025-01-01", distance=10.0)
        p2 = _make_page("Run B", date="2025-01-02", distance=10.0)
        assert find_duplicates([p1, p2]) == []

    def test_single_entry(self) -> None:
        p = _make_page("Run", date="2025-01-01")
        assert find_duplicates([p]) == []


# ---------------------------------------------------------------------------
# Helper extractors
# ---------------------------------------------------------------------------


class TestHelperExtractors:
    def test_get_entry_name(self) -> None:
        p = _make_page("Morning Run")
        assert get_entry_name(p) == "Morning Run"

    def test_get_entry_date(self) -> None:
        p = _make_page(date="2025-03-15")
        assert get_entry_date(p) == "2025-03-15"

    def test_get_entry_source(self) -> None:
        p = _make_page(source="Stryd")
        assert get_entry_source(p) == "Stryd"


# ---------------------------------------------------------------------------
# has_power_data
# ---------------------------------------------------------------------------


class TestHasPowerData:
    def test_with_power(self) -> None:
        p = _make_page(power=230.0)
        assert has_power_data(p) is True

    def test_with_rss_only(self) -> None:
        p = _make_page(rss=45.0)
        assert has_power_data(p) is True

    def test_with_critical_power_only(self) -> None:
        p = _make_page(critical_power=280.0)
        assert has_power_data(p) is True

    def test_without_power(self) -> None:
        p = _make_page(distance=10.0, hr=145)
        assert has_power_data(p) is False

    def test_empty_page(self) -> None:
        p = _make_page()
        assert has_power_data(p) is False


# ---------------------------------------------------------------------------
# get_power_properties
# ---------------------------------------------------------------------------


class TestGetPowerProperties:
    def test_extracts_all_stryd_metrics(self) -> None:
        p = _make_page(power=230.0, rss=45.0, critical_power=280.0, cadence=180.0)
        result = get_power_properties(p)
        assert result["Power (W)"] == {"number": 230.0}
        assert result["RSS"] == {"number": 45.0}
        assert result["Critical Power (W)"] == {"number": 280.0}
        assert result["Cadence (spm)"] == {"number": 180.0}

    def test_includes_feeling_if_present(self) -> None:
        p = _make_page(power=230.0, feeling="Good")
        result = get_power_properties(p)
        assert result["Power (W)"] == {"number": 230.0}
        assert result["Feeling"] == {"select": {"name": "Good"}}

    def test_includes_rpe_if_present(self) -> None:
        p = _make_page(power=230.0, rpe=7)
        result = get_power_properties(p)
        assert result["RPE"] == {"number": 7}

    def test_skips_missing_properties(self) -> None:
        p = _make_page(power=230.0)
        result = get_power_properties(p)
        assert "RSS" not in result
        assert "Cadence (spm)" not in result
        assert "Feeling" not in result

    def test_no_power_returns_empty(self) -> None:
        p = _make_page(distance=10.0, hr=145)
        result = get_power_properties(p)
        assert result == {}

    def test_does_not_include_non_stryd_props(self) -> None:
        p = _make_page(power=230.0, distance=10.0, hr=145)
        result = get_power_properties(p)
        assert "Distance (km)" not in result
        assert "Avg Heart Rate" not in result
