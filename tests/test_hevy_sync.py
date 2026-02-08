"""Tests for scripts.hevy_sync helper functions."""

from scripts.hevy_sync import (
    calculate_duration_min,
    calculate_volume,
    format_exercise_details,
)

# ---------------------------------------------------------------------------
# calculate_volume
# ---------------------------------------------------------------------------


class TestCalculateVolume:
    def test_basic_case(self) -> None:
        exercises = [
            {
                "title": "Bench Press",
                "sets": [
                    {"weight_kg": 80, "reps": 10},
                    {"weight_kg": 80, "reps": 8},
                ],
            }
        ]
        assert calculate_volume(exercises) == 80 * 10 + 80 * 8

    def test_empty_list(self) -> None:
        assert calculate_volume([]) == 0.0

    def test_none_weight(self) -> None:
        exercises = [
            {
                "title": "Pull Up",
                "sets": [{"weight_kg": None, "reps": 12}],
            }
        ]
        assert calculate_volume(exercises) == 0.0

    def test_multiple_exercises(self) -> None:
        exercises = [
            {
                "title": "Squat",
                "sets": [{"weight_kg": 100, "reps": 5}],
            },
            {
                "title": "Deadlift",
                "sets": [{"weight_kg": 120, "reps": 3}],
            },
        ]
        assert calculate_volume(exercises) == 100 * 5 + 120 * 3


# ---------------------------------------------------------------------------
# calculate_duration_min
# ---------------------------------------------------------------------------


class TestCalculateDurationMin:
    def test_normal_iso_timestamps(self) -> None:
        start = "2024-06-15T10:00:00+00:00"
        end = "2024-06-15T11:30:00+00:00"
        assert calculate_duration_min(start, end) == 90

    def test_short_duration(self) -> None:
        start = "2024-06-15T10:00:00+00:00"
        end = "2024-06-15T10:15:00+00:00"
        assert calculate_duration_min(start, end) == 15

    def test_zero_duration(self) -> None:
        ts = "2024-06-15T10:00:00+00:00"
        assert calculate_duration_min(ts, ts) == 0


# ---------------------------------------------------------------------------
# format_exercise_details
# ---------------------------------------------------------------------------


class TestFormatExerciseDetails:
    def test_exercises_with_sets(self) -> None:
        exercises = [
            {
                "title": "Bench Press",
                "sets": [
                    {"weight_kg": 80, "reps": 10},
                    {"weight_kg": 85, "reps": 8},
                ],
            }
        ]
        result = format_exercise_details(exercises)
        assert "Bench Press" in result
        assert "80x10" in result
        assert "85x8" in result

    def test_empty_exercises(self) -> None:
        assert format_exercise_details([]) == ""

    def test_exercise_with_distance(self) -> None:
        exercises = [
            {
                "title": "Rowing",
                "sets": [{"weight_kg": 0, "distance_meters": 500}],
            }
        ]
        result = format_exercise_details(exercises)
        assert "Rowing" in result
        assert "500m" in result

    def test_exercise_with_duration(self) -> None:
        exercises = [
            {
                "title": "Plank",
                "sets": [{"weight_kg": 0, "duration_seconds": 60}],
            }
        ]
        result = format_exercise_details(exercises)
        assert "Plank" in result
        assert "60s" in result

    def test_multiple_exercises_pipe_separated(self) -> None:
        exercises = [
            {"title": "A", "sets": [{"weight_kg": 10, "reps": 5}]},
            {"title": "B", "sets": [{"weight_kg": 20, "reps": 3}]},
        ]
        result = format_exercise_details(exercises)
        assert " | " in result
