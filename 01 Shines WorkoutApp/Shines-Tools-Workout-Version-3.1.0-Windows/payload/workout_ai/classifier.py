from __future__ import annotations

from collections import deque
from dataclasses import dataclass

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


@dataclass
class Classification:
    exercise: str | None
    confidence: float
    scores: dict[str, float]
    stable: bool
    candidate: str | None = None
    margin: float = 0.0


class ExerciseClassifier:
    """Fast temporal exercise recognition.

    All exercise-specific trackers run from the first frame and remain the final
    source of truth. This classifier supplies routing evidence and now reaches a
    stable candidate after a short five-frame warm-up rather than waiting long
    enough to lose several repetitions.
    """

    def __init__(
        self,
        window: int = 24,
        lock_frames: int = 2,
        enabled_exercises: tuple[str, ...] | list[str] | set[str] | None = None,
    ):
        self.window = deque(maxlen=max(12, int(window)))
        self.lock_frames = max(1, int(lock_frames))
        self.enabled_exercises = tuple(enabled_exercises or ())
        self._candidate: str | None = None
        self._candidate_frames = 0

    def set_enabled_exercises(self, exercises) -> None:
        self.enabled_exercises = tuple(exercises or ())
        if self._candidate not in self.enabled_exercises:
            self._candidate = None
            self._candidate_frames = 0

    def reset(self) -> None:
        self.window.clear()
        self._candidate = None
        self._candidate_frames = 0

    @staticmethod
    def _visibility(lm, indexes: tuple[int, ...]) -> float:
        return float(np.mean([lm[i].visibility for i in indexes]))

    @staticmethod
    def _finite(value: float | None, fallback: float) -> float:
        if value is None or not np.isfinite(value):
            return fallback
        return float(value)

    def update(self, pose: PoseFrame) -> Classification:
        lm, world = pose.image, pose.world or pose.image
        shoulder_mid = midpoint(lm[LEFT_SHOULDER], lm[RIGHT_SHOULDER])
        hip_mid = midpoint(lm[LEFT_HIP], lm[RIGHT_HIP])
        ankle_mid = midpoint(lm[LEFT_ANKLE], lm[RIGHT_ANKLE])

        body_horizontal = line_angle_to_horizontal(shoulder_mid, ankle_mid)
        torso_vertical = line_angle_to_vertical(shoulder_mid, hip_mid)
        torso_horizontal = line_angle_to_horizontal(shoulder_mid, hip_mid)

        left_knee = self._finite(angle(world[LEFT_HIP], world[LEFT_KNEE], world[LEFT_ANKLE]), 180.0)
        right_knee = self._finite(angle(world[RIGHT_HIP], world[RIGHT_KNEE], world[RIGHT_ANKLE]), 180.0)
        left_elbow = self._finite(angle(world[LEFT_SHOULDER], world[LEFT_ELBOW], world[LEFT_WRIST]), 180.0)
        right_elbow = self._finite(angle(world[RIGHT_SHOULDER], world[RIGHT_ELBOW], world[RIGHT_WRIST]), 180.0)
        left_hip_angle = self._finite(angle(world[LEFT_SHOULDER], world[LEFT_HIP], world[LEFT_KNEE]), 180.0)
        right_hip_angle = self._finite(angle(world[RIGHT_SHOULDER], world[RIGHT_HIP], world[RIGHT_KNEE]), 180.0)
        left_body_angle = self._finite(angle(world[LEFT_SHOULDER], world[LEFT_HIP], world[LEFT_ANKLE]), 180.0)
        right_body_angle = self._finite(angle(world[RIGHT_SHOULDER], world[RIGHT_HIP], world[RIGHT_ANKLE]), 180.0)

        knee = robust_mean((left_knee, right_knee)) or 180.0
        elbow = robust_mean((left_elbow, right_elbow)) or 180.0
        hip_angle = robust_mean((left_hip_angle, right_hip_angle)) or 180.0
        body_angle = robust_mean((left_body_angle, right_body_angle)) or 180.0

        shoulder_width = max(distance(lm[LEFT_SHOULDER], lm[RIGHT_SHOULDER]), 0.04)
        ankle_ratio = distance(lm[LEFT_ANKLE], lm[RIGHT_ANKLE]) / shoulder_width
        wrist_span = distance(lm[LEFT_WRIST], lm[RIGHT_WRIST]) / shoulder_width

        # Require the complete arm to be visible. A mean visibility score can
        # incorrectly treat one visible shoulder plus an occluded elbow/wrist as
        # a usable arm and average contradictory motion into the classifier.
        arm_visibility_left = float(min(
            lm[LEFT_SHOULDER].visibility,
            lm[LEFT_ELBOW].visibility,
            lm[LEFT_WRIST].visibility,
        ))
        arm_visibility_right = float(min(
            lm[RIGHT_SHOULDER].visibility,
            lm[RIGHT_ELBOW].visibility,
            lm[RIGHT_WRIST].visibility,
        ))
        visible_arms = []
        for s, e, w, vis, e_angle in (
            (LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST, arm_visibility_left, left_elbow),
            (RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST, arm_visibility_right, right_elbow),
        ):
            if vis >= 0.24:
                visible_arms.append((s, e, w, vis, e_angle))

        wrist_above = float(np.mean([lm[w].y <= lm[s].y + 0.03 for s, _, w, _, _ in visible_arms])) if visible_arms else 0.0
        wrist_above_distance = float(np.mean([(lm[s].y - lm[w].y) / shoulder_width for s, _, w, _, _ in visible_arms])) if visible_arms else 0.0
        wrist_near_shoulder = float(np.mean([abs(lm[w].y - lm[s].y) <= 0.25 for s, _, w, _, _ in visible_arms])) if visible_arms else 0.0
        wrist_below_hip = float(np.mean([lm[w].y >= lm[LEFT_HIP if s == LEFT_SHOULDER else RIGHT_HIP].y - 0.08 for s, _, w, _, _ in visible_arms])) if visible_arms else 0.0
        elbow_extended_ratio = float(np.mean([e_angle >= 138.0 for _, _, _, _, e_angle in visible_arms])) if visible_arms else 0.0

        left_knee_lift = lm[LEFT_HIP].y - lm[LEFT_KNEE].y
        right_knee_lift = lm[RIGHT_HIP].y - lm[RIGHT_KNEE].y
        knee_lift = max(left_knee_lift, right_knee_lift)
        knee_lift_asymmetry = abs(left_knee_lift - right_knee_lift)
        knee_angle_asymmetry = abs(left_knee - right_knee)

        torso_length = max(distance(shoulder_mid, hip_mid), shoulder_width * 0.85, 0.08)
        left_kick_height = (shoulder_mid.y - lm[LEFT_ANKLE].y) / torso_length
        right_kick_height = (shoulder_mid.y - lm[RIGHT_ANKLE].y) / torso_length
        kick_height = max(left_kick_height, right_kick_height)
        kick_extension = max(left_knee, right_knee) / 180.0

        ear_mid = midpoint(lm[LEFT_EAR], lm[RIGHT_EAR])
        ear_width = max(distance(lm[LEFT_EAR], lm[RIGHT_EAR]), 0.035)
        head_yaw = (lm[NOSE].x - ear_mid.x) / ear_width

        left_wrist_rel_x = (lm[LEFT_WRIST].x - lm[LEFT_SHOULDER].x) / shoulder_width
        left_wrist_rel_y = (lm[LEFT_WRIST].y - lm[LEFT_SHOULDER].y) / shoulder_width
        right_wrist_rel_x = (lm[RIGHT_WRIST].x - lm[RIGHT_SHOULDER].x) / shoulder_width
        right_wrist_rel_y = (lm[RIGHT_WRIST].y - lm[RIGHT_SHOULDER].y) / shoulder_width

        hip_rel_x = (hip_mid.x - shoulder_mid.x) / shoulder_width
        hip_rel_y = (hip_mid.y - shoulder_mid.y) / shoulder_width

        visible_wrist_heights = [
            (lm[s].y - lm[w].y) / shoulder_width for s, _, w, _, _ in visible_arms
        ]
        wrist_height_norm = float(np.mean(visible_wrist_heights)) if visible_wrist_heights else -2.0
        visible_elbow_heights = [
            (lm[s].y - lm[e].y) / shoulder_width for s, e, _, _, _ in visible_arms
        ]
        elbow_height_norm = float(np.mean(visible_elbow_heights)) if visible_elbow_heights else -2.0
        visible_elbow_side_drift = [
            abs(lm[e].x - lm[s].x) / shoulder_width for s, e, _, _, _ in visible_arms
        ]
        elbow_side_drift = float(np.mean(visible_elbow_side_drift)) if visible_elbow_side_drift else 3.0

        visibility = {
            "pushup": max(
                self._visibility(lm, (LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST, LEFT_HIP, LEFT_ANKLE)),
                self._visibility(lm, (RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST, RIGHT_HIP, RIGHT_ANKLE)),
            ),
            "squat": max(
                self._visibility(lm, (LEFT_SHOULDER, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE)),
                self._visibility(lm, (RIGHT_SHOULDER, RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE)),
            ),
            "curl": max(arm_visibility_left, arm_visibility_right),
            "shoulder_press": max(arm_visibility_left, arm_visibility_right),
            "jumping_jack": self._visibility(lm, (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP, LEFT_ANKLE, RIGHT_ANKLE)),
            "lunge": self._visibility(lm, (LEFT_HIP, RIGHT_HIP, LEFT_KNEE, RIGHT_KNEE, LEFT_ANKLE, RIGHT_ANKLE)),
            "lateral_raise": max(arm_visibility_left, arm_visibility_right),
            "high_knee": self._visibility(lm, (LEFT_HIP, RIGHT_HIP, LEFT_KNEE, RIGHT_KNEE, LEFT_ANKLE, RIGHT_ANKLE)),
            "situp": max(
                self._visibility(lm, (LEFT_SHOULDER, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE)),
                self._visibility(lm, (RIGHT_SHOULDER, RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE)),
            ),
            "plank": max(
                self._visibility(lm, (LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST, LEFT_HIP, LEFT_ANKLE)),
                self._visibility(lm, (RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST, RIGHT_HIP, RIGHT_ANKLE)),
            ),
            "squat_hold": max(
                self._visibility(lm, (LEFT_SHOULDER, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE)),
                self._visibility(lm, (RIGHT_SHOULDER, RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE)),
            ),
            "overhead_stretch": max(arm_visibility_left, arm_visibility_right),
            "forward_fold": max(
                self._visibility(lm, (LEFT_SHOULDER, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE)),
                self._visibility(lm, (RIGHT_SHOULDER, RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE)),
            ),
            "taekwondo_kick": self._visibility(
                lm,
                (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP, LEFT_KNEE, RIGHT_KNEE, LEFT_ANKLE, RIGHT_ANKLE),
            ),
            "head_turn": self._visibility(lm, (NOSE, LEFT_EAR, RIGHT_EAR, LEFT_SHOULDER, RIGHT_SHOULDER)),
            "arm_circle": max(arm_visibility_left, arm_visibility_right),
            "hip_circle": self._visibility(lm, (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP, LEFT_KNEE, RIGHT_KNEE)),
        }

        self.window.append(
            {
                "body_horizontal": body_horizontal,
                "torso_vertical": torso_vertical,
                "torso_horizontal": torso_horizontal,
                "body_angle": body_angle,
                "knee": knee,
                "left_knee": left_knee,
                "right_knee": right_knee,
                "elbow": elbow,
                "hip_angle": hip_angle,
                "hip_y": hip_mid.y,
                "ankle_ratio": ankle_ratio,
                "wrist_span": wrist_span,
                "wrist_above": wrist_above,
                "wrist_above_distance": wrist_above_distance,
                "wrist_near": wrist_near_shoulder,
                "wrist_below_hip": wrist_below_hip,
                "elbow_extended": elbow_extended_ratio,
                "knee_lift": knee_lift,
                "knee_lift_asymmetry": knee_lift_asymmetry,
                "knee_angle_asymmetry": knee_angle_asymmetry,
                "kick_height": kick_height,
                "kick_extension": kick_extension,
                "head_yaw": head_yaw,
                "left_wrist_rel_x": left_wrist_rel_x,
                "left_wrist_rel_y": left_wrist_rel_y,
                "right_wrist_rel_x": right_wrist_rel_x,
                "right_wrist_rel_y": right_wrist_rel_y,
                "hip_rel_x": hip_rel_x,
                "hip_rel_y": hip_rel_y,
                "wrist_height_norm": wrist_height_norm,
                "elbow_height_norm": elbow_height_norm,
                "elbow_side_drift": elbow_side_drift,
                "visibility": visibility,
            }
        )

        if len(self.window) < 5:
            return Classification(None, 0.0, {}, False, None, 0.0)

        def arr(name: str) -> np.ndarray:
            return np.asarray([sample[name] for sample in self.window], dtype=float)

        knees = arr("knee")
        left_knees = arr("left_knee")
        right_knees = arr("right_knee")
        elbows = arr("elbow")
        hips = arr("hip_y")
        hip_angles = arr("hip_angle")
        ankles = arr("ankle_ratio")
        wrist_spans = arr("wrist_span")
        above = arr("wrist_above")
        above_distance = arr("wrist_above_distance")
        near = arr("wrist_near")
        below_hip = arr("wrist_below_hip")
        elbow_extended = arr("elbow_extended")
        knee_lifts = arr("knee_lift")
        knee_lift_asym = arr("knee_lift_asymmetry")
        knee_angle_asym = arr("knee_angle_asymmetry")
        torso_h = arr("torso_horizontal")
        kick_heights = arr("kick_height")
        kick_extensions = arr("kick_extension")
        head_yaws = arr("head_yaw")
        left_wrist_x = arr("left_wrist_rel_x")
        left_wrist_y = arr("left_wrist_rel_y")
        right_wrist_x = arr("right_wrist_rel_x")
        right_wrist_y = arr("right_wrist_rel_y")
        hip_rel_x = arr("hip_rel_x")
        hip_rel_y = arr("hip_rel_y")
        wrist_heights = arr("wrist_height_norm")
        elbow_heights = arr("elbow_height_norm")
        elbow_side_drift = arr("elbow_side_drift")
        body_horizontals = arr("body_horizontal")
        torso_verticals = arr("torso_vertical")

        median_body_horizontal = float(np.median(body_horizontals))
        median_torso_vertical = float(np.median(torso_verticals))
        horizontal_score = clamp((56.0 - median_body_horizontal) / 42.0)
        vertical_score = clamp((64.0 - median_torso_vertical) / 54.0)
        knee_motion = clamp(float(np.ptp(knees)) / 44.0)
        left_knee_motion = clamp(float(np.ptp(left_knees)) / 42.0)
        right_knee_motion = clamp(float(np.ptp(right_knees)) / 42.0)
        elbow_motion = clamp(float(np.ptp(elbows)) / 52.0)
        hip_motion = clamp(float(np.ptp(hips)) / 0.095)
        hip_angle_motion = clamp(float(np.ptp(hip_angles)) / 48.0)
        leg_width_motion = clamp(float(np.ptp(ankles)) / 0.42)
        wrist_span_motion = clamp(float(np.ptp(wrist_spans)) / 1.0)
        wrist_vertical_transition = clamp(float(np.ptp(above)) + 0.65 * float(np.ptp(near)))
        arm_down_transition = clamp(float(np.ptp(below_hip)))
        knee_lift_motion = clamp(float(np.ptp(knee_lifts)) / 0.14)
        alternating_knee_motion = clamp((left_knee_motion + right_knee_motion) / 1.35)
        lunge_asymmetry = clamp(float(np.percentile(knee_angle_asym, 80)) / 62.0)
        high_knee_asymmetry = clamp(float(np.percentile(knee_lift_asym, 80)) / 0.12)
        situp_orientation_motion = clamp(float(np.ptp(torso_h)) / 48.0)
        kick_peak = float(np.percentile(kick_heights, 90))
        kick_height_motion = clamp(float(np.ptp(kick_heights)) / 0.72)
        kick_extension_score = clamp((float(np.percentile(kick_extensions, 85)) - 0.58) / 0.38)
        head_turn_motion = clamp(float(np.ptp(head_yaws)) / 0.85)
        head_turn_peak = clamp(float(np.percentile(np.abs(head_yaws), 85)) / 0.72)
        left_arm_circle_motion = clamp(
            min(float(np.ptp(left_wrist_x)), 2.0) / 1.2
            * min(float(np.ptp(left_wrist_y)), 2.0) / 1.2
        )
        right_arm_circle_motion = clamp(
            min(float(np.ptp(right_wrist_x)), 2.0) / 1.2
            * min(float(np.ptp(right_wrist_y)), 2.0) / 1.2
        )
        arm_circle_motion = max(left_arm_circle_motion, right_arm_circle_motion)
        hip_circle_motion = clamp(
            min(float(np.ptp(hip_rel_x)), 0.8) / 0.28
            * min(float(np.ptp(hip_rel_y)), 0.8) / 0.22
        )
        mean_extended = float(np.mean(elbow_extended))
        quietness = clamp(1.0 - max(knee_motion, elbow_motion, hip_motion, hip_angle_motion * 0.75))

        # Arm-path features separate curls from shoulder presses. A press must
        # move the wrist clearly above the shoulder; a curl keeps the hand at
        # or below shoulder height and the upper arm comparatively anchored.
        wrist_height_peak = float(np.percentile(wrist_heights, 90))
        wrist_height_low = float(np.percentile(wrist_heights, 10))
        wrist_height_motion = clamp(float(np.ptp(wrist_heights)) / 1.65)
        overhead_presence = clamp((wrist_height_peak - 0.22) / 0.95)
        below_shoulder_presence = clamp((0.35 - wrist_height_peak) / 0.90)
        elbow_raise_motion = clamp(float(np.ptp(elbow_heights)) / 0.95)
        elbow_anchor = clamp((1.55 - float(np.percentile(elbow_side_drift, 75))) / 1.25)
        lower_body_stillness = clamp(1.0 - max(knee_motion, hip_motion, hip_angle_motion))

        # Hierarchical posture family gates. These are deliberately hard:
        # floor exercises cannot be reported as squats, and upright exercises
        # cannot be reported as push-ups.
        floor_family = clamp((48.0 - median_body_horizontal) / 22.0)
        upright_family = clamp((median_body_horizontal - 50.0) / 24.0) * vertical_score
        transitional_family = 1.0 - max(floor_family, upright_family)

        def vis_score(name: str) -> float:
            return clamp((visibility[name] - 0.23) / 0.48)

        knee_hold_score = clamp(1.0 - abs(knee - 95.0) / 58.0)
        body_straight_score = clamp((body_angle - 118.0) / 52.0)
        forward_fold_score = clamp((62.0 - torso_horizontal) / 50.0) * clamp((150.0 - hip_angle) / 92.0)
        overhead_score = clamp((float(np.mean(above_distance)) - 0.10) / 0.95)

        scores = {
            "pushup": vis_score("pushup") * floor_family * (
                0.48 * horizontal_score + 0.36 * elbow_motion + 0.16 * (1.0 - knee_motion)
            ),
            "squat": vis_score("squat") * upright_family * (
                0.50 * knee_motion + 0.32 * hip_motion + 0.18 * hip_angle_motion
            ) * (0.78 + 0.22 * (1.0 - lunge_asymmetry)),
            "curl": vis_score("curl") * upright_family * lower_body_stillness * (
                0.58 * elbow_motion
                + 0.22 * arm_down_transition
                + 0.20 * elbow_anchor
            ) * (0.55 + 0.45 * below_shoulder_presence) * (1.0 - 0.72 * overhead_presence),
            "shoulder_press": vis_score("shoulder_press") * upright_family * lower_body_stillness * (
                0.34 * elbow_motion
                + 0.34 * wrist_height_motion
                + 0.22 * overhead_presence
                + 0.10 * elbow_raise_motion
            ) * (0.50 + 0.50 * overhead_presence),
            "jumping_jack": vis_score("jumping_jack") * vertical_score * (
                0.49 * leg_width_motion + 0.41 * max(float(np.ptp(above)), float(np.mean(above))) + 0.10 * wrist_span_motion
            ),
            "lunge": vis_score("lunge") * vertical_score * (
                0.43 * knee_motion + 0.35 * lunge_asymmetry + 0.22 * hip_motion
            ) * (0.72 + 0.28 * (1.0 - leg_width_motion)),
            "lateral_raise": vis_score("lateral_raise") * vertical_score * (
                0.50 * wrist_span_motion + 0.27 * wrist_vertical_transition + 0.23 * mean_extended
            ) * (0.65 + 0.35 * (1.0 - elbow_motion)),
            "high_knee": vis_score("high_knee") * vertical_score * (
                0.42 * knee_lift_motion + 0.34 * alternating_knee_motion + 0.24 * high_knee_asymmetry
            ) * (0.72 + 0.28 * (1.0 - hip_motion)),
            "situp": vis_score("situp") * (
                0.43 * situp_orientation_motion + 0.38 * hip_angle_motion + 0.19 * (1.0 - vertical_score)
            ) * (0.68 + 0.32 * (1.0 - elbow_motion)),
            "plank": vis_score("plank") * horizontal_score * (
                0.55 * body_straight_score + 0.45 * quietness
            ),
            "squat_hold": vis_score("squat_hold") * vertical_score * knee_hold_score * (
                0.60 + 0.40 * quietness
            ),
            "overhead_stretch": vis_score("overhead_stretch") * vertical_score * (
                0.38 * overhead_score + 0.32 * mean_extended + 0.30 * quietness
            ),
            "forward_fold": vis_score("forward_fold") * forward_fold_score * (
                0.62 + 0.38 * quietness
            ),
            "taekwondo_kick": vis_score("taekwondo_kick") * vertical_score * (
                0.46 * clamp((kick_peak + 0.12) / 0.42)
                + 0.30 * kick_height_motion
                + 0.24 * kick_extension_score
            ),
            "head_turn": vis_score("head_turn") * (
                0.52 * head_turn_motion + 0.30 * head_turn_peak + 0.18 * quietness
            ),
            "arm_circle": vis_score("arm_circle") * vertical_score * (
                0.52 * arm_circle_motion + 0.30 * mean_extended + 0.18 * (1.0 - knee_motion)
            ),
            "hip_circle": vis_score("hip_circle") * (
                0.58 * hip_circle_motion + 0.24 * (1.0 - knee_motion) + 0.18 * (1.0 - elbow_motion)
            ),
        }

        # Impossible-posture gates.
        if body_horizontal > 58.0:
            scores["pushup"] *= 0.12
            scores["plank"] *= 0.12
        if torso_vertical > 70.0:
            for name in ("squat", "curl", "shoulder_press", "jumping_jack", "lunge", "lateral_raise", "high_knee", "squat_hold", "overhead_stretch"):
                scores[name] *= 0.18
        if horizontal_score > 0.70:
            scores["situp"] *= 0.50
        if mean_extended < 0.58:
            scores["lateral_raise"] *= 0.56
            scores["overhead_stretch"] *= 0.45
        if leg_width_motion < 0.18:
            scores["jumping_jack"] *= 0.45
        if lunge_asymmetry < 0.20:
            scores["lunge"] *= 0.52
        if knee_lift_motion < 0.18:
            scores["high_knee"] *= 0.45
        if not (62.0 <= knee <= 138.0):
            scores["squat_hold"] *= 0.18
        if hip_angle > 152.0 or torso_horizontal > 66.0:
            scores["forward_fold"] *= 0.15
        if kick_peak < -0.18 or float(np.percentile(kick_extensions, 85)) < 0.62:
            scores["taekwondo_kick"] *= 0.12
        if head_turn_motion < 0.20:
            scores["head_turn"] *= 0.24
        if arm_circle_motion < 0.16:
            scores["arm_circle"] *= 0.24
        if hip_circle_motion < 0.16:
            scores["hip_circle"] *= 0.22

        # Mutually exclusive body-orientation gates.
        if floor_family >= 0.62:
            for name in (
                "squat", "curl", "shoulder_press", "jumping_jack", "lunge",
                "lateral_raise", "high_knee", "squat_hold", "overhead_stretch",
                "taekwondo_kick", "head_turn", "arm_circle", "hip_circle",
            ):
                scores[name] *= 0.015
        elif upright_family >= 0.55:
            scores["pushup"] *= 0.01
            scores["plank"] *= 0.02
            scores["situp"] *= 0.14

        # Lower-body and upper-body motion are kept distinct.
        if max(knee_motion, hip_motion, hip_angle_motion) < 0.16:
            scores["squat"] *= 0.20
            scores["lunge"] *= 0.28
        if knee_motion > 0.34 or hip_motion > 0.34:
            scores["curl"] *= 0.32
            scores["shoulder_press"] *= 0.32
            scores["lateral_raise"] *= 0.35

        # Curl/press disambiguation.
        if wrist_height_peak < 0.18:
            scores["shoulder_press"] *= 0.16
        if wrist_height_peak > 0.62:
            scores["curl"] *= 0.08
        if wrist_height_motion < 0.22:
            scores["shoulder_press"] *= 0.30
        if elbow_anchor < 0.18:
            scores["curl"] *= 0.35

        # A classifier must never choose an exercise disabled in the dashboard.
        if self.enabled_exercises:
            scores = {name: value for name, value in scores.items() if name in self.enabled_exercises}
        if not scores:
            return Classification(None, 0.0, {}, False, None, 0.0)

        ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        best_name, best_score = ordered[0]
        second_score = ordered[1][1] if len(ordered) > 1 else 0.0
        margin = best_score - second_score

        enabled_count = len(scores)
        minimum_score = 0.34 if enabled_count <= 2 else (0.37 if enabled_count <= 5 else 0.40)
        minimum_margin = 0.010 if enabled_count <= 2 else (0.018 if enabled_count <= 5 else 0.028)
        acceptable = best_score >= minimum_score and margin >= minimum_margin
        if acceptable:
            if self._candidate == best_name:
                self._candidate_frames += 1
            else:
                self._candidate = best_name
                self._candidate_frames = 1
        else:
            self._candidate = None
            self._candidate_frames = 0

        stable = self._candidate is not None and self._candidate_frames >= self.lock_frames
        return Classification(
            exercise=self._candidate if stable else None,
            confidence=float(best_score),
            scores={name: float(value) for name, value in scores.items()},
            stable=stable,
            candidate=best_name if acceptable else None,
            margin=float(margin),
        )
