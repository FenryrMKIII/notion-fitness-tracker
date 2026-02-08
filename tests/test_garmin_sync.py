"""Tests for scripts.garmin_sync helper functions."""

from scripts.garmin_sync import GARMIN_TYPE_MAPPING, garmin_type_to_training_type


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
        assert GARMIN_TYPE_MAPPING == expected

    def test_all_mapping_keys_return_via_function(self) -> None:
        for key, value in GARMIN_TYPE_MAPPING.items():
            assert garmin_type_to_training_type(key) == value
