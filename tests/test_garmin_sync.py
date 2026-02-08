"""Tests for scripts.garmin_sync helper functions."""

from datetime import date

from scripts.garmin_sync import (
    GARMIN_TYPE_MAPPING,
    build_health_properties,
    extract_body_battery,
    extract_resting_hr,
    extract_sleep_data,
    extract_steps,
    garmin_type_to_training_type,
)

# ---------------------------------------------------------------------------
# garmin_type_to_training_type
# ---------------------------------------------------------------------------


class TestGarminTypeToTrainingType:
    def test_running(self) -> None:
        assert garmin_type_to_training_type("running") == "Running"

    def test_trail_running(self) -> None:
        assert garmin_type_to_training_type("trail_running") == "Running"

    def test_cycling_maps_to_specifics(self) -> None:
        """Cycling should map to 'Specifics', not 'Running' (bug fix)."""
        assert garmin_type_to_training_type("cycling") == "Specifics"

    def test_unknown_type_defaults_to_specifics(self) -> None:
        assert garmin_type_to_training_type("surfing") == "Specifics"

    def test_hiit(self) -> None:
        assert garmin_type_to_training_type("hiit") == "Gym-Crossfit"

    def test_strength_training(self) -> None:
        assert garmin_type_to_training_type("strength_training") == "Gym-Strength"

    def test_walking(self) -> None:
        assert garmin_type_to_training_type("walking") == "Mobility"

    def test_case_insensitive(self) -> None:
        assert garmin_type_to_training_type("RUNNING") == "Running"
        assert garmin_type_to_training_type("Cycling") == "Specifics"


class TestMappingCoverage:
    """Verify that every key in the mapping dict is exercised above."""

    def test_all_keys_have_expected_values(self) -> None:
        expected = {
            "running": "Running",
            "trail_running": "Running",
            "treadmill_running": "Running",
            "cycling": "Specifics",
            "walking": "Mobility",
            "strength_training": "Gym-Strength",
            "hiit": "Gym-Crossfit",
        }
        assert expected == GARMIN_TYPE_MAPPING

    def test_all_mapping_keys_return_via_function(self) -> None:
        for key, value in GARMIN_TYPE_MAPPING.items():
            assert garmin_type_to_training_type(key) == value


# ---------------------------------------------------------------------------
# extract_sleep_data
# ---------------------------------------------------------------------------


class TestExtractSleepData:
    def test_normal(self) -> None:
        data = {
            "dailySleepDTO": {
                "sleepTimeSeconds": 27000,  # 7.5 hours
                "sleepQualityType": "GOOD",
            }
        }
        hours, quality = extract_sleep_data(data)
        assert hours == 7.5
        assert quality == "GOOD"

    def test_missing_dto(self) -> None:
        hours, quality = extract_sleep_data({})
        assert hours is None
        assert quality is None

    def test_none_input(self) -> None:
        hours, quality = extract_sleep_data(None)
        assert hours is None
        assert quality is None

    def test_zero_seconds(self) -> None:
        data = {
            "dailySleepDTO": {
                "sleepTimeSeconds": 0,
                "sleepQualityType": "POOR",
            }
        }
        hours, quality = extract_sleep_data(data)
        assert hours is None
        assert quality is None

    def test_none_seconds(self) -> None:
        data = {
            "dailySleepDTO": {
                "sleepTimeSeconds": None,
                "sleepQualityType": "POOR",
            }
        }
        hours, quality = extract_sleep_data(data)
        assert hours is None
        assert quality is None


# ---------------------------------------------------------------------------
# extract_steps
# ---------------------------------------------------------------------------


class TestExtractSteps:
    def test_normal(self) -> None:
        data = [{"steps": 5000}, {"steps": 3000}]
        assert extract_steps(data) == 8000

    def test_empty_list(self) -> None:
        assert extract_steps([]) is None

    def test_none_input(self) -> None:
        assert extract_steps(None) is None

    def test_zero_steps(self) -> None:
        data = [{"steps": 0}]
        assert extract_steps(data) is None


# ---------------------------------------------------------------------------
# extract_resting_hr
# ---------------------------------------------------------------------------


class TestExtractRestingHr:
    def test_normal(self) -> None:
        data = {"restingHeartRate": 55}
        assert extract_resting_hr(data) == 55

    def test_missing_key(self) -> None:
        assert extract_resting_hr({}) is None

    def test_none_input(self) -> None:
        assert extract_resting_hr(None) is None


# ---------------------------------------------------------------------------
# extract_body_battery
# ---------------------------------------------------------------------------


class TestExtractBodyBattery:
    def test_normal(self) -> None:
        data = [{"charged": 60}, {"charged": 80}, {"charged": 45}]
        assert extract_body_battery(data) == 80

    def test_empty_list(self) -> None:
        assert extract_body_battery([]) is None

    def test_none_input(self) -> None:
        assert extract_body_battery(None) is None

    def test_no_charged_keys(self) -> None:
        data = [{"drained": 10}]
        assert extract_body_battery(data) is None


# ---------------------------------------------------------------------------
# build_health_properties
# ---------------------------------------------------------------------------


class TestBuildHealthProperties:
    def test_all_fields(self) -> None:
        props = build_health_properties(
            target_date=date(2026, 2, 7),
            sleep_hours=7.5,
            sleep_quality="GOOD",
            steps=9200,
            resting_hr=55,
            body_battery=80,
        )
        assert props["Date Label"]["title"][0]["text"]["content"] == "Health Log — 2026-02-07"
        assert props["Date"]["date"]["start"] == "2026-02-07"
        assert props["External ID"]["rich_text"][0]["text"]["content"] == "garmin-health-2026-02-07"
        assert props["Sleep Duration (h)"]["number"] == 7.5
        assert props["Sleep Quality"]["select"]["name"] == "GOOD"
        assert props["Steps"]["number"] == 9200
        assert props["Resting HR"]["number"] == 55
        assert props["Body Battery"]["number"] == 80

    def test_some_none(self) -> None:
        props = build_health_properties(
            target_date=date(2026, 2, 7),
            sleep_hours=7.0,
            sleep_quality=None,
            steps=None,
            resting_hr=55,
            body_battery=None,
        )
        assert "Sleep Duration (h)" in props
        assert "Sleep Quality" not in props
        assert "Steps" not in props
        assert "Resting HR" in props
        assert "Body Battery" not in props

    def test_external_id_format(self) -> None:
        props = build_health_properties(
            target_date=date(2026, 1, 15),
            sleep_hours=None,
            sleep_quality=None,
            steps=None,
            resting_hr=None,
            body_battery=None,
        )
        ext_id = props["External ID"]["rich_text"][0]["text"]["content"]
        assert ext_id == "garmin-health-2026-01-15"
