from __future__ import annotations

from pathlib import Path

from workout_ai.database import WorkoutDatabase
from workout_ai.geometry import Landmark, PoseFrame
from workout_ai.gestures import HeadTouchExerciseSelector


def _face_pose(*, left: bool = False, right: bool = False, timestamp: float = 0.0) -> PoseFrame:
    points = [Landmark(0.5, 0.5, visibility=1.0, presence=1.0) for _ in range(33)]
    points[0] = Landmark(0.50, 0.19, visibility=1.0, presence=1.0)  # nose
    points[2] = Landmark(0.46, 0.18, visibility=1.0, presence=1.0)  # left eye
    points[5] = Landmark(0.54, 0.18, visibility=1.0, presence=1.0)  # right eye
    points[7] = Landmark(0.43, 0.21, visibility=1.0, presence=1.0)  # left ear
    points[8] = Landmark(0.57, 0.21, visibility=1.0, presence=1.0)  # right ear
    points[11] = Landmark(0.40, 0.34, visibility=1.0, presence=1.0)
    points[12] = Landmark(0.60, 0.34, visibility=1.0, presence=1.0)
    points[13] = Landmark(0.33, 0.27, visibility=1.0, presence=1.0)
    points[14] = Landmark(0.67, 0.27, visibility=1.0, presence=1.0)
    points[15] = Landmark(0.48, 0.20 if left else 0.70, visibility=1.0, presence=1.0)
    points[16] = Landmark(0.52, 0.20 if right else 0.70, visibility=1.0, presence=1.0)
    points[23] = Landmark(0.40, 0.68, visibility=1.0, presence=1.0)
    points[24] = Landmark(0.60, 0.68, visibility=1.0, presence=1.0)
    return PoseFrame(points, points, timestamp)


def test_left_face_touch_moves_up_and_right_face_touch_moves_down() -> None:
    selector = HeadTouchExerciseSelector(("pushup", "squat", "curl"), hold_seconds=0.25, cooldown_seconds=0.65)

    selector.update(_face_pose(left=True), 0.0)
    up = selector.update(_face_pose(left=True), 0.30)
    assert up.direction == -1
    assert up.selected_exercise == "curl"
    assert up.event and up.event.startswith("UP")

    selector.update(_face_pose(right=True), 1.0)
    down = selector.update(_face_pose(right=True), 1.30)
    assert down.direction == 1
    assert down.selected_exercise == "pushup"
    assert down.event and down.event.startswith("DOWN")


def test_face_touch_reports_progress_before_selection() -> None:
    selector = HeadTouchExerciseSelector(("pushup", "squat"), hold_seconds=0.40, cooldown_seconds=0.70)
    selector.update(_face_pose(left=True), 0.0)
    progress = selector.update(_face_pose(left=True), 0.20)
    assert progress.direction == 0
    assert progress.contact_side == "left"
    assert 0.45 <= progress.progress <= 0.55


def test_two_hand_face_contact_is_ignored() -> None:
    selector = HeadTouchExerciseSelector(("pushup", "squat"), hold_seconds=0.25, cooldown_seconds=0.70)
    selector.update(_face_pose(left=True, right=True), 0.0)
    result = selector.update(_face_pose(left=True, right=True), 0.40)
    assert result.direction == 0
    assert result.selected_exercise is None


def test_dashboard_exercise_preferences_persist(tmp_path: Path) -> None:
    path = tmp_path / "workouts.sqlite3"
    first = WorkoutDatabase(path)
    first.ensure_profile("Rohit")
    first.set_exercise_enabled("Rohit", "pushup", False)
    first.set_exercise_enabled("Rohit", "plank", True)
    first.set_goal("Rohit", "plank", 75)
    first.set_overall_daily_goal("Rohit", 120)

    reopened = WorkoutDatabase(path)
    settings = reopened.exercise_settings("Rohit")
    assert settings["pushup"]["enabled"] is False
    assert settings["plank"]["enabled"] is True
    assert settings["plank"]["goal"] == 75
    assert reopened.overall_daily_goal("Rohit") == 120
