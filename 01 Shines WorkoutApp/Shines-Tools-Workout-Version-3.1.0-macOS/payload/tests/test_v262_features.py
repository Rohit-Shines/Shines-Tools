from __future__ import annotations

import math
from pathlib import Path

from workout_ai.constants import (
    LEFT_ANKLE,
    LEFT_EAR,
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    LEFT_WRIST,
    NOSE,
    RIGHT_ANKLE,
    RIGHT_EAR,
    RIGHT_ELBOW,
    RIGHT_HIP,
    RIGHT_KNEE,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
)
from workout_ai.database import WorkoutDatabase
from workout_ai.exercises import (
    ArmCircleTracker,
    HeadTurnTracker,
    HipCircleTracker,
    SquatHoldTracker,
    TaekwondoKickTracker,
)
from workout_ai.geometry import Landmark, PoseFrame


def blank(timestamp: float) -> list[Landmark]:
    return [Landmark(0.5, 0.5, 0.0, 0.98, 0.98) for _ in range(33)]


def standing(timestamp: float) -> list[Landmark]:
    p = blank(timestamp)
    p[NOSE] = Landmark(0.50, 0.17, 0.0, 0.98, 0.98)
    p[LEFT_EAR] = Landmark(0.43, 0.18, 0.0, 0.98, 0.98)
    p[RIGHT_EAR] = Landmark(0.57, 0.18, 0.0, 0.98, 0.98)
    p[LEFT_SHOULDER] = Landmark(0.40, 0.30, 0.0, 0.98, 0.98)
    p[RIGHT_SHOULDER] = Landmark(0.60, 0.30, 0.0, 0.98, 0.98)
    p[LEFT_HIP] = Landmark(0.43, 0.56, 0.0, 0.98, 0.98)
    p[RIGHT_HIP] = Landmark(0.57, 0.56, 0.0, 0.98, 0.98)
    p[LEFT_KNEE] = Landmark(0.43, 0.73, 0.0, 0.98, 0.98)
    p[RIGHT_KNEE] = Landmark(0.57, 0.73, 0.0, 0.98, 0.98)
    p[LEFT_ANKLE] = Landmark(0.43, 0.91, 0.0, 0.98, 0.98)
    p[RIGHT_ANKLE] = Landmark(0.57, 0.91, 0.0, 0.98, 0.98)
    p[LEFT_ELBOW] = Landmark(0.35, 0.47, 0.0, 0.98, 0.98)
    p[RIGHT_ELBOW] = Landmark(0.65, 0.47, 0.0, 0.98, 0.98)
    p[LEFT_WRIST] = Landmark(0.33, 0.65, 0.0, 0.98, 0.98)
    p[RIGHT_WRIST] = Landmark(0.67, 0.65, 0.0, 0.98, 0.98)
    return p


def pose(points: list[Landmark], timestamp: float) -> PoseFrame:
    return PoseFrame(points, list(points), timestamp)


def test_taekwondo_kick_counts_either_leg_after_return() -> None:
    tracker = TaekwondoKickTracker(0.60)
    t = 0.0
    for _ in range(8):
        tracker.update(pose(standing(t), t)); t += 0.05
    high = standing(t)
    high[LEFT_KNEE] = Landmark(0.43, 0.36, 0.0, 0.98, 0.98)
    high[LEFT_ANKLE] = Landmark(0.43, 0.17, 0.0, 0.98, 0.98)
    for _ in range(7):
        tracker.update(pose(high, t)); t += 0.05
    output = None
    for _ in range(8):
        output = tracker.update(pose(standing(t), t)); t += 0.05
    assert tracker.reps == 1
    assert output is not None


def test_head_turn_counts_each_side_return_to_centre() -> None:
    tracker = HeadTurnTracker(0.60)
    t = 0.0
    for _ in range(4):
        tracker.update(pose(standing(t), t)); t += 0.1
    turned = standing(t)
    turned[NOSE] = Landmark(0.59, 0.17, 0.0, 0.98, 0.98)
    for _ in range(4):
        tracker.update(pose(turned, t)); t += 0.1
    for _ in range(4):
        tracker.update(pose(standing(t), t)); t += 0.1
    assert tracker.reps == 1


def arm_circle_pose(timestamp: float, degrees: float) -> PoseFrame:
    p = standing(timestamp)
    theta = math.radians(degrees)
    sx, sy, radius = 0.40, 0.30, 0.18
    wx = sx + radius * math.cos(theta)
    wy = sy - radius * math.sin(theta)
    p[LEFT_WRIST] = Landmark(wx, wy, 0.0, 0.99, 0.99)
    p[LEFT_ELBOW] = Landmark((sx + wx) / 2.0, (sy + wy) / 2.0, 0.0, 0.99, 0.99)
    p[RIGHT_SHOULDER] = Landmark(0.60, 0.30, 0.0, 0.35, 0.35)
    p[RIGHT_ELBOW] = Landmark(0.64, 0.46, 0.0, 0.20, 0.20)
    p[RIGHT_WRIST] = Landmark(0.66, 0.63, 0.0, 0.20, 0.20)
    return pose(p, timestamp)


def test_arm_circle_counts_complete_loop() -> None:
    tracker = ArmCircleTracker(0.60)
    t = 0.0
    for degree in range(0, 390, 10):
        tracker.update(arm_circle_pose(t, degree)); t += 0.04
    assert tracker.reps == 1


def hip_circle_pose(timestamp: float, degrees: float, radius: float = 0.045) -> PoseFrame:
    p = standing(timestamp)
    theta = math.radians(degrees)
    dx = radius * math.cos(theta)
    dy = radius * math.sin(theta)
    for h, k, a, base_x in (
        (LEFT_HIP, LEFT_KNEE, LEFT_ANKLE, 0.43),
        (RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE, 0.57),
    ):
        p[h] = Landmark(base_x + dx, 0.56 + dy, 0.0, 0.99, 0.99)
        p[k] = Landmark(base_x + dx, 0.73 + dy, 0.0, 0.99, 0.99)
        p[a] = Landmark(base_x + dx, 0.91 + dy, 0.0, 0.99, 0.99)
    return pose(p, timestamp)


def test_hip_circle_counts_complete_loop() -> None:
    tracker = HipCircleTracker(0.60)
    t = 0.0
    for _ in range(8):
        tracker.update(pose(standing(t), t)); t += 0.05
    for degree in range(0, 390, 10):
        tracker.update(hip_circle_pose(t, degree)); t += 0.05
    assert tracker.reps == 1


def squat_hold_pose(timestamp: float) -> PoseFrame:
    p = standing(timestamp)
    for s, h, k, a in (
        (LEFT_SHOULDER, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE),
        (RIGHT_SHOULDER, RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE),
    ):
        x = p[h].x
        p[s] = Landmark(x, 0.29, 0.0, 0.98, 0.98)
        p[h] = Landmark(x, 0.58, 0.0, 0.98, 0.98)
        p[k] = Landmark(x + 0.16, 0.70, 0.0, 0.98, 0.98)
        p[a] = Landmark(x, 0.88, 0.0, 0.98, 0.98)
    return pose(p, timestamp)


def test_timed_hold_exposes_live_fractional_seconds() -> None:
    tracker = SquatHoldTracker(0.60)
    output = None
    t = 0.0
    for _ in range(20):
        output = tracker.update(squat_hold_pose(t)); t += 0.1
    assert output is not None
    assert output.live_value is not None
    assert output.live_value >= 1.0
    assert tracker.reps >= 1


def test_exercise_order_persists_per_profile(tmp_path: Path) -> None:
    db = WorkoutDatabase(tmp_path / "workouts.sqlite3")
    profile = "Rohit"
    order = ["plank", "taekwondo_kick", "pushup", "squat"]
    db.set_exercise_order(profile, order)
    db.set_exercise_enabled(profile, "taekwondo_kick", True)
    reopened = WorkoutDatabase(tmp_path / "workouts.sqlite3")
    ordered = reopened.ordered_exercises(profile)
    assert ordered[:4] == tuple(order)
    enabled = reopened.enabled_exercises(profile)
    assert enabled.index("taekwondo_kick") < enabled.index("pushup")
