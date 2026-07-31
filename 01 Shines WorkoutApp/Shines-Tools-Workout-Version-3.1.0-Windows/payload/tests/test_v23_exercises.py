from __future__ import annotations

from workout_ai.constants import (
    LEFT_ANKLE, LEFT_ELBOW, LEFT_HIP, LEFT_KNEE, LEFT_SHOULDER, LEFT_WRIST,
    RIGHT_ANKLE, RIGHT_ELBOW, RIGHT_HIP, RIGHT_KNEE, RIGHT_SHOULDER, RIGHT_WRIST,
)
from workout_ai.exercises import HighKneeTracker, LateralRaiseTracker, LungeTracker
from workout_ai.geometry import Landmark, PoseFrame


def blank(timestamp: float) -> list[Landmark]:
    return [Landmark(0.5, 0.5, 0.0, 0.98, 0.98) for _ in range(33)]


def lunge_pose(timestamp: float, down: bool) -> PoseFrame:
    p = blank(timestamp)
    p[LEFT_SHOULDER] = Landmark(0.46, 0.18)
    p[RIGHT_SHOULDER] = Landmark(0.54, 0.18)
    p[LEFT_HIP] = Landmark(0.46, 0.46)
    p[RIGHT_HIP] = Landmark(0.54, 0.46)
    if down:
        p[LEFT_KNEE] = Landmark(0.46, 0.68)
        p[LEFT_ANKLE] = Landmark(0.25, 0.68)
        p[RIGHT_KNEE] = Landmark(0.61, 0.68)
        p[RIGHT_ANKLE] = Landmark(0.62, 0.90)
    else:
        p[LEFT_KNEE] = Landmark(0.46, 0.68)
        p[LEFT_ANKLE] = Landmark(0.46, 0.90)
        p[RIGHT_KNEE] = Landmark(0.54, 0.68)
        p[RIGHT_ANKLE] = Landmark(0.54, 0.90)
    return PoseFrame(p, list(p), timestamp)


def lateral_raise_pose(timestamp: float, up: bool) -> PoseFrame:
    p = blank(timestamp)
    p[LEFT_SHOULDER] = Landmark(0.43, 0.30)
    p[RIGHT_SHOULDER] = Landmark(0.57, 0.30)
    p[LEFT_HIP] = Landmark(0.45, 0.65)
    p[RIGHT_HIP] = Landmark(0.55, 0.65)
    if up:
        p[LEFT_ELBOW] = Landmark(0.27, 0.31)
        p[LEFT_WRIST] = Landmark(0.12, 0.31)
        p[RIGHT_ELBOW] = Landmark(0.73, 0.31)
        p[RIGHT_WRIST] = Landmark(0.88, 0.31)
    else:
        p[LEFT_ELBOW] = Landmark(0.42, 0.48)
        p[LEFT_WRIST] = Landmark(0.43, 0.67)
        p[RIGHT_ELBOW] = Landmark(0.58, 0.48)
        p[RIGHT_WRIST] = Landmark(0.57, 0.67)
    return PoseFrame(p, list(p), timestamp)


def high_knee_pose(timestamp: float, lifted: bool) -> PoseFrame:
    p = blank(timestamp)
    p[LEFT_SHOULDER] = Landmark(0.44, 0.18)
    p[RIGHT_SHOULDER] = Landmark(0.56, 0.18)
    p[LEFT_HIP] = Landmark(0.46, 0.48)
    p[RIGHT_HIP] = Landmark(0.54, 0.48)
    p[RIGHT_KNEE] = Landmark(0.54, 0.69)
    p[RIGHT_ANKLE] = Landmark(0.54, 0.91)
    if lifted:
        p[LEFT_KNEE] = Landmark(0.42, 0.38)
        p[LEFT_ANKLE] = Landmark(0.35, 0.55)
    else:
        p[LEFT_KNEE] = Landmark(0.46, 0.69)
        p[LEFT_ANKLE] = Landmark(0.46, 0.91)
    return PoseFrame(p, list(p), timestamp)


def test_lunge_counts_one_cycle():
    tracker = LungeTracker(0.50)
    t = 0.0
    for _ in range(15):
        tracker.update(lunge_pose(t, False)); t += 1 / 30
    for _ in range(15):
        tracker.update(lunge_pose(t, True)); t += 1 / 30
    for _ in range(18):
        tracker.update(lunge_pose(t, False)); t += 1 / 30
    assert tracker.reps == 1


def test_lateral_raise_counts_one_cycle():
    tracker = LateralRaiseTracker(0.50)
    t = 0.0
    for _ in range(15):
        tracker.update(lateral_raise_pose(t, False)); t += 1 / 30
    for _ in range(15):
        tracker.update(lateral_raise_pose(t, True)); t += 1 / 30
    for _ in range(18):
        tracker.update(lateral_raise_pose(t, False)); t += 1 / 30
    assert tracker.reps == 1


def test_high_knee_counts_each_lift():
    tracker = HighKneeTracker(0.50)
    t = 0.0
    for _ in range(12):
        tracker.update(high_knee_pose(t, False)); t += 1 / 30
    for _ in range(10):
        tracker.update(high_knee_pose(t, True)); t += 1 / 30
    for _ in range(12):
        tracker.update(high_knee_pose(t, False)); t += 1 / 30
    assert tracker.reps == 1
