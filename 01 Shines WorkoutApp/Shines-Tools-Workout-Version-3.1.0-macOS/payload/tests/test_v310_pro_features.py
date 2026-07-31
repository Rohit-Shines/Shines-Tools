from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from workout_ai.database import WorkoutDatabase
from workout_ai.exercises import SquatHoldTracker
from workout_ai.settings import AppSettings
from tests.test_v262_features import squat_hold_pose


def test_profile_shortcuts_are_editable_and_persistent(tmp_path: Path) -> None:
    path = tmp_path / "workouts.sqlite3"
    db = WorkoutDatabase(path)
    values = db.shortcuts("Rohit")
    values["pushup"] = "Z"
    values["squat"] = "Y"
    saved = db.set_shortcuts("Rohit", values)
    assert saved["pushup"] == "Z"
    reopened = WorkoutDatabase(path)
    assert reopened.shortcuts("Rohit")["squat"] == "Y"


def test_shortcut_conflicts_and_reserved_keys_are_rejected(tmp_path: Path) -> None:
    db = WorkoutDatabase(tmp_path / "workouts.sqlite3")
    values = db.shortcuts("Rohit")
    values["pushup"] = "Z"
    values["squat"] = "Z"
    with pytest.raises(ValueError, match="assigned to both"):
        db.set_shortcuts("Rohit", values)
    values = db.shortcuts("Rohit")
    values["pushup"] = "Q"
    with pytest.raises(ValueError, match="reserved"):
        db.set_shortcuts("Rohit", values)


def test_profile_clone_copies_goals_order_enabled_and_shortcuts(tmp_path: Path) -> None:
    db = WorkoutDatabase(tmp_path / "workouts.sqlite3")
    db.set_goal("Rohit", "pushup", 55)
    db.set_exercise_enabled("Rohit", "taekwondo_kick", True)
    db.set_exercise_order("Rohit", ["plank", "pushup", "squat"])
    shortcuts = db.shortcuts("Rohit")
    shortcuts["pushup"] = "Z"
    # Swap the existing Z owner if any (none by default).
    db.set_shortcuts("Rohit", shortcuts)
    db.clone_profile_settings("Rohit", "Priya")
    assert db.goals("Priya")["pushup"] == 55
    assert db.exercise_settings("Priya")["taekwondo_kick"]["enabled"] is True
    assert db.ordered_exercises("Priya")[:3] == ("plank", "pushup", "squat")
    assert db.shortcuts("Priya")["pushup"] == "Z"


def test_coaching_uses_stored_form_scores_and_feedback(tmp_path: Path) -> None:
    db = WorkoutDatabase(tmp_path / "workouts.sqlite3")
    session = db.start_session("Rohit", datetime.now(), None, "manual")
    base = datetime.now() - timedelta(minutes=3)
    for index in range(20):
        db.add_rep(
            session,
            "Rohit",
            "pushup",
            base + timedelta(seconds=index),
            80.0 + index * 0.3,
            65.0,
            1.0,
            feedback="Keep hips aligned",
        )
    coaching = db.coaching_insights("Rohit")
    pushup = next(item for item in coaching["items"] if item["exercise"] == "pushup")
    assert pushup["average_form"] is not None
    assert pushup["sample_count"] == 20
    assert pushup["feedback"] == "Keep hips aligned"


def test_timed_hold_enters_fractional_seconds_mode_quickly() -> None:
    tracker = SquatHoldTracker(0.60)
    output = None
    timestamp = 0.0
    for _ in range(10):
        output = tracker.update(squat_hold_pose(timestamp))
        timestamp += 0.1
    assert output is not None
    assert output.phase == "holding"
    assert output.live_value is not None
    assert output.live_value >= 0.5
    assert output.unit == "seconds"


def test_reminder_defaults_are_portable(tmp_path: Path) -> None:
    settings = AppSettings(tmp_path / "settings.json")
    values = settings.load()
    assert values["reminder_interval_minutes"] == 30
    saved = settings.update(reminder_enabled=True, reminder_interval_minutes=20)
    assert saved["reminder_enabled"] is True
    assert AppSettings(tmp_path / "settings.json").load()["reminder_interval_minutes"] == 20
