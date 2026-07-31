from __future__ import annotations

from datetime import datetime

from workout_ai.constants import (
    LEFT_ANKLE, LEFT_ELBOW, LEFT_HIP, LEFT_KNEE, LEFT_SHOULDER, LEFT_WRIST,
    RIGHT_ANKLE, RIGHT_ELBOW, RIGHT_HIP, RIGHT_KNEE, RIGHT_SHOULDER, RIGHT_WRIST,
)
from workout_ai.database import WorkoutDatabase
from workout_ai.exercises import PlankTracker, SquatHoldTracker
from workout_ai.geometry import Landmark, PoseFrame


def blank() -> list[Landmark]:
    return [Landmark(0.5, 0.5, 0.0, 0.99, 0.99) for _ in range(33)]


def plank_pose(t: float) -> PoseFrame:
    p = blank()
    for shoulder, elbow, wrist, hip, knee, ankle, offset in (
        (LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE, 0.0),
        (RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST, RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE, 0.03),
    ):
        p[shoulder] = Landmark(0.25, 0.50 + offset)
        p[elbow] = Landmark(0.30, 0.66 + offset)
        p[wrist] = Landmark(0.36, 0.68 + offset)
        p[hip] = Landmark(0.52, 0.52 + offset)
        p[knee] = Landmark(0.70, 0.54 + offset)
        p[ankle] = Landmark(0.86, 0.57 + offset)
    return PoseFrame(p, list(p), t)


def squat_hold_pose(t: float) -> PoseFrame:
    p = blank()
    for shoulder, hip, knee, ankle, x in (
        (LEFT_SHOULDER, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE, 0.45),
        (RIGHT_SHOULDER, RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE, 0.55),
    ):
        p[shoulder] = Landmark(x, 0.20)
        p[hip] = Landmark(x, 0.48)
        p[knee] = Landmark(x + 0.18, 0.62)
        p[ankle] = Landmark(x, 0.78)
    return PoseFrame(p, list(p), t)


def test_plank_counts_elapsed_seconds():
    tracker = PlankTracker(0.50)
    for i in range(100):
        tracker.update(plank_pose(i / 30.0))
    assert tracker.reps >= 2


def test_squat_hold_counts_elapsed_seconds():
    tracker = SquatHoldTracker(0.50)
    for i in range(100):
        tracker.update(squat_hold_pose(i / 30.0))
    assert tracker.reps >= 2


def test_database_sums_compact_timed_values_and_preferences(tmp_path):
    db = WorkoutDatabase(tmp_path / "workouts.sqlite3")
    db.ensure_profile("Rohit")
    db.set_overall_daily_goal("Rohit", 100)
    db.set_exercise_enabled("Rohit", "forward_fold", True)
    session = db.start_session("Rohit", datetime.now(), tmp_path / "video.mp4", "auto")
    db.add_rep(session, "Rohit", "plank", datetime.now(), 80, None, 3.0, value=3, unit="seconds")
    assert db.session_counts(session)["plank"] == 3
    assert db.overall_daily_goal("Rohit") == 100
    assert db.exercise_settings("Rohit")["forward_fold"]["enabled"] is True
