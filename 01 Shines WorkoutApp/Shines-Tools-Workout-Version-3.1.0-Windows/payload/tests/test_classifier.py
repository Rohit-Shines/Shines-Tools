from __future__ import annotations

from workout_ai.classifier import ExerciseClassifier
from tests.test_exercises import pushup_pose, standing_pose


def test_stationary_standing_is_not_guessed_as_pushup():
    classifier = ExerciseClassifier(window=30, lock_frames=6)
    result = None
    for index in range(45):
        result = classifier.update(standing_pose(index / 30))
    assert result is not None
    assert result.exercise != "pushup"


def test_horizontal_plank_locks_pushup():
    classifier = ExerciseClassifier(window=30, lock_frames=6)
    result = None
    for index in range(45):
        result = classifier.update(pushup_pose(index / 30, down=(index % 20 > 12)))
    assert result is not None
    assert result.exercise == "pushup"
