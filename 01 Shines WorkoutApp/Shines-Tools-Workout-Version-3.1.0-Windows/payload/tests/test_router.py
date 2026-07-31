from __future__ import annotations

from workout_ai.classifier import Classification
from workout_ai.exercises import TrackerOutput
from workout_ai.router import AutoExerciseRouter


def out(exercise: str, *, completed: bool = False, valid: bool = True, confidence: float = 0.7, phase: str = "up") -> TrackerOutput:
    return TrackerOutput(
        exercise=exercise,
        reps=1 if completed else 0,
        phase=phase,
        valid_pose=valid,
        confidence=confidence,
        form_score=confidence * 100,
        feedback="",
        rep_completed=completed,
    )


def test_first_completed_rep_can_fast_lock_correct_exercise():
    router = AutoExerciseRouter()
    outputs = {
        "pushup": out("pushup", completed=True, confidence=0.75),
        "squat": out("squat", valid=False, confidence=0.0, phase="search"),
    }
    classification = Classification(None, 0.50, {"pushup": 0.50, "squat": 0.10}, False, "pushup", 0.40)
    assert router.accept_completed_rep("pushup", 1.0, classification, outputs)
    assert router.active == "pushup"


def test_shadow_tracker_cannot_steal_fresh_active_set():
    router = AutoExerciseRouter()
    router.active = "shoulder_press"
    router.last_active_evidence = 2.0
    outputs = {
        "shoulder_press": out("shoulder_press", valid=True, confidence=0.72, phase="up"),
        "curl": out("curl", completed=True, confidence=0.68),
    }
    classification = Classification(None, 0.46, {"shoulder_press": 0.47, "curl": 0.45}, False, "curl", 0.02)
    assert not router.accept_completed_rep("curl", 2.3, classification, outputs)
    assert router.active == "shoulder_press"
