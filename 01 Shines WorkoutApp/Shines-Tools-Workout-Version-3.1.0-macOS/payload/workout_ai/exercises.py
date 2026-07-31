from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Optional

import numpy as np

from .constants import (
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
from .filters import MedianEMAFilter, StabilityCounter
from .geometry import (
    PoseFrame,
    angle,
    clamp,
    distance,
    line_angle_to_horizontal,
    line_angle_to_vertical,
    midpoint,
    robust_mean,
)


def _score_high(value: float, poor: float, good: float) -> float:
    """Return 0..1 where larger values are better."""
    if not np.isfinite(value) or good <= poor:
        return 0.0
    return clamp((value - poor) / (good - poor))


def _score_low(value: float, good: float, poor: float) -> float:
    """Return 0..1 where smaller values are better."""
    if not np.isfinite(value) or poor <= good:
        return 0.0
    return clamp((poor - value) / (poor - good))


def _mean_visibility(pose: PoseFrame, indexes: tuple[int, ...]) -> float:
    return float(np.mean([pose.image[i].visibility for i in indexes]))


@dataclass
class TrackerOutput:
    exercise: str
    reps: int
    phase: str
    valid_pose: bool
    confidence: float
    form_score: float
    feedback: str
    metric_name: str = ""
    metric_value: Optional[float] = None
    rep_completed: bool = False
    rep_rom: Optional[float] = None
    rep_duration: Optional[float] = None
    rep_quality: Optional[float] = None
    quality_threshold: float = 0.60
    active_landmarks: tuple[int, ...] = ()
    value_increment: int = 1
    unit: str = "reps"
    live_value: Optional[float] = None
    direction: str = ""


@dataclass
class RepCycle:
    phase: str = "search"
    phase_started: float = 0.0
    cycle_started: float = 0.0
    minimum: float = 999.0
    maximum: float = -999.0
    invalid_since: Optional[float] = None
    quality_total: float = 0.0
    quality_samples: int = 0
    acceptable_frames: int = 0

    def reset(self, phase: str = "search", now: float = 0.0) -> None:
        self.phase = phase
        self.phase_started = now
        self.cycle_started = 0.0
        self.minimum = 999.0
        self.maximum = -999.0
        self.invalid_since = None
        self.quality_total = 0.0
        self.quality_samples = 0
        self.acceptable_frames = 0

    def observe(self, value: Optional[float], quality: float, threshold: float) -> None:
        if value is not None and np.isfinite(value):
            self.minimum = min(self.minimum, float(value))
            self.maximum = max(self.maximum, float(value))
        self.observe_quality(quality, threshold)

    def observe_quality(self, quality: float, threshold: float) -> None:
        value = clamp(float(quality))
        self.quality_total += value
        self.quality_samples += 1
        if value >= threshold:
            self.acceptable_frames += 1

    @property
    def average_quality(self) -> float:
        if self.quality_samples == 0:
            return 0.0
        return self.quality_total / self.quality_samples

    @property
    def acceptable_ratio(self) -> float:
        if self.quality_samples == 0:
            return 0.0
        return self.acceptable_frames / self.quality_samples

    @property
    def combined_quality(self) -> float:
        """Human-like rep quality.

        Most weight is assigned to average form across the entire movement, while
        the remaining weight rewards a rep that spends most frames above the
        acceptance line. A brief imperfect frame therefore does not cancel a rep.
        """
        return clamp(0.70 * self.average_quality + 0.30 * self.acceptable_ratio)


class BaseExerciseTracker:
    exercise = "base"

    def __init__(self, quality_threshold: float = 0.60) -> None:
        self.reps = 0
        self.quality_threshold = clamp(float(quality_threshold), 0.45, 0.85)
        # Four stable frames is enough to suppress one-frame pose glitches without
        # forcing a person to freeze unnaturally before every set.
        self.filter = MedianEMAFilter(window=5, alpha=0.46)
        self.pose_stability = StabilityCounter(required_frames=4)
        self.cycle = RepCycle()
        self.last_rep_at = -999.0

    def set_quality_threshold(self, value: float) -> None:
        self.quality_threshold = clamp(float(value), 0.45, 0.85)

    def reset(self) -> None:
        self.reps = 0
        self.filter.reset()
        self.pose_stability.reset()
        self.cycle.reset()
        self.last_rep_at = -999.0

    def invalidate(self, now: float, grace: float = 0.80) -> None:
        # Do not erase a rep because one landmark disappears briefly.
        if self.cycle.invalid_since is None:
            self.cycle.invalid_since = now
        elif now - self.cycle.invalid_since > grace:
            self.cycle.reset(now=now)
            self.pose_stability.reset()

    def validate(self) -> None:
        self.cycle.invalid_since = None

    def best_side(self, pose: PoseFrame, left: tuple[int, ...], right: tuple[int, ...]) -> str:
        return "left" if _mean_visibility(pose, left) >= _mean_visibility(pose, right) else "right"

    def _rep_quality_ok(self) -> tuple[bool, float]:
        quality = self.cycle.combined_quality
        return quality >= self.quality_threshold, quality

    def _quality_feedback(self, label: str, quality: float) -> str:
        percent = round(quality * 100)
        if quality >= 0.82:
            return f"Good {label}"
        return f"Counted {label} - acceptable form ({percent}%)"

    def update(self, pose: PoseFrame) -> TrackerOutput:  # pragma: no cover
        raise NotImplementedError


class PushupTracker(BaseExerciseTracker):
    """Forgiving push-up tracker with a non-negotiable floor-orientation gate.

    It accepts normal human variation and partial range, but standing arm motion
    can never count because the shoulder-to-ankle line must remain horizontal.
    """

    exercise = "pushup"

    def update(self, pose: PoseFrame) -> TrackerOutput:
        now = pose.timestamp
        left = (LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE)
        right = (RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST, RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE)
        side = self.best_side(pose, left, right)
        s, e, w, h, k, a = left if side == "left" else right
        required = (s, e, w, h, k, a)

        lm = pose.image
        world = pose.world or pose.image
        visibility = _mean_visibility(pose, required)
        body_len = max(distance(lm[s], lm[a]), 0.08)
        horizontal_angle = line_angle_to_horizontal(lm[s], lm[a])
        body_angle = angle(world[s], world[h], world[a])
        elbow = self.filter.update((self.exercise, "elbow"), angle(world[s], world[e], world[w]))
        floor_delta = abs(lm[w].y - lm[a].y) / body_len
        shoulder_hip_delta = abs(lm[s].y - lm[h].y) / body_len
        hip_ankle_delta = abs(lm[h].y - lm[a].y) / body_len
        wrist_offset = abs(lm[w].x - lm[s].x) / body_len
        wrist_not_high = 1.0 if lm[w].y >= lm[s].y - 0.10 else 0.0

        visibility_score = _score_high(visibility, 0.30, 0.72)
        horizontal_score = _score_low(horizontal_angle, 18.0, 55.0)
        straight_score = _score_high(body_angle, 118.0, 168.0)
        levels_score = _score_low((shoulder_hip_delta + hip_ankle_delta) / 2.0, 0.16, 0.58)
        support_score = (
            0.45 * _score_low(wrist_offset, 0.30, 0.78)
            + 0.35 * _score_low(floor_delta, 0.28, 0.72)
            + 0.20 * wrist_not_high
        )
        quality = clamp(
            0.14 * visibility_score
            + 0.34 * horizontal_score
            + 0.24 * straight_score
            + 0.10 * levels_score
            + 0.18 * support_score
        )

        # Horizontal posture remains mandatory to prevent the original standing
        # false-positive bug. The remaining form items influence quality rather
        # than blocking every imperfect frame.
        valid = visibility >= 0.36 and horizontal_angle <= 55.0 and elbow is not None
        stable = self.pose_stability.update(valid)
        completed = False
        rom = None
        duration = None
        rep_quality = None
        feedback = "Move into a side-view push-up position"

        if not valid:
            self.invalidate(now)
            if visibility < 0.36:
                feedback = "Move back so one full side of your body is visible"
            elif horizontal_angle > 55.0:
                feedback = "Push-up tracking starts only when your body is horizontal"
        else:
            self.validate()
            assert elbow is not None
            if not stable:
                feedback = "Position found - hold briefly"
            elif self.cycle.phase == "search":
                if elbow >= 132.0:
                    self.cycle.reset("up", now)
                    self.cycle.cycle_started = now
                    self.cycle.observe(elbow, quality, self.quality_threshold)
                    feedback = "Ready - lower your body"
                else:
                    feedback = "Raise toward the top position to begin"
            elif self.cycle.phase == "up":
                self.cycle.observe(elbow, quality, self.quality_threshold)
                if elbow <= 124.0 and now - self.cycle.phase_started >= 0.12:
                    self.cycle.phase = "down"
                    self.cycle.phase_started = now
                    feedback = "Down position detected - press up"
                else:
                    feedback = "Lower with a mostly straight body"
            else:  # down
                self.cycle.observe(elbow, quality, self.quality_threshold)
                cycle_time = now - self.cycle.cycle_started
                candidate_rom = self.cycle.maximum - self.cycle.minimum
                if elbow >= 132.0 and now - self.cycle.phase_started >= 0.12:
                    quality_ok, rep_quality = self._rep_quality_ok()
                    movement_ok = candidate_rom >= 22.0 and 0.30 <= cycle_time <= 12.0
                    cooldown_ok = now - self.last_rep_at >= 0.35
                    if movement_ok and quality_ok and cooldown_ok:
                        self.reps += 1
                        self.last_rep_at = now
                        completed = True
                        rom = candidate_rom
                        duration = cycle_time
                        feedback = self._quality_feedback("push-up", rep_quality)
                    elif not quality_ok:
                        feedback = f"Almost counted: {rep_quality*100:.0f}% quality; need {self.quality_threshold*100:.0f}%"
                    else:
                        feedback = "Almost counted: use a little more up/down movement"
                    self.cycle.reset("up", now)
                    self.cycle.cycle_started = now
                    self.cycle.observe(elbow, quality, self.quality_threshold)
                elif cycle_time > 12.0:
                    self.cycle.reset("search", now)
                    feedback = "Return to the top to restart"

        return TrackerOutput(
            exercise=self.exercise,
            reps=self.reps,
            phase=self.cycle.phase,
            valid_pose=valid,
            confidence=quality,
            form_score=quality * 100.0,
            feedback=feedback,
            metric_name="Elbow",
            metric_value=elbow,
            rep_completed=completed,
            rep_rom=rom,
            rep_duration=duration,
            rep_quality=rep_quality,
            quality_threshold=self.quality_threshold,
            active_landmarks=required,
        )


class SquatTracker(BaseExerciseTracker):
    exercise = "squat"

    def update(self, pose: PoseFrame) -> TrackerOutput:
        now = pose.timestamp
        left = (LEFT_SHOULDER, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE)
        right = (RIGHT_SHOULDER, RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE)
        side = self.best_side(pose, left, right)
        s, h, k, a = left if side == "left" else right
        required = (s, h, k, a)
        lm, world = pose.image, pose.world or pose.image
        visibility = _mean_visibility(pose, required)
        torso_angle = line_angle_to_vertical(lm[s], lm[h])
        knee = self.filter.update((self.exercise, "knee"), angle(world[h], world[k], world[a]))
        hip = self.filter.update((self.exercise, "hip"), angle(world[s], world[h], world[k]))

        visibility_score = _score_high(visibility, 0.30, 0.72)
        torso_score = _score_low(torso_angle, 12.0, 62.0)
        ankle_score = _score_high(lm[a].visibility, 0.25, 0.70)
        quality = clamp(0.50 * visibility_score + 0.35 * torso_score + 0.15 * ankle_score)
        valid = visibility >= 0.36 and torso_angle <= 65.0 and knee is not None and hip is not None
        stable = self.pose_stability.update(valid)

        completed = False
        rom = None
        duration = None
        rep_quality = None
        feedback = "Stand side-on or at 45 degrees"

        if not valid:
            self.invalidate(now)
            feedback = "Keep one shoulder, hip, knee and ankle visible"
        else:
            self.validate()
            assert knee is not None and hip is not None
            if not stable:
                feedback = "Position found - hold briefly"
            elif self.cycle.phase == "search":
                if knee >= 145.0:
                    self.cycle.reset("up", now)
                    self.cycle.cycle_started = now
                    self.cycle.observe(knee, quality, self.quality_threshold)
                    feedback = "Ready - squat down"
                else:
                    feedback = "Stand a little taller to begin"
            elif self.cycle.phase == "up":
                self.cycle.observe(knee, quality, self.quality_threshold)
                if knee <= 126.0 and hip <= 168.0 and now - self.cycle.phase_started >= 0.14:
                    self.cycle.phase = "down"
                    self.cycle.phase_started = now
                    feedback = "Depth detected - stand up"
                else:
                    feedback = "Sit your hips back"
            else:
                self.cycle.observe(knee, quality, self.quality_threshold)
                cycle_time = now - self.cycle.cycle_started
                candidate_rom = self.cycle.maximum - self.cycle.minimum
                if knee >= 145.0 and now - self.cycle.phase_started >= 0.14:
                    quality_ok, rep_quality = self._rep_quality_ok()
                    movement_ok = candidate_rom >= 25.0 and 0.35 <= cycle_time <= 14.0
                    cooldown_ok = now - self.last_rep_at >= 0.38
                    if movement_ok and quality_ok and cooldown_ok:
                        self.reps += 1
                        self.last_rep_at = now
                        completed = True
                        rom = candidate_rom
                        duration = cycle_time
                        feedback = self._quality_feedback("squat", rep_quality)
                    elif not quality_ok:
                        feedback = f"Almost counted: {rep_quality*100:.0f}% quality; need {self.quality_threshold*100:.0f}%"
                    else:
                        feedback = "Almost counted: bend and straighten a little more"
                    self.cycle.reset("up", now)
                    self.cycle.cycle_started = now
                    self.cycle.observe(knee, quality, self.quality_threshold)
                elif cycle_time > 14.0:
                    self.cycle.reset("search", now)
                    feedback = "Stand tall to restart"

        return TrackerOutput(
            exercise=self.exercise,
            reps=self.reps,
            phase=self.cycle.phase,
            valid_pose=valid,
            confidence=quality,
            form_score=quality * 100.0,
            feedback=feedback,
            metric_name="Knee",
            metric_value=knee,
            rep_completed=completed,
            rep_rom=rom,
            rep_duration=duration,
            rep_quality=rep_quality,
            quality_threshold=self.quality_threshold,
            active_landmarks=required,
        )


class CurlTracker(BaseExerciseTracker):
    exercise = "curl"

    def update(self, pose: PoseFrame) -> TrackerOutput:
        now = pose.timestamp
        left = (LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST, LEFT_HIP)
        right = (RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST, RIGHT_HIP)
        side = self.best_side(pose, left, right)
        s, e, w, h = left if side == "left" else right
        required = (s, e, w, h)
        lm, world = pose.image, pose.world or pose.image
        visibility = _mean_visibility(pose, required)
        torso_angle = line_angle_to_vertical(lm[s], lm[h])
        elbow = self.filter.update((self.exercise, "elbow"), angle(world[s], world[e], world[w]))
        upper_arm = max(distance(lm[s], lm[e]), 0.03)
        elbow_drift = abs(lm[e].x - lm[s].x) / upper_arm
        wrist_height_norm = (lm[s].y - lm[w].y) / upper_arm
        overhead_penalty = clamp((wrist_height_norm - 0.35) / 0.65)

        visibility_score = _score_high(visibility, 0.28, 0.70)
        upright_score = _score_low(torso_angle, 12.0, 65.0)
        drift_score = _score_low(elbow_drift, 0.30, 1.35)
        hand_zone_score = clamp(1.0 - overhead_penalty)
        quality = clamp(
            0.42 * visibility_score
            + 0.22 * upright_score
            + 0.24 * drift_score
            + 0.12 * hand_zone_score
        )
        # A biceps curl may bring the hand near the shoulder, but it should not
        # travel distinctly overhead. This hard gate prevents shoulder presses
        # from being counted as curls.
        valid = (
            visibility >= 0.34
            and torso_angle <= 68.0
            and elbow is not None
            and wrist_height_norm <= 0.72
        )
        stable = self.pose_stability.update(valid)

        completed = False
        rom = None
        duration = None
        rep_quality = None
        feedback = "Keep your working arm visible"

        if not valid:
            self.invalidate(now, grace=0.10 if wrist_height_norm > 0.72 else 0.80)
            if wrist_height_norm > 0.72:
                feedback = "Hand is overhead - use shoulder press mode"
            else:
                feedback = "Show one full arm from shoulder to wrist"
        else:
            self.validate()
            assert elbow is not None
            if not stable:
                feedback = "Position found - hold briefly"
            elif self.cycle.phase == "search":
                if elbow >= 130.0:
                    self.cycle.reset("extended", now)
                    self.cycle.cycle_started = now
                    self.cycle.observe(elbow, quality, self.quality_threshold)
                    feedback = "Ready - curl upward"
                else:
                    feedback = "Lower your forearm to begin"
            elif self.cycle.phase == "extended":
                self.cycle.observe(elbow, quality, self.quality_threshold)
                if elbow <= 96.0 and now - self.cycle.phase_started >= 0.12:
                    self.cycle.phase = "contracted"
                    self.cycle.phase_started = now
                    feedback = "Curl detected - lower the arm"
                else:
                    feedback = "Curl your forearm upward"
            else:
                self.cycle.observe(elbow, quality, self.quality_threshold)
                candidate_rom = self.cycle.maximum - self.cycle.minimum
                cycle_time = now - self.cycle.cycle_started
                if elbow >= 130.0 and now - self.cycle.phase_started >= 0.12:
                    quality_ok, rep_quality = self._rep_quality_ok()
                    movement_ok = candidate_rom >= 34.0 and 0.30 <= cycle_time <= 12.0
                    cooldown_ok = now - self.last_rep_at >= 0.35
                    if movement_ok and quality_ok and cooldown_ok:
                        self.reps += 1
                        self.last_rep_at = now
                        completed = True
                        rom = candidate_rom
                        duration = cycle_time
                        feedback = self._quality_feedback("curl", rep_quality)
                    elif not quality_ok:
                        feedback = f"Almost counted: {rep_quality*100:.0f}% quality; need {self.quality_threshold*100:.0f}%"
                    else:
                        feedback = "Almost counted: move the forearm a little farther"
                    self.cycle.reset("extended", now)
                    self.cycle.cycle_started = now
                    self.cycle.observe(elbow, quality, self.quality_threshold)

        return TrackerOutput(
            exercise=self.exercise,
            reps=self.reps,
            phase=self.cycle.phase,
            valid_pose=valid,
            confidence=quality,
            form_score=quality * 100.0,
            feedback=feedback,
            metric_name="Elbow",
            metric_value=elbow,
            rep_completed=completed,
            rep_rom=rom,
            rep_duration=duration,
            rep_quality=rep_quality,
            quality_threshold=self.quality_threshold,
            active_landmarks=required,
        )


class ShoulderPressTracker(BaseExerciseTracker):
    exercise = "shoulder_press"

    def update(self, pose: PoseFrame) -> TrackerOutput:
        now = pose.timestamp
        lm, world = pose.image, pose.world or pose.image
        arm_indexes = (
            (LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST),
            (RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST),
        )
        arms: list[dict[str, float | tuple[int, int, int]]] = []
        for s, e, w in arm_indexes:
            arm_visibility = float(min(lm[s].visibility, lm[e].visibility, lm[w].visibility))
            elbow_angle = angle(world[s], world[e], world[w])
            if arm_visibility >= 0.26 and np.isfinite(elbow_angle):
                arms.append(
                    {
                        "indexes": (s, e, w),
                        "visibility": arm_visibility,
                        "elbow": elbow_angle,
                        "wrist_height": lm[s].y - lm[w].y,
                        "wrist_height_norm": (lm[s].y - lm[w].y) / max(distance(lm[s], lm[e]), 0.03),
                    }
                )

        shoulder_mid = midpoint(lm[LEFT_SHOULDER], lm[RIGHT_SHOULDER])
        hips_visible = min(lm[LEFT_HIP].visibility, lm[RIGHT_HIP].visibility) >= 0.28
        shoulders_visible = min(lm[LEFT_SHOULDER].visibility, lm[RIGHT_SHOULDER].visibility) >= 0.28
        if hips_visible and shoulders_visible:
            torso_angle = line_angle_to_vertical(shoulder_mid, midpoint(lm[LEFT_HIP], lm[RIGHT_HIP]))
            orientation_available = True
        elif shoulders_visible and lm[NOSE].visibility >= 0.28:
            torso_angle = line_angle_to_vertical(lm[NOSE], shoulder_mid)
            orientation_available = True
        else:
            torso_angle = 28.0
            orientation_available = False

        arm_visibility = robust_mean([float(item["visibility"]) for item in arms]) or 0.0
        elbow_raw = robust_mean([float(item["elbow"]) for item in arms])
        elbow = self.filter.update((self.exercise, "elbow"), elbow_raw)
        wrist_height = robust_mean([float(item["wrist_height"]) for item in arms]) or 0.0
        wrist_height_norm = robust_mean([float(item["wrist_height_norm"]) for item in arms]) or -2.0
        visible_arm_count = len(arms)

        # Down means the hand is at/below shoulder level. Up requires a clear
        # overhead crossing, not merely a bent elbow. This is the key separation
        # from biceps curls.
        down_flags = [
            float(item["wrist_height_norm"]) <= 0.30 and float(item["elbow"]) <= 152.0
            for item in arms
        ]
        up_flags = [
            float(item["wrist_height_norm"]) >= 0.72 and float(item["elbow"]) >= 124.0
            for item in arms
        ]
        down_ratio = float(np.mean(down_flags)) if down_flags else 0.0
        up_ratio = float(np.mean(up_flags)) if up_flags else 0.0

        visibility_score = _score_high(arm_visibility, 0.24, 0.70)
        upright_score = _score_low(torso_angle, 10.0, 62.0) if orientation_available else 0.68
        arm_count_score = 1.0 if visible_arm_count >= 2 else (0.78 if visible_arm_count == 1 else 0.0)
        overhead_readiness = clamp((wrist_height_norm + 0.25) / 1.25)
        quality = clamp(
            0.45 * visibility_score
            + 0.23 * upright_score
            + 0.14 * arm_count_score
            + 0.18 * overhead_readiness
        )
        valid = visible_arm_count >= 1 and elbow is not None and torso_angle <= 68.0
        stable = self.pose_stability.update(valid)

        # Include both angle and wrist travel in the movement metric. This makes
        # seated presses and one-arm presses count even when elbow-angle change is
        # modest but the hand clearly travels overhead.
        movement_metric = None if elbow is None else elbow + 42.0 * clamp(wrist_height_norm + 0.35, 0.0, 2.4)
        active = tuple(index for item in arms for index in item["indexes"]) if arms else (
            LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_ELBOW, RIGHT_ELBOW, LEFT_WRIST, RIGHT_WRIST
        )

        completed = False
        rom = None
        duration = None
        rep_quality = None
        feedback = "Show at least one complete arm"

        if not valid:
            self.invalidate(now)
            feedback = "Keep at least one shoulder, elbow and wrist in view"
        else:
            self.validate()
            assert elbow is not None and movement_metric is not None
            if not stable:
                feedback = "Arm detected - hold briefly"
            elif self.cycle.phase == "search":
                if down_ratio >= 0.60:
                    self.cycle.reset("down", now)
                    self.cycle.cycle_started = now
                    self.cycle.observe(movement_metric, quality, self.quality_threshold)
                    feedback = "Ready - press overhead"
                else:
                    feedback = "Bring your hand near shoulder level to begin"
            elif self.cycle.phase == "down":
                self.cycle.observe(movement_metric, quality, self.quality_threshold)
                if up_ratio >= 0.60 and now - self.cycle.phase_started >= 0.12:
                    self.cycle.phase = "up"
                    self.cycle.phase_started = now
                    feedback = "Top detected - lower the hand"
                else:
                    feedback = "Press upward"
            else:
                self.cycle.observe(movement_metric, quality, self.quality_threshold)
                candidate_rom = self.cycle.maximum - self.cycle.minimum
                cycle_time = now - self.cycle.cycle_started
                if down_ratio >= 0.60 and now - self.cycle.phase_started >= 0.12:
                    quality_ok, rep_quality = self._rep_quality_ok()
                    movement_ok = candidate_rom >= 16.0 and 0.30 <= cycle_time <= 15.0
                    cooldown_ok = now - self.last_rep_at >= 0.35
                    if movement_ok and quality_ok and cooldown_ok:
                        self.reps += 1
                        self.last_rep_at = now
                        completed = True
                        rom = candidate_rom
                        duration = cycle_time
                        feedback = self._quality_feedback("shoulder press", rep_quality)
                    elif not quality_ok:
                        feedback = f"Almost counted: {rep_quality*100:.0f}% quality; need {self.quality_threshold*100:.0f}%"
                    else:
                        feedback = "Almost counted: raise and lower the hand a little farther"
                    self.cycle.reset("down", now)
                    self.cycle.cycle_started = now
                    self.cycle.observe(movement_metric, quality, self.quality_threshold)

        return TrackerOutput(
            exercise=self.exercise,
            reps=self.reps,
            phase=self.cycle.phase,
            valid_pose=valid,
            confidence=quality,
            form_score=quality * 100.0,
            feedback=feedback,
            metric_name="Elbow avg",
            metric_value=elbow,
            rep_completed=completed,
            rep_rom=rom,
            rep_duration=duration,
            rep_quality=rep_quality,
            quality_threshold=self.quality_threshold,
            active_landmarks=active,
        )


class JumpingJackTracker(BaseExerciseTracker):
    exercise = "jumping_jack"

    def update(self, pose: PoseFrame) -> TrackerOutput:
        now = pose.timestamp
        lm = pose.image
        base_required = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_ANKLE, RIGHT_ANKLE, LEFT_HIP, RIGHT_HIP)
        base_visibility = _mean_visibility(pose, base_required)
        visible_wrists = [
            (LEFT_WRIST, LEFT_SHOULDER, LEFT_HIP),
            (RIGHT_WRIST, RIGHT_SHOULDER, RIGHT_HIP),
        ]
        visible_wrists = [item for item in visible_wrists if lm[item[0]].visibility >= 0.28]
        wrist_visibility = robust_mean([lm[w].visibility for w, _, _ in visible_wrists]) or 0.0
        visibility = 0.72 * base_visibility + 0.28 * wrist_visibility

        shoulder_mid = midpoint(lm[LEFT_SHOULDER], lm[RIGHT_SHOULDER])
        hip_mid = midpoint(lm[LEFT_HIP], lm[RIGHT_HIP])
        torso_angle = line_angle_to_vertical(shoulder_mid, hip_mid)
        shoulder_width = max(distance(lm[LEFT_SHOULDER], lm[RIGHT_SHOULDER]), 0.04)
        ankle_ratio = distance(lm[LEFT_ANKLE], lm[RIGHT_ANKLE]) / shoulder_width

        arm_open_ratio = float(np.mean([
            lm[w].y <= lm[s].y + 0.04 for w, s, _ in visible_wrists
        ])) if visible_wrists else 0.0
        arm_closed_ratio = float(np.mean([
            lm[w].y >= lm[h].y - 0.14 for w, _, h in visible_wrists
        ])) if visible_wrists else 0.0
        legs_open = 1.0 if ankle_ratio >= 1.40 else 0.0
        legs_closed = 1.0 if ankle_ratio <= 1.25 else 0.0
        open_score = 0.55 * arm_open_ratio + 0.45 * legs_open
        closed_score = 0.55 * arm_closed_ratio + 0.45 * legs_closed

        visibility_score = _score_high(visibility, 0.28, 0.70)
        upright_score = _score_low(torso_angle, 10.0, 58.0)
        quality = clamp(0.60 * visibility_score + 0.40 * upright_score)
        valid = base_visibility >= 0.34 and len(visible_wrists) >= 1 and torso_angle <= 65.0
        stable = self.pose_stability.update(valid)

        completed = False
        duration = None
        rep_quality = None
        feedback = "Face the camera and show hands and feet"

        if not valid:
            self.invalidate(now)
        else:
            self.validate()
            if not stable:
                feedback = "Position found - hold briefly"
            elif self.cycle.phase == "search":
                if closed_score >= 0.60:
                    self.cycle.reset("closed", now)
                    self.cycle.cycle_started = now
                    self.cycle.observe_quality(quality, self.quality_threshold)
                    feedback = "Ready - open arms and legs"
                else:
                    feedback = "Start with feet closer and arm down"
            elif self.cycle.phase == "closed":
                self.cycle.observe_quality(quality, self.quality_threshold)
                if open_score >= 0.60 and now - self.cycle.phase_started >= 0.10:
                    self.cycle.phase = "open"
                    self.cycle.phase_started = now
                    feedback = "Open detected - return to start"
                else:
                    feedback = "Open arms and legs together"
            else:
                self.cycle.observe_quality(quality, self.quality_threshold)
                cycle_time = now - self.cycle.cycle_started
                if closed_score >= 0.60 and now - self.cycle.phase_started >= 0.10:
                    quality_ok, rep_quality = self._rep_quality_ok()
                    movement_ok = 0.25 <= cycle_time <= 8.0
                    cooldown_ok = now - self.last_rep_at >= 0.25
                    if movement_ok and quality_ok and cooldown_ok:
                        self.reps += 1
                        self.last_rep_at = now
                        completed = True
                        duration = cycle_time
                        feedback = self._quality_feedback("jumping jack", rep_quality)
                    elif not quality_ok:
                        feedback = f"Almost counted: {rep_quality*100:.0f}% quality; need {self.quality_threshold*100:.0f}%"
                    self.cycle.reset("closed", now)
                    self.cycle.cycle_started = now
                    self.cycle.observe_quality(quality, self.quality_threshold)

        active = base_required + tuple(w for w, _, _ in visible_wrists)
        return TrackerOutput(
            exercise=self.exercise,
            reps=self.reps,
            phase=self.cycle.phase,
            valid_pose=valid,
            confidence=quality,
            form_score=quality * 100.0,
            feedback=feedback,
            metric_name="Leg width",
            metric_value=ankle_ratio,
            rep_completed=completed,
            rep_duration=duration,
            rep_quality=rep_quality,
            quality_threshold=self.quality_threshold,
            active_landmarks=active,
        )



class LungeTracker(BaseExerciseTracker):
    """Counts one completed down-and-up lunge as one repetition."""

    exercise = "lunge"

    def update(self, pose: PoseFrame) -> TrackerOutput:
        now = pose.timestamp
        lm, world = pose.image, pose.world or pose.image
        required = (
            LEFT_HIP, RIGHT_HIP, LEFT_KNEE, RIGHT_KNEE,
            LEFT_ANKLE, RIGHT_ANKLE, LEFT_SHOULDER, RIGHT_SHOULDER,
        )
        visibility = _mean_visibility(pose, required)
        shoulder_mid = midpoint(lm[LEFT_SHOULDER], lm[RIGHT_SHOULDER])
        hip_mid = midpoint(lm[LEFT_HIP], lm[RIGHT_HIP])
        torso_angle = line_angle_to_vertical(shoulder_mid, hip_mid)
        left_knee = self.filter.update((self.exercise, "left_knee"), angle(world[LEFT_HIP], world[LEFT_KNEE], world[LEFT_ANKLE]))
        right_knee = self.filter.update((self.exercise, "right_knee"), angle(world[RIGHT_HIP], world[RIGHT_KNEE], world[RIGHT_ANKLE]))
        usable = [v for v in (left_knee, right_knee) if v is not None and np.isfinite(v)]
        min_knee = min(usable) if usable else None
        max_knee = max(usable) if usable else None
        asymmetry = (max_knee - min_knee) if min_knee is not None and max_knee is not None else 0.0

        visibility_score = _score_high(visibility, 0.28, 0.72)
        upright_score = _score_low(torso_angle, 10.0, 62.0)
        asymmetry_score = _score_high(asymmetry, 8.0, 46.0)
        quality = clamp(0.48 * visibility_score + 0.34 * upright_score + 0.18 * asymmetry_score)
        valid = visibility >= 0.34 and torso_angle <= 68.0 and min_knee is not None and max_knee is not None
        stable = self.pose_stability.update(valid)

        completed = False
        rom = None
        duration = None
        rep_quality = None
        feedback = "Face forward or 45 degrees and keep both legs visible"
        movement_metric = min_knee

        if not valid:
            self.invalidate(now)
            feedback = "Keep shoulders, hips, knees and ankles visible"
        else:
            self.validate()
            assert min_knee is not None and max_knee is not None
            both_tall = min_knee >= 143.0
            lunge_down = min_knee <= 122.0 and asymmetry >= 12.0
            if not stable:
                feedback = "Position found - hold briefly"
            elif self.cycle.phase == "search":
                if both_tall:
                    self.cycle.reset("up", now)
                    self.cycle.cycle_started = now
                    self.cycle.observe(min_knee, quality, self.quality_threshold)
                    feedback = "Ready - step and lower"
                else:
                    feedback = "Stand tall to begin"
            elif self.cycle.phase == "up":
                self.cycle.observe(min_knee, quality, self.quality_threshold)
                if lunge_down and now - self.cycle.phase_started >= 0.14:
                    self.cycle.phase = "down"
                    self.cycle.phase_started = now
                    feedback = "Lunge depth detected - rise"
                else:
                    feedback = "Lower one knee while keeping torso upright"
            else:
                self.cycle.observe(min_knee, quality, self.quality_threshold)
                cycle_time = now - self.cycle.cycle_started
                candidate_rom = self.cycle.maximum - self.cycle.minimum
                if both_tall and now - self.cycle.phase_started >= 0.14:
                    quality_ok, rep_quality = self._rep_quality_ok()
                    movement_ok = candidate_rom >= 22.0 and 0.38 <= cycle_time <= 15.0
                    cooldown_ok = now - self.last_rep_at >= 0.40
                    if movement_ok and quality_ok and cooldown_ok:
                        self.reps += 1
                        self.last_rep_at = now
                        completed = True
                        rom = candidate_rom
                        duration = cycle_time
                        feedback = self._quality_feedback("lunge", rep_quality)
                    elif not quality_ok:
                        feedback = f"Almost counted: {rep_quality*100:.0f}% quality; need {self.quality_threshold*100:.0f}%"
                    else:
                        feedback = "Almost counted: lower and rise a little farther"
                    self.cycle.reset("up", now)
                    self.cycle.cycle_started = now
                    self.cycle.observe(min_knee, quality, self.quality_threshold)

        return TrackerOutput(
            exercise=self.exercise,
            reps=self.reps,
            phase=self.cycle.phase,
            valid_pose=valid,
            confidence=quality,
            form_score=quality * 100.0,
            feedback=feedback,
            metric_name="Front knee",
            metric_value=movement_metric,
            rep_completed=completed,
            rep_rom=rom,
            rep_duration=duration,
            rep_quality=rep_quality,
            quality_threshold=self.quality_threshold,
            active_landmarks=required,
        )


class LateralRaiseTracker(BaseExerciseTracker):
    exercise = "lateral_raise"

    def update(self, pose: PoseFrame) -> TrackerOutput:
        now = pose.timestamp
        lm, world = pose.image, pose.world or pose.image
        arms = []
        for s, e, w, h in (
            (LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST, LEFT_HIP),
            (RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST, RIGHT_HIP),
        ):
            visibility = _mean_visibility(pose, (s, e, w))
            elbow = angle(world[s], world[e], world[w])
            if visibility >= 0.25 and np.isfinite(elbow):
                upper = max(distance(lm[s], lm[e]), 0.03)
                arms.append({
                    "indexes": (s, e, w),
                    "visibility": visibility,
                    "elbow": elbow,
                    "height": (lm[s].y - lm[w].y) / upper,
                    "side": abs(lm[w].x - lm[s].x) / upper,
                    "down": (lm[h].y - lm[w].y) / upper,
                })

        shoulder_mid = midpoint(lm[LEFT_SHOULDER], lm[RIGHT_SHOULDER])
        hip_mid = midpoint(lm[LEFT_HIP], lm[RIGHT_HIP])
        torso_angle = line_angle_to_vertical(shoulder_mid, hip_mid)
        arm_visibility = robust_mean([item["visibility"] for item in arms]) or 0.0
        elbow = self.filter.update((self.exercise, "elbow"), robust_mean([item["elbow"] for item in arms]))
        height = robust_mean([item["height"] for item in arms])
        side_ratio = robust_mean([item["side"] for item in arms]) or 0.0
        down_ratio = float(np.mean([
            item["height"] <= -0.35 and item["elbow"] >= 125.0 for item in arms
        ])) if arms else 0.0
        top_ratio = float(np.mean([
            -0.22 <= item["height"] <= 0.30 and item["side"] >= 0.78 and item["elbow"] >= 125.0
            for item in arms
        ])) if arms else 0.0

        visibility_score = _score_high(arm_visibility, 0.24, 0.70)
        upright_score = _score_low(torso_angle, 10.0, 62.0)
        extension_score = _score_high(elbow or 0.0, 108.0, 158.0)
        quality = clamp(0.46 * visibility_score + 0.30 * upright_score + 0.24 * extension_score)
        valid = len(arms) >= 1 and elbow is not None and height is not None and torso_angle <= 68.0
        stable = self.pose_stability.update(valid)
        movement_metric = None if height is None else height * 100.0 + side_ratio * 35.0
        active = tuple(index for arm in arms for index in arm["indexes"])

        completed = False
        rom = None
        duration = None
        rep_quality = None
        feedback = "Show at least one full arm and your torso"

        if not valid:
            self.invalidate(now)
        else:
            self.validate()
            assert movement_metric is not None
            if not stable:
                feedback = "Arm detected - hold briefly"
            elif self.cycle.phase == "search":
                if down_ratio >= 0.60:
                    self.cycle.reset("down", now)
                    self.cycle.cycle_started = now
                    self.cycle.observe(movement_metric, quality, self.quality_threshold)
                    feedback = "Ready - raise arm to shoulder height"
                else:
                    feedback = "Lower your arms beside your body to begin"
            elif self.cycle.phase == "down":
                self.cycle.observe(movement_metric, quality, self.quality_threshold)
                if top_ratio >= 0.60 and now - self.cycle.phase_started >= 0.12:
                    self.cycle.phase = "top"
                    self.cycle.phase_started = now
                    feedback = "Shoulder height detected - lower slowly"
                else:
                    feedback = "Raise sideways with mostly straight elbows"
            else:
                self.cycle.observe(movement_metric, quality, self.quality_threshold)
                cycle_time = now - self.cycle.cycle_started
                candidate_rom = self.cycle.maximum - self.cycle.minimum
                if down_ratio >= 0.60 and now - self.cycle.phase_started >= 0.12:
                    quality_ok, rep_quality = self._rep_quality_ok()
                    movement_ok = candidate_rom >= 38.0 and 0.35 <= cycle_time <= 14.0
                    cooldown_ok = now - self.last_rep_at >= 0.38
                    if movement_ok and quality_ok and cooldown_ok:
                        self.reps += 1
                        self.last_rep_at = now
                        completed = True
                        rom = candidate_rom
                        duration = cycle_time
                        feedback = self._quality_feedback("lateral raise", rep_quality)
                    elif not quality_ok:
                        feedback = f"Almost counted: {rep_quality*100:.0f}% quality; need {self.quality_threshold*100:.0f}%"
                    else:
                        feedback = "Almost counted: raise and lower a little farther"
                    self.cycle.reset("down", now)
                    self.cycle.cycle_started = now
                    self.cycle.observe(movement_metric, quality, self.quality_threshold)

        return TrackerOutput(
            exercise=self.exercise,
            reps=self.reps,
            phase=self.cycle.phase,
            valid_pose=valid,
            confidence=quality,
            form_score=quality * 100.0,
            feedback=feedback,
            metric_name="Arm height",
            metric_value=movement_metric,
            rep_completed=completed,
            rep_rom=rom,
            rep_duration=duration,
            rep_quality=rep_quality,
            quality_threshold=self.quality_threshold,
            active_landmarks=active,
        )


class HighKneeTracker(BaseExerciseTracker):
    """Counts each completed left or right knee lift as one repetition."""

    exercise = "high_knee"

    def __init__(self, quality_threshold: float = 0.60) -> None:
        super().__init__(quality_threshold)
        self.lifted_side: str | None = None
        self.peak_lift = 0.0

    def reset(self) -> None:
        super().reset()
        self.lifted_side = None
        self.peak_lift = 0.0

    def update(self, pose: PoseFrame) -> TrackerOutput:
        now = pose.timestamp
        lm = pose.image
        required = (
            LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP,
            LEFT_KNEE, RIGHT_KNEE, LEFT_ANKLE, RIGHT_ANKLE,
        )
        visibility = _mean_visibility(pose, required)
        shoulder_mid = midpoint(lm[LEFT_SHOULDER], lm[RIGHT_SHOULDER])
        hip_mid = midpoint(lm[LEFT_HIP], lm[RIGHT_HIP])
        torso_angle = line_angle_to_vertical(shoulder_mid, hip_mid)
        torso_len = max(distance(shoulder_mid, hip_mid), 0.08)
        left_lift = (lm[LEFT_HIP].y - lm[LEFT_KNEE].y) / torso_len
        right_lift = (lm[RIGHT_HIP].y - lm[RIGHT_KNEE].y) / torso_len
        max_lift = max(left_lift, right_lift)
        active_side = "left" if left_lift >= right_lift else "right"
        neutral = left_lift <= 0.02 and right_lift <= 0.02

        visibility_score = _score_high(visibility, 0.28, 0.72)
        upright_score = _score_low(torso_angle, 10.0, 58.0)
        lift_score = _score_high(max_lift, 0.04, 0.48)
        quality = clamp(0.48 * visibility_score + 0.34 * upright_score + 0.18 * lift_score)
        valid = visibility >= 0.34 and torso_angle <= 65.0
        stable = self.pose_stability.update(valid)

        completed = False
        rom = None
        duration = None
        rep_quality = None
        feedback = "Face the camera and keep hips, knees and ankles visible"

        if not valid:
            self.invalidate(now)
            self.lifted_side = None
            self.peak_lift = 0.0
        else:
            self.validate()
            if not stable:
                feedback = "Position found - hold briefly"
            elif self.cycle.phase == "search":
                if neutral:
                    self.cycle.reset("neutral", now)
                    self.cycle.cycle_started = now
                    self.cycle.observe(max_lift, quality, self.quality_threshold)
                    feedback = "Ready - lift either knee"
                else:
                    feedback = "Lower both feet to begin"
            elif self.cycle.phase == "neutral":
                self.cycle.observe(max_lift, quality, self.quality_threshold)
                if max_lift >= 0.22 and now - self.cycle.phase_started >= 0.08:
                    self.cycle.phase = "lifted"
                    self.cycle.phase_started = now
                    self.lifted_side = active_side
                    self.peak_lift = max_lift
                    feedback = f"{active_side.title()} knee detected - lower it"
                else:
                    feedback = "Lift one knee toward hip height"
            else:
                self.cycle.observe(max_lift, quality, self.quality_threshold)
                self.peak_lift = max(self.peak_lift, max_lift)
                cycle_time = now - self.cycle.cycle_started
                if neutral and now - self.cycle.phase_started >= 0.08:
                    quality_ok, rep_quality = self._rep_quality_ok()
                    movement_ok = self.peak_lift >= 0.22 and 0.18 <= cycle_time <= 5.0
                    cooldown_ok = now - self.last_rep_at >= 0.18
                    if movement_ok and quality_ok and cooldown_ok:
                        self.reps += 1
                        self.last_rep_at = now
                        completed = True
                        rom = self.peak_lift * 100.0
                        duration = cycle_time
                        feedback = self._quality_feedback("high knee", rep_quality)
                    elif not quality_ok:
                        feedback = f"Almost counted: {rep_quality*100:.0f}% quality; need {self.quality_threshold*100:.0f}%"
                    self.cycle.reset("neutral", now)
                    self.cycle.cycle_started = now
                    self.cycle.observe(max_lift, quality, self.quality_threshold)
                    self.lifted_side = None
                    self.peak_lift = 0.0

        return TrackerOutput(
            exercise=self.exercise,
            reps=self.reps,
            phase=self.cycle.phase,
            valid_pose=valid,
            confidence=quality,
            form_score=quality * 100.0,
            feedback=feedback,
            metric_name="Knee lift",
            metric_value=max_lift * 100.0,
            rep_completed=completed,
            rep_rom=rom,
            rep_duration=duration,
            rep_quality=rep_quality,
            quality_threshold=self.quality_threshold,
            active_landmarks=required,
        )


class SitupTracker(BaseExerciseTracker):
    exercise = "situp"

    def update(self, pose: PoseFrame) -> TrackerOutput:
        now = pose.timestamp
        left = (LEFT_SHOULDER, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE)
        right = (RIGHT_SHOULDER, RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE)
        side = self.best_side(pose, left, right)
        s, h, k, a = left if side == "left" else right
        required = (s, h, k, a)
        lm, world = pose.image, pose.world or pose.image
        visibility = _mean_visibility(pose, required)
        torso_to_horizontal = line_angle_to_horizontal(lm[s], lm[h])
        knee = self.filter.update((self.exercise, "knee"), angle(world[h], world[k], world[a]))
        hip = self.filter.update((self.exercise, "hip"), angle(world[s], world[h], world[k]))
        floor_posture = line_angle_to_horizontal(lm[h], lm[a])

        visibility_score = _score_high(visibility, 0.28, 0.72)
        bent_knee_score = _score_low(knee or 180.0, 95.0, 168.0)
        floor_score = _score_low(floor_posture, 18.0, 68.0)
        quality = clamp(0.48 * visibility_score + 0.26 * bent_knee_score + 0.26 * floor_score)
        valid = visibility >= 0.34 and knee is not None and hip is not None and floor_posture <= 72.0
        stable = self.pose_stability.update(valid)
        movement_metric = torso_to_horizontal + 0.25 * (180.0 - hip)

        completed = False
        rom = None
        duration = None
        rep_quality = None
        feedback = "Use a side view with shoulder, hip, knee and ankle visible"

        if not valid:
            self.invalidate(now)
        else:
            self.validate()
            lying = torso_to_horizontal <= 42.0
            raised = torso_to_horizontal >= 52.0 or hip <= 112.0
            if not stable:
                feedback = "Position found - hold briefly"
            elif self.cycle.phase == "search":
                if lying:
                    self.cycle.reset("down", now)
                    self.cycle.cycle_started = now
                    self.cycle.observe(movement_metric, quality, self.quality_threshold)
                    feedback = "Ready - raise your torso"
                else:
                    feedback = "Lie back to the starting position"
            elif self.cycle.phase == "down":
                self.cycle.observe(movement_metric, quality, self.quality_threshold)
                if raised and now - self.cycle.phase_started >= 0.14:
                    self.cycle.phase = "up"
                    self.cycle.phase_started = now
                    feedback = "Top detected - lower with control"
                else:
                    feedback = "Raise shoulders toward your knees"
            else:
                self.cycle.observe(movement_metric, quality, self.quality_threshold)
                candidate_rom = self.cycle.maximum - self.cycle.minimum
                cycle_time = now - self.cycle.cycle_started
                if lying and now - self.cycle.phase_started >= 0.14:
                    quality_ok, rep_quality = self._rep_quality_ok()
                    movement_ok = candidate_rom >= 18.0 and 0.45 <= cycle_time <= 15.0
                    cooldown_ok = now - self.last_rep_at >= 0.42
                    if movement_ok and quality_ok and cooldown_ok:
                        self.reps += 1
                        self.last_rep_at = now
                        completed = True
                        rom = candidate_rom
                        duration = cycle_time
                        feedback = self._quality_feedback("sit-up", rep_quality)
                    elif not quality_ok:
                        feedback = f"Almost counted: {rep_quality*100:.0f}% quality; need {self.quality_threshold*100:.0f}%"
                    else:
                        feedback = "Almost counted: raise and lower a little farther"
                    self.cycle.reset("down", now)
                    self.cycle.cycle_started = now
                    self.cycle.observe(movement_metric, quality, self.quality_threshold)

        return TrackerOutput(
            exercise=self.exercise,
            reps=self.reps,
            phase=self.cycle.phase,
            valid_pose=valid,
            confidence=quality,
            form_score=quality * 100.0,
            feedback=feedback,
            metric_name="Torso",
            metric_value=torso_to_horizontal,
            rep_completed=completed,
            rep_rom=rom,
            rep_duration=duration,
            rep_quality=rep_quality,
            quality_threshold=self.quality_threshold,
            active_landmarks=required,
        )



class TimedHoldTracker(BaseExerciseTracker):
    """Base class for static exercises measured in whole seconds.

    A pose must remain valid for a few consecutive frames. Whole seconds are
    emitted as value increments so database history remains compact even when a
    long hold is recorded.
    """

    unit = "seconds"

    def __init__(self, quality_threshold: float = 0.60) -> None:
        super().__init__(quality_threshold)
        self.hold_started: Optional[float] = None
        self.segment_emitted = 0
        self.invalid_started: Optional[float] = None
        # Timed holds should enter seconds mode quickly without requiring a
        # person to freeze perfectly for several frames.
        self.pose_stability = StabilityCounter(required_frames=2)

    def reset(self) -> None:
        super().reset()
        self.hold_started = None
        self.segment_emitted = 0
        self.invalid_started = None

    def hold_output(
        self,
        pose: PoseFrame,
        *,
        valid: bool,
        confidence: float,
        quality: float,
        feedback: str,
        metric_name: str,
        metric_value: Optional[float],
        active_landmarks: tuple[int, ...],
    ) -> TrackerOutput:
        now = pose.timestamp
        # Static poses use a slightly forgiving gate. Tolerance still affects
        # coaching quality, but a normal human hold is not rejected for one
        # imperfect joint.
        hold_gate = max(0.34, self.quality_threshold * 0.68)
        stable = self.pose_stability.update(valid and quality >= hold_gate)
        increment = 0
        live_elapsed = float(self.reps)

        if stable:
            self.invalid_started = None
            if self.hold_started is None:
                self.hold_started = now
                self.segment_emitted = 0
            live_elapsed = max(0.0, now - self.hold_started)
            elapsed = max(0, int(live_elapsed))
            if elapsed > self.segment_emitted:
                increment = elapsed - self.segment_emitted
                self.segment_emitted = elapsed
                self.reps += increment
            phase = "holding"
            display_feedback = feedback if increment == 0 else f"Held {self.reps} seconds"
        else:
            if self.invalid_started is None:
                self.invalid_started = now
            elif now - self.invalid_started > 0.85:
                self.hold_started = None
                self.segment_emitted = 0
                self.pose_stability.reset()
            phase = "position"
            display_feedback = feedback

        return TrackerOutput(
            exercise=self.exercise,
            reps=self.reps,
            phase=phase,
            valid_pose=bool(valid),
            confidence=clamp(confidence),
            form_score=clamp(quality) * 100.0,
            feedback=display_feedback,
            metric_name=metric_name,
            metric_value=metric_value,
            rep_completed=increment > 0,
            rep_rom=None,
            rep_duration=float(increment) if increment else None,
            rep_quality=clamp(quality),
            quality_threshold=self.quality_threshold,
            active_landmarks=active_landmarks,
            value_increment=increment if increment > 0 else 1,
            unit="seconds",
            live_value=live_elapsed,
        )


class PlankTracker(TimedHoldTracker):
    exercise = "plank"

    def update(self, pose: PoseFrame) -> TrackerOutput:
        left = (LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE)
        right = (RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST, RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE)
        side = self.best_side(pose, left, right)
        s, e, w, h, k, a = left if side == "left" else right
        lm = pose.image
        world = pose.world or pose.image
        visibility = _mean_visibility(pose, (s, e, w, h, k, a))
        horizontal = line_angle_to_horizontal(lm[s], lm[a])
        body_angle = angle(world[s], world[h], world[a])
        body_len = max(distance(lm[s], lm[a]), 0.08)
        support_level = min(abs(lm[w].y - lm[a].y), abs(lm[e].y - lm[a].y)) / body_len

        visibility_score = _score_high(visibility, 0.28, 0.72)
        horizontal_score = _score_low(horizontal, 15.0, 52.0)
        straight_score = _score_high(body_angle, 120.0, 170.0)
        support_score = _score_low(support_level, 0.20, 0.80)
        quality = 0.24 * visibility_score + 0.34 * horizontal_score + 0.30 * straight_score + 0.12 * support_score
        valid = visibility >= 0.22 and horizontal <= 62.0 and body_angle >= 105.0 and support_level <= 1.05
        if not valid:
            feedback = "Turn side-on and keep shoulders, hips and feet in one line"
        elif body_angle < 150.0:
            feedback = "Lift or lower your hips into a straighter plank"
        else:
            feedback = "Hold the plank steadily"
        return self.hold_output(
            pose,
            valid=valid,
            confidence=quality,
            quality=quality,
            feedback=feedback,
            metric_name="Body line",
            metric_value=body_angle,
            active_landmarks=(s, e, w, h, k, a),
        )


class SquatHoldTracker(TimedHoldTracker):
    exercise = "squat_hold"

    def update(self, pose: PoseFrame) -> TrackerOutput:
        left = (LEFT_SHOULDER, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE)
        right = (RIGHT_SHOULDER, RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE)
        side = self.best_side(pose, left, right)
        s, h, k, a = left if side == "left" else right
        lm = pose.image
        world = pose.world or pose.image
        visibility = _mean_visibility(pose, (s, h, k, a))
        knee = angle(world[h], world[k], world[a])
        torso_vertical = line_angle_to_vertical(lm[s], lm[h])
        bend_score = 1.0 - min(1.0, abs(knee - 95.0) / 55.0) if np.isfinite(knee) else 0.0
        visibility_score = _score_high(visibility, 0.28, 0.72)
        vertical_score = _score_low(torso_vertical, 12.0, 55.0)
        quality = 0.28 * visibility_score + 0.45 * bend_score + 0.27 * vertical_score
        valid = visibility >= 0.22 and 55.0 <= knee <= 150.0 and torso_vertical <= 68.0
        if not valid:
            feedback = "Lower into a squat and hold with your side visible"
        elif knee > 118.0:
            feedback = "Sit slightly lower for a stronger squat hold"
        else:
            feedback = "Hold the squat position steadily"
        return self.hold_output(
            pose,
            valid=valid,
            confidence=quality,
            quality=quality,
            feedback=feedback,
            metric_name="Knee angle",
            metric_value=knee,
            active_landmarks=(s, h, k, a),
        )


class OverheadStretchTracker(TimedHoldTracker):
    exercise = "overhead_stretch"

    def update(self, pose: PoseFrame) -> TrackerOutput:
        lm = pose.image
        world = pose.world or pose.image
        arms = []
        for s, e, w in (
            (LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST),
            (RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST),
        ):
            vis = _mean_visibility(pose, (s, e, w))
            if vis >= 0.25:
                elbow = angle(world[s], world[e], world[w])
                above = (lm[s].y - lm[w].y) / max(distance(lm[LEFT_SHOULDER], lm[RIGHT_SHOULDER]), 0.05)
                arms.append((s, e, w, vis, elbow, above))
        shoulder_mid = midpoint(lm[LEFT_SHOULDER], lm[RIGHT_SHOULDER])
        hip_mid = midpoint(lm[LEFT_HIP], lm[RIGHT_HIP])
        torso_vertical = line_angle_to_vertical(shoulder_mid, hip_mid)
        if arms:
            visibility = max(item[3] for item in arms)
            elbow = robust_mean([item[4] for item in arms]) or 0.0
            above = max(item[5] for item in arms)
        else:
            visibility, elbow, above = 0.0, 0.0, 0.0
        visibility_score = _score_high(visibility, 0.25, 0.70)
        extension_score = _score_high(elbow, 120.0, 168.0)
        above_score = _score_high(above, 0.18, 1.15)
        vertical_score = _score_low(torso_vertical, 10.0, 52.0)
        quality = 0.20 * visibility_score + 0.30 * extension_score + 0.32 * above_score + 0.18 * vertical_score
        valid = bool(arms) and visibility >= 0.25 and elbow >= 118.0 and above >= 0.15 and torso_vertical <= 58.0
        active = tuple(index for item in arms for index in item[:3])
        feedback = "Reach upward and hold" if valid else "Stand tall and extend at least one arm overhead"
        return self.hold_output(
            pose,
            valid=valid,
            confidence=quality,
            quality=quality,
            feedback=feedback,
            metric_name="Elbow angle",
            metric_value=elbow,
            active_landmarks=active,
        )


class ForwardFoldTracker(TimedHoldTracker):
    exercise = "forward_fold"

    def update(self, pose: PoseFrame) -> TrackerOutput:
        left = (LEFT_SHOULDER, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE)
        right = (RIGHT_SHOULDER, RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE)
        side = self.best_side(pose, left, right)
        s, h, k, a = left if side == "left" else right
        lm = pose.image
        world = pose.world or pose.image
        visibility = _mean_visibility(pose, (s, h, k, a))
        torso_horizontal = line_angle_to_horizontal(lm[s], lm[h])
        hip_angle = angle(world[s], world[h], world[k])
        knee = angle(world[h], world[k], world[a])
        fold_score = _score_low(torso_horizontal, 12.0, 62.0)
        hip_score = _score_low(hip_angle, 55.0, 150.0)
        knee_score = _score_high(knee, 125.0, 172.0)
        visibility_score = _score_high(visibility, 0.28, 0.72)
        quality = 0.25 * visibility_score + 0.32 * fold_score + 0.28 * hip_score + 0.15 * knee_score
        valid = visibility >= 0.28 and torso_horizontal <= 62.0 and hip_angle <= 148.0 and knee >= 118.0
        feedback = "Relax into the forward fold and hold" if valid else "Hinge at the hips with legs mostly straight"
        return self.hold_output(
            pose,
            valid=valid,
            confidence=quality,
            quality=quality,
            feedback=feedback,
            metric_name="Hip angle",
            metric_value=hip_angle,
            active_landmarks=(s, h, k, a),
        )



class TaekwondoKickTracker(BaseExerciseTracker):
    """Count either-leg high kicks after the foot returns to the floor.

    The high-position gate deliberately requires the ankle to approach or rise
    above shoulder level and the knee to be substantially extended. This keeps
    ordinary high-knee marching from being counted as a kick.
    """

    exercise = "taekwondo_kick"

    def __init__(self, quality_threshold: float = 0.60) -> None:
        super().__init__(quality_threshold)
        self.phase = "ready"
        self.active_side: str | None = None
        self.high_started = 0.0
        self.best_quality = 0.0
        self.best_height = -999.0

    def reset(self) -> None:
        super().reset()
        self.phase = "ready"
        self.active_side = None
        self.high_started = 0.0
        self.best_quality = 0.0
        self.best_height = -999.0

    def update(self, pose: PoseFrame) -> TrackerOutput:
        now = pose.timestamp
        lm = pose.image
        world = pose.world or pose.image
        shoulder_mid = midpoint(lm[LEFT_SHOULDER], lm[RIGHT_SHOULDER])
        hip_mid = midpoint(lm[LEFT_HIP], lm[RIGHT_HIP])
        shoulder_width = max(distance(lm[LEFT_SHOULDER], lm[RIGHT_SHOULDER]), 0.05)
        torso_length = max(distance(shoulder_mid, hip_mid), shoulder_width * 0.85, 0.08)
        torso_vertical = line_angle_to_vertical(shoulder_mid, hip_mid)

        candidates = []
        for side, h, k, a in (
            ("left", LEFT_HIP, LEFT_KNEE, LEFT_ANKLE),
            ("right", RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE),
        ):
            visibility = _mean_visibility(pose, (h, k, a, LEFT_SHOULDER, RIGHT_SHOULDER))
            knee_angle = angle(world[h], world[k], world[a])
            height_ratio = (shoulder_mid.y - lm[a].y) / torso_length
            foot_return = lm[a].y >= hip_mid.y + 0.42 * torso_length
            high = (
                visibility >= 0.30
                and torso_vertical <= 48.0
                and height_ratio >= -0.08
                and knee_angle >= 112.0
            )
            candidates.append((side, h, k, a, visibility, knee_angle, height_ratio, foot_return, high))

        best = max(candidates, key=lambda item: item[6])
        side, h, k, a, visibility, knee_angle, height_ratio, foot_return, high = best
        visibility_score = _score_high(visibility, 0.28, 0.76)
        vertical_score = _score_low(torso_vertical, 12.0, 52.0)
        height_score = _score_high(height_ratio, -0.18, 0.28)
        extension_score = _score_high(knee_angle, 105.0, 168.0)
        quality = 0.20 * visibility_score + 0.18 * vertical_score + 0.38 * height_score + 0.24 * extension_score

        completed = False
        rep_quality = None
        duration = None
        feedback = "Stand upright and return both feet to the floor"

        if self.phase == "ready":
            if high and now - self.last_rep_at >= 0.45:
                self.phase = "extended"
                self.active_side = side
                self.high_started = now
                self.best_quality = quality
                self.best_height = height_ratio
            elif height_ratio > -0.35:
                feedback = "Lift and extend either leg higher"
        else:
            locked = next(item for item in candidates if item[0] == self.active_side)
            _, lh, lk, la, lvis, lknee, lheight, lreturn, lhigh = locked
            lvisibility_score = _score_high(lvis, 0.28, 0.76)
            lheight_score = _score_high(lheight, -0.18, 0.28)
            lextension_score = _score_high(lknee, 105.0, 168.0)
            locked_quality = 0.20 * lvisibility_score + 0.18 * vertical_score + 0.38 * lheight_score + 0.24 * lextension_score
            self.best_quality = max(self.best_quality, locked_quality)
            self.best_height = max(self.best_height, lheight)
            duration_now = now - self.high_started
            if lreturn and duration_now >= 0.16:
                quality_ok = self.best_quality >= max(0.48, self.quality_threshold * 0.78)
                height_ok = self.best_height >= -0.08
                if quality_ok and height_ok and duration_now <= 3.2:
                    self.reps += 1
                    self.last_rep_at = now
                    completed = True
                    rep_quality = self.best_quality
                    duration = duration_now
                    feedback = f"Counted {self.active_side} kick"
                else:
                    feedback = "Kick was not high or extended enough"
                self.phase = "ready"
                self.active_side = None
            elif duration_now > 3.2:
                self.phase = "ready"
                self.active_side = None
                feedback = "Reset and try one controlled kick"
            else:
                feedback = f"Retract the {self.active_side} leg and return the foot"

        active = (LEFT_SHOULDER, RIGHT_SHOULDER, h, k, a)
        return TrackerOutput(
            exercise=self.exercise,
            reps=self.reps,
            phase=self.phase,
            valid_pose=bool(visibility >= 0.28 and torso_vertical <= 55.0),
            confidence=clamp(quality),
            form_score=clamp(quality) * 100.0,
            feedback=feedback,
            metric_name="Kick height",
            metric_value=height_ratio * 100.0,
            rep_completed=completed,
            rep_rom=self.best_height * 100.0 if completed else None,
            rep_duration=duration,
            rep_quality=rep_quality,
            quality_threshold=self.quality_threshold,
            active_landmarks=active,
            direction=side,
        )


class HeadTurnTracker(BaseExerciseTracker):
    """Count comfortable left/right head turns followed by a return to centre."""

    exercise = "head_turn"

    def __init__(self, quality_threshold: float = 0.60) -> None:
        super().__init__(quality_threshold)
        self.phase = "centre"
        self.turn_side: str | None = None
        self.turn_started = 0.0
        self.max_yaw = 0.0
        self.center_frames = 0

    def reset(self) -> None:
        super().reset()
        self.phase = "centre"
        self.turn_side = None
        self.turn_started = 0.0
        self.max_yaw = 0.0
        self.center_frames = 0

    def update(self, pose: PoseFrame) -> TrackerOutput:
        now = pose.timestamp
        lm = pose.image
        required = (NOSE, LEFT_EAR, RIGHT_EAR, LEFT_SHOULDER, RIGHT_SHOULDER)
        visibility = _mean_visibility(pose, required)
        ear_mid = midpoint(lm[LEFT_EAR], lm[RIGHT_EAR])
        shoulder_mid = midpoint(lm[LEFT_SHOULDER], lm[RIGHT_SHOULDER])
        ear_width = max(distance(lm[LEFT_EAR], lm[RIGHT_EAR]), 0.035)
        shoulder_width = max(distance(lm[LEFT_SHOULDER], lm[RIGHT_SHOULDER]), 0.06)
        yaw_ratio = (lm[NOSE].x - ear_mid.x) / ear_width
        shoulder_tilt = abs(lm[LEFT_SHOULDER].y - lm[RIGHT_SHOULDER].y) / shoulder_width
        centred = abs(yaw_ratio) <= 0.22
        turned = abs(yaw_ratio) >= 0.48
        side = "right" if yaw_ratio > 0 else "left"

        visibility_score = _score_high(visibility, 0.30, 0.78)
        turn_score = _score_high(abs(yaw_ratio), 0.20, 0.78)
        stable_shoulders = _score_low(shoulder_tilt, 0.05, 0.38)
        quality = 0.36 * visibility_score + 0.44 * turn_score + 0.20 * stable_shoulders
        completed = False
        duration = None
        rep_quality = None

        if self.phase == "centre":
            centre_ready = self.center_frames >= 2
            if centred:
                self.center_frames += 1
            elif not turned:
                self.center_frames = 0
            if turned and centre_ready and now - self.last_rep_at >= 0.30:
                self.phase = "turned"
                self.turn_side = side
                self.turn_started = now
                self.max_yaw = abs(yaw_ratio)
                feedback = f"Return from the {side} turn to centre"
            else:
                feedback = "Turn your head left or right, then return to centre"
        else:
            self.max_yaw = max(self.max_yaw, abs(yaw_ratio))
            duration_now = now - self.turn_started
            if centred and duration_now >= 0.18:
                rep_quality = clamp(0.55 * _score_high(self.max_yaw, 0.38, 0.80) + 0.45 * visibility_score)
                if rep_quality >= max(0.46, self.quality_threshold * 0.76):
                    self.reps += 1
                    self.last_rep_at = now
                    completed = True
                    duration = duration_now
                    feedback = f"Counted {self.turn_side} head turn"
                else:
                    feedback = "Turn a little farther, without forcing the neck"
                self.phase = "centre"
                self.center_frames = 1
                self.turn_side = None
            elif duration_now > 3.5:
                self.phase = "centre"
                self.center_frames = 0
                self.turn_side = None
                feedback = "Return to centre and restart gently"
            else:
                feedback = f"Return from the {self.turn_side} turn to centre"

        return TrackerOutput(
            exercise=self.exercise,
            reps=self.reps,
            phase=self.phase,
            valid_pose=visibility >= 0.30,
            confidence=clamp(quality),
            form_score=clamp(quality) * 100.0,
            feedback=feedback,
            metric_name="Head yaw",
            metric_value=yaw_ratio * 55.0,
            rep_completed=completed,
            rep_duration=duration,
            rep_quality=rep_quality,
            quality_threshold=self.quality_threshold,
            active_landmarks=required,
            direction=side if turned else (self.turn_side or ""),
        )


def _wrapped_delta(current: float, previous: float) -> float:
    return (current - previous + 180.0) % 360.0 - 180.0


class ArmCircleTracker(BaseExerciseTracker):
    """Count large arm circles in either direction using wrist angle around shoulder."""

    exercise = "arm_circle"

    def __init__(self, quality_threshold: float = 0.60) -> None:
        super().__init__(quality_threshold)
        self.locked_side: str | None = None
        self.last_angle: float | None = None
        self.accumulated = 0.0
        self.started = 0.0
        self.direction_sign = 0
        self.good_frames = 0

    def reset_motion(self) -> None:
        self.locked_side = None
        self.last_angle = None
        self.accumulated = 0.0
        self.started = 0.0
        self.direction_sign = 0
        self.good_frames = 0

    def reset(self) -> None:
        super().reset()
        self.reset_motion()

    def update(self, pose: PoseFrame) -> TrackerOutput:
        now = pose.timestamp
        lm = pose.image
        world = pose.world or pose.image
        shoulder_width = max(distance(lm[LEFT_SHOULDER], lm[RIGHT_SHOULDER]), 0.06)
        shoulder_mid = midpoint(lm[LEFT_SHOULDER], lm[RIGHT_SHOULDER])
        hip_mid = midpoint(lm[LEFT_HIP], lm[RIGHT_HIP])
        torso_vertical = line_angle_to_vertical(shoulder_mid, hip_mid)

        options = []
        for side, s, e, w in (
            ("left", LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST),
            ("right", RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST),
        ):
            visibility = _mean_visibility(pose, (s, e, w, LEFT_HIP, RIGHT_HIP))
            radius = distance(lm[s], lm[w]) / shoulder_width
            elbow_angle = angle(world[s], world[e], world[w])
            theta = math.degrees(math.atan2(-(lm[w].y - lm[s].y), lm[w].x - lm[s].x))
            score = visibility + 0.25 * radius
            options.append((score, side, s, e, w, visibility, radius, elbow_angle, theta))

        if self.locked_side:
            selected = next(item for item in options if item[1] == self.locked_side)
        else:
            selected = max(options, key=lambda item: item[0])
        _, side, s, e, w, visibility, radius, elbow_angle, theta = selected

        visible = visibility >= 0.28
        large = radius >= 0.55
        extended = elbow_angle >= 108.0
        upright = torso_vertical <= 52.0
        valid = visible and large and extended and upright
        quality = (
            0.22 * _score_high(visibility, 0.28, 0.78)
            + 0.28 * _score_high(radius, 0.40, 1.25)
            + 0.26 * _score_high(elbow_angle, 100.0, 170.0)
            + 0.24 * _score_low(torso_vertical, 10.0, 58.0)
        )

        completed = False
        duration = None
        rep_quality = None
        direction = ""
        feedback = "Extend one arm and draw a large circle"

        if valid:
            if self.locked_side is None:
                self.locked_side = side
                self.last_angle = theta
                self.started = now
            elif self.last_angle is not None:
                delta = _wrapped_delta(theta, self.last_angle)
                self.last_angle = theta
                if abs(delta) <= 58.0 and abs(delta) >= 0.6:
                    sign = 1 if delta > 0 else -1
                    if self.direction_sign == 0:
                        self.direction_sign = sign
                    if sign == self.direction_sign:
                        self.accumulated += delta
                        self.good_frames += 1
                    else:
                        self.accumulated *= 0.82
                direction = "counter-clockwise" if self.direction_sign > 0 else "clockwise"
                feedback = f"Keep circling {direction}; {abs(self.accumulated):.0f}°"
            if abs(self.accumulated) >= 300.0 and now - self.started >= 0.55:
                rep_quality = clamp(0.55 * quality + 0.45 * min(1.0, abs(self.accumulated) / 360.0))
                if rep_quality >= max(0.46, self.quality_threshold * 0.76):
                    self.reps += 1
                    self.last_rep_at = now
                    completed = True
                    duration = now - self.started
                    feedback = f"Counted {direction} arm circle"
                self.accumulated -= math.copysign(360.0, self.accumulated)
                self.started = now
                self.good_frames = 0
        else:
            if self.locked_side is not None and now - self.started > 0.45:
                self.reset_motion()

        return TrackerOutput(
            exercise=self.exercise,
            reps=self.reps,
            phase="circling" if self.locked_side else "ready",
            valid_pose=valid,
            confidence=clamp(quality),
            form_score=clamp(quality) * 100.0,
            feedback=feedback,
            metric_name="Circle progress",
            metric_value=abs(self.accumulated),
            rep_completed=completed,
            rep_rom=360.0 if completed else None,
            rep_duration=duration,
            rep_quality=rep_quality,
            quality_threshold=self.quality_threshold,
            active_landmarks=(s, e, w, LEFT_SHOULDER, RIGHT_SHOULDER),
            direction=direction,
        )


class HipCircleTracker(BaseExerciseTracker):
    """Count pelvis circles relative to the shoulder centre in a front view."""

    exercise = "hip_circle"

    def __init__(self, quality_threshold: float = 0.60) -> None:
        super().__init__(quality_threshold)
        self.baseline_x: float | None = None
        self.baseline_y: float | None = None
        self.last_angle: float | None = None
        self.accumulated = 0.0
        self.started = 0.0
        self.direction_sign = 0
        self.motion_started = False

    def reset_motion(self) -> None:
        self.last_angle = None
        self.accumulated = 0.0
        self.started = 0.0
        self.direction_sign = 0
        self.motion_started = False

    def reset(self) -> None:
        super().reset()
        self.baseline_x = None
        self.baseline_y = None
        self.reset_motion()

    def update(self, pose: PoseFrame) -> TrackerOutput:
        now = pose.timestamp
        lm = pose.image
        world = pose.world or pose.image
        shoulder_mid = midpoint(lm[LEFT_SHOULDER], lm[RIGHT_SHOULDER])
        hip_mid = midpoint(lm[LEFT_HIP], lm[RIGHT_HIP])
        shoulder_width = max(distance(lm[LEFT_SHOULDER], lm[RIGHT_SHOULDER]), 0.06)
        visibility = _mean_visibility(
            pose,
            (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP, LEFT_KNEE, RIGHT_KNEE),
        )
        left_knee = angle(world[LEFT_HIP], world[LEFT_KNEE], world[LEFT_ANKLE])
        right_knee = angle(world[RIGHT_HIP], world[RIGHT_KNEE], world[RIGHT_ANKLE])
        knee_mean = robust_mean((left_knee, right_knee)) or 180.0

        rel_x = (hip_mid.x - shoulder_mid.x) / shoulder_width
        rel_y = (hip_mid.y - shoulder_mid.y) / shoulder_width
        if self.baseline_x is None:
            self.baseline_x, self.baseline_y = rel_x, rel_y

        dx = rel_x - float(self.baseline_x)
        dy = rel_y - float(self.baseline_y)
        radius = math.hypot(dx, dy)
        theta = math.degrees(math.atan2(-dy, dx))
        knees_stable = knee_mean >= 145.0
        visible = visibility >= 0.32
        valid = visible and knees_stable

        # Slowly follow the neutral standing position only before a circle begins.
        if not self.motion_started and radius < 0.10:
            self.baseline_x = 0.94 * float(self.baseline_x) + 0.06 * rel_x
            self.baseline_y = 0.94 * float(self.baseline_y) + 0.06 * rel_y
            dx = rel_x - float(self.baseline_x)
            dy = rel_y - float(self.baseline_y)
            radius = math.hypot(dx, dy)

        quality = (
            0.32 * _score_high(visibility, 0.30, 0.78)
            + 0.38 * _score_high(radius, 0.07, 0.26)
            + 0.30 * _score_high(knee_mean, 132.0, 175.0)
        )
        completed = False
        duration = None
        rep_quality = None
        direction = ""
        feedback = "Keep feet planted and move the hips in a smooth circle"

        if valid and radius >= 0.10:
            if not self.motion_started:
                self.motion_started = True
                self.last_angle = theta
                self.started = now
            elif self.last_angle is not None:
                delta = _wrapped_delta(theta, self.last_angle)
                self.last_angle = theta
                if abs(delta) <= 62.0 and abs(delta) >= 0.5:
                    sign = 1 if delta > 0 else -1
                    if self.direction_sign == 0:
                        self.direction_sign = sign
                    if sign == self.direction_sign:
                        self.accumulated += delta
                    else:
                        self.accumulated *= 0.80
                direction = "counter-clockwise" if self.direction_sign > 0 else "clockwise"
                feedback = f"Continue the {direction} hip circle; {abs(self.accumulated):.0f}°"
            if abs(self.accumulated) >= 285.0 and now - self.started >= 0.75:
                rep_quality = clamp(0.52 * quality + 0.48 * min(1.0, abs(self.accumulated) / 360.0))
                if rep_quality >= max(0.44, self.quality_threshold * 0.74):
                    self.reps += 1
                    self.last_rep_at = now
                    completed = True
                    duration = now - self.started
                    feedback = f"Counted {direction} hip circle"
                self.accumulated -= math.copysign(360.0, self.accumulated)
                self.started = now
        elif self.motion_started and now - self.started > 0.55:
            self.reset_motion()

        return TrackerOutput(
            exercise=self.exercise,
            reps=self.reps,
            phase="circling" if self.motion_started else "ready",
            valid_pose=valid,
            confidence=clamp(quality),
            form_score=clamp(quality) * 100.0,
            feedback=feedback,
            metric_name="Circle progress",
            metric_value=abs(self.accumulated),
            rep_completed=completed,
            rep_rom=360.0 if completed else None,
            rep_duration=duration,
            rep_quality=rep_quality,
            quality_threshold=self.quality_threshold,
            active_landmarks=(LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP),
            direction=direction,
        )


def create_trackers(
    quality_threshold: float = 0.60,
    enabled_exercises: tuple[str, ...] | list[str] | None = None,
) -> dict[str, BaseExerciseTracker]:
    all_trackers: dict[str, BaseExerciseTracker] = {
        "pushup": PushupTracker(quality_threshold),
        "squat": SquatTracker(quality_threshold),
        "curl": CurlTracker(quality_threshold),
        "shoulder_press": ShoulderPressTracker(quality_threshold),
        "jumping_jack": JumpingJackTracker(quality_threshold),
        "lunge": LungeTracker(quality_threshold),
        "lateral_raise": LateralRaiseTracker(quality_threshold),
        "high_knee": HighKneeTracker(quality_threshold),
        "situp": SitupTracker(quality_threshold),
        "taekwondo_kick": TaekwondoKickTracker(quality_threshold),
        "head_turn": HeadTurnTracker(quality_threshold),
        "arm_circle": ArmCircleTracker(quality_threshold),
        "hip_circle": HipCircleTracker(quality_threshold),
        "plank": PlankTracker(quality_threshold),
        "squat_hold": SquatHoldTracker(quality_threshold),
        "overhead_stretch": OverheadStretchTracker(quality_threshold),
        "forward_fold": ForwardFoldTracker(quality_threshold),
    }
    if enabled_exercises is None:
        return all_trackers
    enabled = set(enabled_exercises)
    return {name: tracker for name, tracker in all_trackers.items() if name in enabled}
