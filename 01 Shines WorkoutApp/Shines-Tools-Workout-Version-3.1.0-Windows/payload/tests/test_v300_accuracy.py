from __future__ import annotations

from workout_ai.classifier import ExerciseClassifier
from workout_ai.constants import (
    KEY_TO_EXERCISE,
    LEFT_ANKLE,
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    LEFT_WRIST,
    RIGHT_ANKLE,
    RIGHT_ELBOW,
    RIGHT_HIP,
    RIGHT_KNEE,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
)
from workout_ai.exercises import CurlTracker, ShoulderPressTracker
from workout_ai.geometry import Landmark, PoseFrame
from tests.test_exercises import blank_pose, pushup_pose, shoulder_press_pose, squat_pose


def curl_pose(timestamp: float, contracted: bool) -> PoseFrame:
    points = blank_pose(timestamp)
    for shoulder, elbow, wrist, hip, knee, ankle, x, direction in (
        (LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE, 0.43, -1),
        (RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST, RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE, 0.57, 1),
    ):
        points[shoulder] = Landmark(x, 0.30, 0.0, 0.98, 0.98)
        points[hip] = Landmark(x, 0.60, 0.0, 0.98, 0.98)
        points[knee] = Landmark(x, 0.78, 0.0, 0.98, 0.98)
        points[ankle] = Landmark(x, 0.94, 0.0, 0.98, 0.98)
        points[elbow] = Landmark(x + direction * 0.02, 0.48, 0.0, 0.98, 0.98)
        points[wrist] = Landmark(
            x + direction * (0.08 if contracted else 0.03),
            0.35 if contracted else 0.67,
            0.0,
            0.98,
            0.98,
        )
    return PoseFrame(points, list(points), timestamp)


def classify_sequence(enabled, pose_factory):
    classifier = ExerciseClassifier(window=24, lock_frames=2, enabled_exercises=enabled)
    result = None
    for index in range(60):
        result = classifier.update(pose_factory(index))
    assert result is not None
    return result


def test_pushup_and_squat_only_profile_never_crosses_orientation_family():
    push = classify_sequence(
        ("pushup", "squat"),
        lambda i: pushup_pose(i / 30, down=(i % 24 >= 12)),
    )
    squat = classify_sequence(
        ("pushup", "squat"),
        lambda i: squat_pose(i / 30, down=(i % 24 >= 12)),
    )
    assert push.exercise == "pushup"
    assert push.scores["squat"] <= 0.01
    assert squat.exercise == "squat"
    assert squat.scores["pushup"] <= 0.01


def test_shoulder_press_and_curl_are_separated_by_overhead_wrist_path():
    press = classify_sequence(
        ("curl", "shoulder_press"),
        lambda i: shoulder_press_pose(i / 30, up=(12 <= i % 30 < 22)),
    )
    curl = classify_sequence(
        ("curl", "shoulder_press"),
        lambda i: curl_pose(i / 30, contracted=(12 <= i % 30 < 22)),
    )
    assert press.exercise == "shoulder_press"
    assert press.scores["shoulder_press"] > press.scores["curl"] + 0.25
    assert curl.exercise == "curl"
    assert curl.scores["curl"] > curl.scores["shoulder_press"] + 0.25


def test_shoulder_press_does_not_increment_curl_tracker():
    curl = CurlTracker(0.60)
    press = ShoulderPressTracker(0.60)
    timestamp = 0.0
    for _ in range(15):
        pose = shoulder_press_pose(timestamp, up=False)
        curl.update(pose)
        press.update(pose)
        timestamp += 1 / 30
    for _ in range(12):
        pose = shoulder_press_pose(timestamp, up=True)
        curl.update(pose)
        press.update(pose)
        timestamp += 1 / 30
    for _ in range(15):
        pose = shoulder_press_pose(timestamp, up=False)
        curl.update(pose)
        press.update(pose)
        timestamp += 1 / 30
    assert curl.reps == 0
    assert press.reps == 1


def test_priority_manual_shortcuts_are_unique():
    priority = {
        "p": "pushup",
        "s": "squat",
        "h": "shoulder_press",
        "b": "curl",
        "t": "taekwondo_kick",
    }
    assert {key: KEY_TO_EXERCISE[key] for key in priority} == priority
    assert len(set(KEY_TO_EXERCISE)) == len(KEY_TO_EXERCISE)
