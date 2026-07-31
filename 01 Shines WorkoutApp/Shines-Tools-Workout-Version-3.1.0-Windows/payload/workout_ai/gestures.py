from __future__ import annotations

from dataclasses import dataclass

from .constants import (
    LEFT_EAR,
    LEFT_ELBOW,
    LEFT_EYE,
    LEFT_HIP,
    LEFT_SHOULDER,
    LEFT_WRIST,
    NOSE,
    RIGHT_EAR,
    RIGHT_ELBOW,
    RIGHT_EYE,
    RIGHT_HIP,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
)
from .geometry import PoseFrame, angle, clamp, distance, line_angle_to_vertical


@dataclass(frozen=True)
class GestureResult:
    selected_exercise: str | None
    event: str | None = None
    direction: int = 0
    progress: float = 0.0
    contact_side: str | None = None


class HeadTouchExerciseSelector:
    """Hands-free exercise selector that runs alongside automatic recognition.

    Controls:
      * Left hand touching the face selects the previous enabled exercise (UP).
      * Right hand touching the face/head selects the next enabled exercise (DOWN).

    The gesture is deliberately conservative: the person must be upright, only
    one hand may be near the face, the working elbow must be bent, contact must
    be held briefly, and a cooldown prevents repeated scrolling. The selection
    is a *hint* for the automatic router rather than a hard manual lock.
    """

    def __init__(
        self,
        exercises: tuple[str, ...],
        *,
        hold_seconds: float = 0.30,
        cooldown_seconds: float = 0.90,
    ) -> None:
        self.exercises = tuple(exercises)
        self.hold_seconds = max(0.22, float(hold_seconds))
        self.cooldown_seconds = max(0.65, float(cooldown_seconds))
        self.index = -1
        self.selected: str | None = None
        self.left_started: float | None = None
        self.right_started: float | None = None
        self.last_triggered = -999.0

    def set_exercises(self, exercises: tuple[str, ...]) -> None:
        new_values = tuple(exercises)
        if new_values == self.exercises:
            return
        previous = self.selected
        self.exercises = new_values
        if previous in new_values:
            self.index = new_values.index(previous)
        else:
            self.index = -1
            self.selected = None
        self.left_started = None
        self.right_started = None

    def clear(self) -> None:
        self.index = -1
        self.selected = None
        self.left_started = None
        self.right_started = None

    def _cycle(self, direction: int) -> str | None:
        if not self.exercises:
            self.clear()
            return None
        if self.index < 0:
            self.index = 0 if direction > 0 else len(self.exercises) - 1
        else:
            self.index = (self.index + direction) % len(self.exercises)
        self.selected = self.exercises[self.index]
        return self.selected

    @staticmethod
    def _visible(pose: PoseFrame, indexes: tuple[int, ...], threshold: float = 0.42) -> bool:
        return all(
            pose.image[index].visibility >= threshold
            and pose.image[index].presence >= threshold
            for index in indexes
        )

    @staticmethod
    def _face_distance(pose: PoseFrame, wrist: int, targets: tuple[int, ...]) -> float:
        lm = pose.image
        visible_targets = [
            index
            for index in targets
            if lm[index].visibility >= 0.35 and lm[index].presence >= 0.35
        ]
        if not visible_targets:
            return 999.0
        return min(distance(lm[wrist], lm[index]) for index in visible_targets)

    def update(self, pose: PoseFrame, timestamp: float, *, allowed: bool = True) -> GestureResult:
        if not allowed or not self.exercises:
            self.left_started = None
            self.right_started = None
            return GestureResult(self.selected)

        lm = pose.image
        core = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)
        if not self._visible(pose, core, 0.35):
            self.left_started = None
            self.right_started = None
            return GestureResult(self.selected)

        shoulder_width = max(distance(lm[LEFT_SHOULDER], lm[RIGHT_SHOULDER]), 0.04)
        torso_vertical = min(
            line_angle_to_vertical(lm[LEFT_SHOULDER], lm[LEFT_HIP]),
            line_angle_to_vertical(lm[RIGHT_SHOULDER], lm[RIGHT_HIP]),
        )
        upright = torso_vertical <= 38.0

        left_visible = self._visible(pose, (LEFT_WRIST, LEFT_ELBOW, LEFT_SHOULDER), 0.36)
        right_visible = self._visible(pose, (RIGHT_WRIST, RIGHT_ELBOW, RIGHT_SHOULDER), 0.36)

        left_elbow_angle = (
            angle(lm[LEFT_SHOULDER], lm[LEFT_ELBOW], lm[LEFT_WRIST], dimensions=2)
            if left_visible
            else 180.0
        )
        right_elbow_angle = (
            angle(lm[RIGHT_SHOULDER], lm[RIGHT_ELBOW], lm[RIGHT_WRIST], dimensions=2)
            if right_visible
            else 180.0
        )

        # The nose is included so touching the cheek/centre of the face works;
        # same-side eye/ear landmarks keep left and right gestures distinct.
        left_distance = self._face_distance(pose, LEFT_WRIST, (LEFT_EAR, LEFT_EYE, NOSE))
        right_distance = self._face_distance(pose, RIGHT_WRIST, (RIGHT_EAR, RIGHT_EYE, NOSE))
        face_threshold = shoulder_width * 0.92

        left_near = (
            upright
            and left_visible
            and left_elbow_angle <= 155.0
            and left_distance <= face_threshold
        )
        right_near = (
            upright
            and right_visible
            and right_elbow_angle <= 155.0
            and right_distance <= face_threshold
        )

        # Ignore ambiguous two-hand contact; this can occur during stretches.
        if left_near and right_near:
            self.left_started = None
            self.right_started = None
            return GestureResult(self.selected)

        self.left_started = timestamp if left_near and self.left_started is None else self.left_started
        self.right_started = timestamp if right_near and self.right_started is None else self.right_started
        if not left_near:
            self.left_started = None
        if not right_near:
            self.right_started = None

        side: str | None = None
        progress = 0.0
        if self.left_started is not None:
            side = "left"
            progress = clamp((timestamp - self.left_started) / self.hold_seconds)
        elif self.right_started is not None:
            side = "right"
            progress = clamp((timestamp - self.right_started) / self.hold_seconds)

        if timestamp - self.last_triggered < self.cooldown_seconds:
            return GestureResult(self.selected, progress=progress, contact_side=side)

        if self.left_started is not None and timestamp - self.left_started >= self.hold_seconds:
            selected = self._cycle(-1)
            self.last_triggered = timestamp
            self.left_started = None
            return GestureResult(
                selected,
                "UP - previous exercise selected",
                -1,
                1.0,
                "left",
            )

        if self.right_started is not None and timestamp - self.right_started >= self.hold_seconds:
            selected = self._cycle(1)
            self.last_triggered = timestamp
            self.right_started = None
            return GestureResult(
                selected,
                "DOWN - next exercise selected",
                1,
                1.0,
                "right",
            )

        return GestureResult(self.selected, progress=progress, contact_side=side)
