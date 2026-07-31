from __future__ import annotations

from datetime import datetime
from pathlib import Path

from workout_ai.classifier import Classification
from workout_ai.constants import KEY_TO_EXERCISE
from workout_ai.database import WorkoutDatabase
from workout_ai.exercises import TrackerOutput
from workout_ai.geometry import Landmark, PoseFrame
from workout_ai.gestures import HeadTouchExerciseSelector
from workout_ai.router import AutoExerciseRouter


def _pose(*, left_touch: bool = False, right_touch: bool = False, timestamp: float = 0.0) -> PoseFrame:
    points = [Landmark(0.5, 0.5, visibility=1.0, presence=1.0) for _ in range(33)]
    # Upright torso.
    points[11] = Landmark(0.40, 0.32, visibility=1.0, presence=1.0)  # left shoulder
    points[12] = Landmark(0.60, 0.32, visibility=1.0, presence=1.0)  # right shoulder
    points[23] = Landmark(0.40, 0.66, visibility=1.0, presence=1.0)  # left hip
    points[24] = Landmark(0.60, 0.66, visibility=1.0, presence=1.0)  # right hip
    points[7] = Landmark(0.43, 0.20, visibility=1.0, presence=1.0)   # left ear
    points[8] = Landmark(0.57, 0.20, visibility=1.0, presence=1.0)   # right ear
    points[15] = Landmark(0.43, 0.20 if left_touch else 0.72, visibility=1.0, presence=1.0)
    points[16] = Landmark(0.57, 0.20 if right_touch else 0.72, visibility=1.0, presence=1.0)
    return PoseFrame(points, points, timestamp)


def test_version3_priority_shortcuts_are_simple() -> None:
    assert KEY_TO_EXERCISE["p"] == "pushup"
    assert KEY_TO_EXERCISE["s"] == "squat"
    assert KEY_TO_EXERCISE["h"] == "shoulder_press"
    assert KEY_TO_EXERCISE["b"] == "curl"
    assert KEY_TO_EXERCISE["t"] == "taekwondo_kick"


def test_head_touch_gesture_cycles_previous_and_next() -> None:
    selector = HeadTouchExerciseSelector(("pushup", "squat", "curl"), hold_seconds=0.4, cooldown_seconds=0.7)
    selector.update(_pose(left_touch=True, timestamp=0.0), 0.0)
    result = selector.update(_pose(left_touch=True, timestamp=0.5), 0.5)
    assert result.direction == -1
    assert result.selected_exercise == "curl"

    selector.update(_pose(right_touch=True, timestamp=1.3), 1.3)
    result = selector.update(_pose(right_touch=True, timestamp=1.8), 1.8)
    assert result.direction == 1
    assert result.selected_exercise == "pushup"


def test_personal_best_is_highest_single_session(tmp_path: Path) -> None:
    db = WorkoutDatabase(tmp_path / "workouts.sqlite3")
    profile = "Rohit"
    first = db.start_session(profile, datetime.now(), None, "auto")
    for _ in range(20):
        db.add_rep(first, profile, "pushup", datetime.now(), 80, None, None)
    second = db.start_session(profile, datetime.now(), None, "auto")
    for _ in range(21):
        db.add_rep(second, profile, "pushup", datetime.now(), 80, None, None)
    assert db.personal_bests(profile)["pushup"] == 21
    assert db.summary(profile)["personal_bests"]["pushup"] == 21


def test_preferred_exercise_hint_can_accept_unique_completion() -> None:
    router = AutoExerciseRouter()
    classification = Classification(None, 0.0, {"curl": 0.1, "squat": 0.1}, False, None, 0.0)
    outputs = {
        "curl": TrackerOutput("curl", 0, "up", True, 0.52, 70, "ok", rep_completed=True, rep_quality=0.70),
        "squat": TrackerOutput("squat", 0, "search", False, 0.0, 0, "no"),
    }
    assert router.accept_completed_rep("curl", 1.0, classification, outputs, "curl") is True
    assert router.active == "curl"
