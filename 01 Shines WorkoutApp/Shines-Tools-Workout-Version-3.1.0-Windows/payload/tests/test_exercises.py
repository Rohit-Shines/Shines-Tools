from __future__ import annotations

from datetime import datetime

from workout_ai.constants import (
    LEFT_ANKLE, LEFT_ELBOW, LEFT_HIP, LEFT_KNEE, LEFT_SHOULDER, LEFT_WRIST,
    RIGHT_ANKLE, RIGHT_ELBOW, RIGHT_HIP, RIGHT_KNEE, RIGHT_SHOULDER, RIGHT_WRIST,
)
from workout_ai.exercises import PushupTracker, SquatTracker
from workout_ai.geometry import Landmark, PoseFrame


def blank_pose(timestamp: float) -> list[Landmark]:
    return [Landmark(0.5, 0.5, 0.0, 0.95, 0.95) for _ in range(33)]


def pushup_pose(timestamp: float, down: bool = False) -> PoseFrame:
    p = blank_pose(timestamp)
    for s, e, w, h, k, a in (
        (LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE),
        (RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST, RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE),
    ):
        p[s] = Landmark(0.30, 0.50, 0.0, 0.98, 0.98)
        p[h] = Landmark(0.55, 0.50, 0.0, 0.98, 0.98)
        p[k] = Landmark(0.73, 0.50, 0.0, 0.98, 0.98)
        p[a] = Landmark(0.90, 0.50, 0.0, 0.98, 0.98)
        p[w] = Landmark(0.31, 0.65, 0.0, 0.98, 0.98)
        p[e] = Landmark(0.39, 0.58, 0.0, 0.98, 0.98) if down else Landmark(0.305, 0.575, 0.0, 0.98, 0.98)
    return PoseFrame(p, list(p), timestamp)


def standing_pose(timestamp: float, bent: bool = False) -> PoseFrame:
    p = blank_pose(timestamp)
    for s, e, w, h, k, a in (
        (LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE),
        (RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST, RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE),
    ):
        p[s] = Landmark(0.50, 0.20, 0.0, 0.98, 0.98)
        p[h] = Landmark(0.50, 0.50, 0.0, 0.98, 0.98)
        p[k] = Landmark(0.50, 0.70, 0.0, 0.98, 0.98)
        p[a] = Landmark(0.50, 0.90, 0.0, 0.98, 0.98)
        p[e] = Landmark(0.58, 0.35, 0.0, 0.98, 0.98)
        p[w] = Landmark(0.50 if bent else 0.62, 0.48 if bent else 0.52, 0.0, 0.98, 0.98)
    return PoseFrame(p, list(p), timestamp)


def squat_pose(timestamp: float, down: bool = False) -> PoseFrame:
    p = blank_pose(timestamp)
    for s, h, k, a in (
        (LEFT_SHOULDER, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE),
        (RIGHT_SHOULDER, RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE),
    ):
        if down:
            p[s] = Landmark(0.43, 0.25, 0.0, 0.98, 0.98)
            p[h] = Landmark(0.50, 0.56, 0.0, 0.98, 0.98)
            p[k] = Landmark(0.65, 0.70, 0.0, 0.98, 0.98)
            p[a] = Landmark(0.50, 0.88, 0.0, 0.98, 0.98)
        else:
            p[s] = Landmark(0.50, 0.20, 0.0, 0.98, 0.98)
            p[h] = Landmark(0.50, 0.50, 0.0, 0.98, 0.98)
            p[k] = Landmark(0.50, 0.70, 0.0, 0.98, 0.98)
            p[a] = Landmark(0.50, 0.90, 0.0, 0.98, 0.98)
    return PoseFrame(p, list(p), timestamp)


def test_standing_elbow_motion_never_counts_as_pushup():
    tracker = PushupTracker()
    t = 0.0
    for index in range(180):
        tracker.update(standing_pose(t, bent=(index // 15) % 2 == 1))
        t += 1 / 30
    assert tracker.reps == 0


def test_complete_pushup_counts_once():
    tracker = PushupTracker()
    t = 0.0
    output = None
    for _ in range(18):
        output = tracker.update(pushup_pose(t, down=False)); t += 1 / 30
    for _ in range(12):
        output = tracker.update(pushup_pose(t, down=True)); t += 1 / 30
    for _ in range(15):
        output = tracker.update(pushup_pose(t, down=False)); t += 1 / 30
    assert tracker.reps == 1
    assert output is not None


def test_noise_at_top_does_not_double_count_pushup():
    tracker = PushupTracker()
    t = 0.0
    for _ in range(18):
        tracker.update(pushup_pose(t, down=False)); t += 1 / 30
    for _ in range(12):
        tracker.update(pushup_pose(t, down=True)); t += 1 / 30
    for _ in range(60):
        tracker.update(pushup_pose(t, down=False)); t += 1 / 30
    assert tracker.reps == 1


def test_complete_squat_counts_once():
    tracker = SquatTracker()
    t = 0.0
    for _ in range(18):
        tracker.update(squat_pose(t, down=False)); t += 1 / 30
    for _ in range(15):
        tracker.update(squat_pose(t, down=True)); t += 1 / 30
    for _ in range(18):
        tracker.update(squat_pose(t, down=False)); t += 1 / 30
    assert tracker.reps == 1


def test_partial_pushup_never_counts():
    tracker = PushupTracker()
    t = 0.0
    for _ in range(18):
        tracker.update(pushup_pose(t, down=False)); t += 1 / 30
    # A shallow movement is represented by alternating top frames and never
    # reaching the strict down threshold.
    for _ in range(90):
        tracker.update(pushup_pose(t, down=False)); t += 1 / 30
    assert tracker.reps == 0


def test_two_complete_pushups_count_exactly_two():
    tracker = PushupTracker()
    t = 0.0
    for _ in range(18):
        tracker.update(pushup_pose(t, down=False)); t += 1 / 30
    for _rep in range(2):
        for _ in range(12):
            tracker.update(pushup_pose(t, down=True)); t += 1 / 30
        for _ in range(18):
            tracker.update(pushup_pose(t, down=False)); t += 1 / 30
    assert tracker.reps == 2


def acceptable_partial_pushup_pose(timestamp: float) -> PoseFrame:
    """A realistic, not-perfect push-up depth (~116 degree elbow)."""
    p = blank_pose(timestamp)
    for s, e, w, h, k, a in (
        (LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE),
        (RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST, RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE),
    ):
        p[s] = Landmark(0.30, 0.50, 0.0, 0.90, 0.90)
        p[h] = Landmark(0.55, 0.52, 0.0, 0.90, 0.90)  # small normal hip variation
        p[k] = Landmark(0.73, 0.51, 0.0, 0.88, 0.88)
        p[a] = Landmark(0.90, 0.50, 0.0, 0.88, 0.88)
        p[w] = Landmark(0.31, 0.65, 0.0, 0.90, 0.90)
        p[e] = Landmark(0.35, 0.56, 0.0, 0.90, 0.90)
    return PoseFrame(p, list(p), timestamp)


def shoulder_press_pose(timestamp: float, up: bool) -> PoseFrame:
    p = blank_pose(timestamp)
    # Torso and face are visible; right arm is deliberately occluded to confirm
    # that a normal one-arm or cropped-camera press can still be counted.
    p[LEFT_SHOULDER] = Landmark(0.42, 0.42, 0.0, 0.95, 0.95)
    p[RIGHT_SHOULDER] = Landmark(0.58, 0.42, 0.0, 0.80, 0.80)
    p[LEFT_HIP] = Landmark(0.45, 0.78, 0.0, 0.25, 0.25)
    p[RIGHT_HIP] = Landmark(0.55, 0.78, 0.0, 0.25, 0.25)
    p[RIGHT_ELBOW] = Landmark(0.60, 0.56, 0.0, 0.05, 0.05)
    p[RIGHT_WRIST] = Landmark(0.62, 0.65, 0.0, 0.05, 0.05)
    if up:
        p[LEFT_ELBOW] = Landmark(0.42, 0.30, 0.0, 0.95, 0.95)
        p[LEFT_WRIST] = Landmark(0.42, 0.14, 0.0, 0.95, 0.95)
    else:
        p[LEFT_ELBOW] = Landmark(0.34, 0.53, 0.0, 0.95, 0.95)
        p[LEFT_WRIST] = Landmark(0.42, 0.62, 0.0, 0.95, 0.95)
    return PoseFrame(p, list(p), timestamp)


def test_acceptable_partial_pushup_counts_at_human_threshold():
    tracker = PushupTracker(0.60)
    t = 0.0
    for _ in range(15):
        tracker.update(pushup_pose(t, down=False)); t += 1 / 30
    for _ in range(12):
        tracker.update(acceptable_partial_pushup_pose(t)); t += 1 / 30
    for _ in range(15):
        tracker.update(pushup_pose(t, down=False)); t += 1 / 30
    assert tracker.reps == 1


def test_one_arm_shoulder_press_counts_with_partial_camera_view():
    from workout_ai.exercises import ShoulderPressTracker

    tracker = ShoulderPressTracker(0.60)
    t = 0.0
    for _ in range(15):
        tracker.update(shoulder_press_pose(t, up=False)); t += 1 / 30
    for _ in range(12):
        tracker.update(shoulder_press_pose(t, up=True)); t += 1 / 30
    for _ in range(15):
        tracker.update(shoulder_press_pose(t, up=False)); t += 1 / 30
    assert tracker.reps == 1
