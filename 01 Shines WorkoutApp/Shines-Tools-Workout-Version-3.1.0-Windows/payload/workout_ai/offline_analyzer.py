from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Sequence

import cv2
import numpy as np

from .constants import (
    DISPLAY_NAMES,
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
from .geometry import PoseFrame, angle, clamp, distance, line_angle_to_horizontal
from .ui import draw_pose


@dataclass
class FrameObservation:
    frame_index: int
    timestamp: float
    pose: PoseFrame | None
    valid: bool
    quality: float
    primary: float | None
    secondary: float | None
    active_landmarks: tuple[int, ...]
    side: str | None = None


@dataclass
class DetectedRep:
    number: int
    start_frame: int
    active_frame: int
    end_frame: int
    start_time: float
    active_time: float
    end_time: float
    duration: float
    rom: float
    quality: float


@dataclass
class OfflineAnalysisResult:
    exercise: str
    detected_count: int
    final_count: int
    fps: float
    frame_count: int
    duration_seconds: float
    side: str | None
    reps: list[DetectedRep]
    valid_fraction: float
    signal_range: float
    low_threshold: float
    high_threshold: float
    raw_video_path: str
    annotated_video_path: str
    motion_plot_path: str = ""
    manually_corrected: bool = False
    workout_name: str = ""
    profile: str = "User"

    def to_json(self, path: Path) -> None:
        payload = asdict(self)
        payload["reps"] = [asdict(rep) for rep in self.reps]
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


SIDE_LANDMARKS = {
    "left": (LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE),
    "right": (RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST, RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE),
}


def _finite(value: float | None) -> bool:
    return value is not None and np.isfinite(value)


def _mean_visibility(pose: PoseFrame, indexes: Iterable[int]) -> float:
    values = [pose.image[i].visibility for i in indexes]
    return float(np.mean(values)) if values else 0.0


def _dominant_side(poses: Sequence[PoseFrame | None], exercise: str) -> str:
    if exercise == "jumping_jack":
        return "both"
    scores: dict[str, list[float]] = {"left": [], "right": []}
    if exercise in {"curl", "shoulder_press"}:
        side_sets = {
            "left": (LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST),
            "right": (RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST),
        }
    elif exercise == "squat":
        side_sets = {
            "left": (LEFT_SHOULDER, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE),
            "right": (RIGHT_SHOULDER, RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE),
        }
    else:
        side_sets = SIDE_LANDMARKS
    for pose in poses:
        if pose is None:
            continue
        for side, indexes in side_sets.items():
            scores[side].append(_mean_visibility(pose, indexes))
    left = float(np.median(scores["left"])) if scores["left"] else 0.0
    right = float(np.median(scores["right"])) if scores["right"] else 0.0
    return "left" if left >= right else "right"


def _score_high(value: float, poor: float, good: float) -> float:
    if not np.isfinite(value) or good <= poor:
        return 0.0
    return clamp((value - poor) / (good - poor))


def _score_low(value: float, good: float, poor: float) -> float:
    if not np.isfinite(value) or poor <= good:
        return 0.0
    return clamp((poor - value) / (poor - good))


def _extract_observation(
    pose: PoseFrame | None,
    exercise: str,
    side: str,
    frame_index: int,
    timestamp: float,
) -> FrameObservation:
    if pose is None:
        return FrameObservation(frame_index, timestamp, None, False, 0.0, None, None, (), side)

    lm = pose.image
    world = pose.world or pose.image

    if exercise == "pushup":
        s, e, w, h, k, a = SIDE_LANDMARKS[side]
        # Knee push-ups are supported. Use the ankle when visible, otherwise the knee.
        end = a if lm[a].visibility >= 0.28 else k
        required = (s, e, w, h, k, end)
        visibility = _mean_visibility(pose, required)
        body_len = max(distance(lm[s], lm[end]), 0.08)
        horizontal = line_angle_to_horizontal(lm[s], lm[end])
        elbow = angle(world[s], world[e], world[w])
        body_angle = angle(world[s], world[h], world[end])
        # At the top of a push-up the shoulder is higher in the image. Negating
        # this value makes both features "high at rest/top".
        shoulder_height = -(lm[s].y - lm[w].y) / body_len
        wrist_support = abs(lm[w].x - lm[s].x) / body_len
        quality = clamp(
            0.30 * _score_high(visibility, 0.20, 0.72)
            + 0.35 * _score_low(horizontal, 24.0, 70.0)
            + 0.20 * _score_high(body_angle, 105.0, 168.0)
            + 0.15 * _score_low(wrist_support, 0.25, 0.95)
        )
        # Only the orientation gate is non-negotiable. Range and alignment are
        # used for scoring, not for rejecting normal human repetitions.
        valid = visibility >= 0.24 and horizontal <= 72.0 and np.isfinite(elbow)
        return FrameObservation(
            frame_index, timestamp, pose, valid, quality, float(elbow), float(shoulder_height), required, side
        )

    if exercise == "squat":
        if side == "left":
            s, h, k, a = LEFT_SHOULDER, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE
        else:
            s, h, k, a = RIGHT_SHOULDER, RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE
        required = (s, h, k, a)
        visibility = _mean_visibility(pose, required)
        knee = angle(world[h], world[k], world[a])
        torso_vertical = 90.0 - line_angle_to_horizontal(lm[s], lm[h])
        body_len = max(distance(lm[s], lm[a]), 0.08)
        hip_height = -lm[h].y / body_len
        quality = clamp(
            0.45 * _score_high(visibility, 0.20, 0.72)
            + 0.35 * _score_low(abs(torso_vertical), 12.0, 68.0)
            + 0.20 * _score_high(lm[a].visibility, 0.18, 0.65)
        )
        valid = visibility >= 0.24 and np.isfinite(knee)
        return FrameObservation(frame_index, timestamp, pose, valid, quality, float(knee), float(hip_height), required, side)

    if exercise == "curl":
        if side == "left":
            s, e, w, h = LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST, LEFT_HIP
        else:
            s, e, w, h = RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST, RIGHT_HIP
        required = (s, e, w)
        visibility = _mean_visibility(pose, required)
        elbow = angle(world[s], world[e], world[w])
        upper_arm_drift = distance(lm[e], lm[h]) if lm[h].visibility >= 0.15 else 0.0
        quality = clamp(0.75 * _score_high(visibility, 0.18, 0.70) + 0.25 * _score_high(upper_arm_drift, 0.02, 0.18))
        valid = visibility >= 0.22 and np.isfinite(elbow)
        return FrameObservation(frame_index, timestamp, pose, valid, quality, float(elbow), None, required, side)

    if exercise == "shoulder_press":
        if side == "left":
            s, e, w = LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST
        else:
            s, e, w = RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST
        required = (s, e, w)
        visibility = _mean_visibility(pose, required)
        elbow = angle(world[s], world[e], world[w])
        # Rest position is hand near the shoulder. Higher image y and smaller
        # elbow angle therefore represent rest; invert elbow for a high-rest signal.
        wrist_rest = lm[w].y - lm[s].y
        quality = _score_high(visibility, 0.18, 0.72)
        valid = visibility >= 0.22 and np.isfinite(elbow)
        return FrameObservation(frame_index, timestamp, pose, valid, quality, -float(elbow), float(wrist_rest), required, side)

    if exercise == "jumping_jack":
        required = (
            LEFT_SHOULDER,
            RIGHT_SHOULDER,
            LEFT_WRIST,
            RIGHT_WRIST,
            LEFT_HIP,
            RIGHT_HIP,
            LEFT_ANKLE,
            RIGHT_ANKLE,
        )
        visibility = _mean_visibility(pose, required)
        shoulder_width = max(distance(lm[LEFT_SHOULDER], lm[RIGHT_SHOULDER]), 0.04)
        ankle_spread = distance(lm[LEFT_ANKLE], lm[RIGHT_ANKLE]) / shoulder_width
        wrists_y = (lm[LEFT_WRIST].y + lm[RIGHT_WRIST].y) / 2.0
        shoulders_y = (lm[LEFT_SHOULDER].y + lm[RIGHT_SHOULDER].y) / 2.0
        wrist_rest = wrists_y - shoulders_y
        quality = _score_high(visibility, 0.18, 0.72)
        valid = visibility >= 0.22
        # Rest is feet together and hands down, therefore invert ankle spread.
        return FrameObservation(frame_index, timestamp, pose, valid, quality, -float(ankle_spread), float(wrist_rest), required, "both")

    raise ValueError(f"Unsupported exercise: {exercise}")


def _interpolate(values: np.ndarray, valid: np.ndarray, max_gap_frames: int) -> np.ndarray:
    result = values.astype(float, copy=True)
    finite = np.isfinite(result) & valid
    if finite.sum() < 2:
        return result
    indexes = np.arange(len(result))
    interp = np.interp(indexes, indexes[finite], result[finite])
    # Fill only short internal gaps. Long gaps remain NaN and split the session.
    missing = ~finite
    start = None
    for i, flag in enumerate(missing):
        if flag and start is None:
            start = i
        if start is not None and (not flag or i == len(missing) - 1):
            end = i if not flag else i + 1
            length = end - start
            if length <= max_gap_frames and start > 0 and end < len(result):
                result[start:end] = interp[start:end]
            start = None
    return result


def _median_filter(values: np.ndarray, window: int) -> np.ndarray:
    if window <= 1:
        return values.copy()
    if window % 2 == 0:
        window += 1
    half = window // 2
    padded = np.pad(values, (half, half), mode="edge")
    output = np.empty_like(values, dtype=float)
    for i in range(len(values)):
        chunk = padded[i : i + window]
        finite = chunk[np.isfinite(chunk)]
        output[i] = float(np.median(finite)) if finite.size else np.nan
    return output


def _moving_average(values: np.ndarray, window: int) -> np.ndarray:
    if window <= 1:
        return values.copy()
    finite = np.isfinite(values)
    source = np.where(finite, values, 0.0)
    kernel = np.ones(window, dtype=float)
    sums = np.convolve(source, kernel, mode="same")
    counts = np.convolve(finite.astype(float), kernel, mode="same")
    return np.divide(sums, counts, out=np.full_like(sums, np.nan), where=counts > 0)


def _close_short_gaps(mask: np.ndarray, max_gap: int) -> np.ndarray:
    result = mask.astype(bool, copy=True)
    start = None
    for i, flag in enumerate(result):
        if not flag and start is None:
            start = i
        if start is not None and (flag or i == len(result) - 1):
            end = i if flag else i + 1
            if start > 0 and end < len(result) and end - start <= max_gap:
                result[start:end] = True
            start = None
    return result


def _segments(mask: np.ndarray, min_frames: int) -> list[tuple[int, int]]:
    segments: list[tuple[int, int]] = []
    start = None
    for i, flag in enumerate(mask):
        if flag and start is None:
            start = i
        if start is not None and (not flag or i == len(mask) - 1):
            end = i if not flag else i + 1
            if end - start >= min_frames:
                segments.append((start, end))
            start = None
    return segments


def _robust_normalize(values: np.ndarray) -> tuple[np.ndarray, float]:
    finite = values[np.isfinite(values)]
    if finite.size < 4:
        return np.full_like(values, np.nan), 0.0
    low, high = np.percentile(finite, [10, 90])
    spread = float(high - low)
    if spread < 1e-6:
        return np.full_like(values, 0.5), spread
    normalized = (values - low) / spread
    return np.clip(normalized, 0.0, 1.0), spread


def count_cycles_from_signal(
    signal: Sequence[float],
    fps: float,
    valid_mask: Sequence[bool] | None = None,
    quality: Sequence[float] | None = None,
    min_rep_seconds: float = 0.28,
    max_rep_seconds: float = 12.0,
) -> tuple[list[DetectedRep], float, float]:
    """Count rest -> active -> rest cycles using adaptive hysteresis.

    The function intentionally uses the full signal distribution. It does not
    expect a fixed elbow angle such as 90 degrees, which is why it is much more
    tolerant of camera perspective, body proportions and normal human range.
    """
    values = np.asarray(signal, dtype=float)
    n = len(values)
    if n == 0:
        return [], 0.38, 0.62
    valid = np.isfinite(values) if valid_mask is None else np.asarray(valid_mask, dtype=bool) & np.isfinite(values)
    qualities = np.ones(n, dtype=float) if quality is None else np.asarray(quality, dtype=float)
    valid = _close_short_gaps(valid, max(1, int(round(fps * 0.55))))
    min_segment = max(8, int(round(fps * 0.75)))
    reps: list[DetectedRep] = []
    rep_number = 0
    global_low, global_high = 0.38, 0.62

    for seg_start, seg_end in _segments(valid, min_segment):
        segment = values[seg_start:seg_end]
        finite = segment[np.isfinite(segment)]
        if finite.size < min_segment // 2:
            continue
        # Percentile thresholds adapt to shallow-but-real repetitions.
        p20, p80 = np.percentile(finite, [20, 80])
        amplitude = float(p80 - p20)
        if amplitude < 0.16:
            continue
        low_thr = float(p20 + 0.28 * amplitude)
        high_thr = float(p20 + 0.72 * amplitude)
        global_low, global_high = low_thr, high_thr

        state = "search"
        start_idx = seg_start
        active_idx = seg_start
        min_idx = seg_start
        min_value = math.inf
        last_count_end = -10_000
        min_rep_frames = max(3, int(round(fps * min_rep_seconds)))
        max_rep_frames = max(min_rep_frames + 1, int(round(fps * max_rep_seconds)))
        cooldown = max(2, int(round(fps * 0.18)))

        for idx in range(seg_start, seg_end):
            value = values[idx]
            if not np.isfinite(value):
                continue
            if state == "search":
                if value >= high_thr:
                    state = "rest"
                    start_idx = idx
                    min_idx = idx
                    min_value = value
            elif state == "rest":
                if value < min_value:
                    min_value, min_idx = value, idx
                if value <= low_thr:
                    state = "active"
                    active_idx = min_idx
                elif idx - start_idx > max_rep_frames:
                    start_idx = idx
                    min_idx = idx
                    min_value = value
            else:  # active
                if value < min_value:
                    min_value, min_idx = value, idx
                    active_idx = idx
                if value >= high_thr:
                    duration_frames = idx - start_idx
                    excursion = float(np.nanmax(values[start_idx : idx + 1]) - np.nanmin(values[start_idx : idx + 1]))
                    if (
                        min_rep_frames <= duration_frames <= max_rep_frames
                        and idx - last_count_end >= cooldown
                        and excursion >= max(0.18, 0.45 * amplitude)
                    ):
                        rep_number += 1
                        rep_quality = float(np.nanmean(qualities[start_idx : idx + 1])) if idx > start_idx else 0.0
                        reps.append(
                            DetectedRep(
                                number=rep_number,
                                start_frame=start_idx,
                                active_frame=active_idx,
                                end_frame=idx,
                                start_time=start_idx / fps,
                                active_time=active_idx / fps,
                                end_time=idx / fps,
                                duration=duration_frames / fps,
                                rom=excursion,
                                quality=clamp(rep_quality),
                            )
                        )
                        last_count_end = idx
                    state = "rest"
                    start_idx = idx
                    min_idx = idx
                    min_value = value
                elif idx - start_idx > max_rep_frames:
                    state = "search"

    return reps, global_low, global_high


def _build_combined_signal(
    observations: Sequence[FrameObservation], fps: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    n = len(observations)
    valid = np.array([item.valid for item in observations], dtype=bool)
    quality = np.array([item.quality for item in observations], dtype=float)
    primary = np.array([item.primary if _finite(item.primary) else np.nan for item in observations], dtype=float)
    secondary = np.array([item.secondary if _finite(item.secondary) else np.nan for item in observations], dtype=float)

    gap = max(1, int(round(fps * 0.50)))
    primary = _interpolate(primary, valid, gap)
    secondary = _interpolate(secondary, valid, gap)
    median_window = max(3, int(round(fps * 0.13)) | 1)
    average_window = max(2, int(round(fps * 0.10)))
    primary = _moving_average(_median_filter(primary, median_window), average_window)
    secondary = _moving_average(_median_filter(secondary, median_window), average_window)

    # Normalize globally first. Each valid set is already restricted to the named
    # exercise posture, and a second adaptive normalization occurs in the counter.
    p_norm, p_range = _robust_normalize(primary[valid])
    primary_full = np.full(n, np.nan)
    if p_norm.size:
        primary_full[np.where(valid)[0]] = p_norm

    secondary_full = np.full(n, np.nan)
    s_range = 0.0
    secondary_valid = valid & np.isfinite(secondary)
    if secondary_valid.sum() >= 4:
        s_norm, s_range = _robust_normalize(secondary[secondary_valid])
        secondary_full[np.where(secondary_valid)[0]] = s_norm

    # If the primary angle barely moves, rely more on body translation. This is
    # important for push-ups recorded from a perspective that compresses elbow ROM.
    primary_weight = 0.72 if p_range >= 12.0 else 0.52
    if s_range < 0.015:
        primary_weight = 1.0
    secondary_weight = 1.0 - primary_weight

    combined = np.full(n, np.nan)
    for i in range(n):
        parts: list[tuple[float, float]] = []
        if np.isfinite(primary_full[i]):
            parts.append((primary_full[i], primary_weight))
        if np.isfinite(secondary_full[i]):
            parts.append((secondary_full[i], secondary_weight))
        if parts:
            weight_sum = sum(weight for _, weight in parts)
            combined[i] = sum(value * weight for value, weight in parts) / max(weight_sum, 1e-6)

    combined = _moving_average(_median_filter(combined, max(3, int(round(fps * 0.17)) | 1)), max(2, int(round(fps * 0.10))))
    return combined, valid, quality, p_range


def analyse_video(
    video_path: Path,
    exercise: str,
    model_path: Path,
    annotated_path: Path,
    workout_name: str,
    profile: str,
    motion_plot_path: Path | None = None,
    progress_callback=None,
) -> OfflineAnalysisResult:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    if fps < 5.0 or fps > 120.0:
        fps = 30.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    poses: list[PoseFrame | None] = []
    frames_read = 0
    from .pose_engine import PoseEngine

    engine = PoseEngine(
        model_path,
        min_pose_detection_confidence=0.48,
        min_pose_presence_confidence=0.45,
        min_tracking_confidence=0.55,
    )
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            timestamp = frames_read / fps
            poses.append(engine.process(frame, timestamp))
            frames_read += 1
            if progress_callback and (frames_read % max(1, int(fps)) == 0 or frames_read == frame_count):
                progress_callback("pose", frames_read, max(frame_count, frames_read))
    finally:
        engine.close()
        cap.release()

    side = _dominant_side(poses, exercise)
    observations = [
        _extract_observation(pose, exercise, side, index, index / fps)
        for index, pose in enumerate(poses)
    ]
    signal, valid, quality, primary_range = _build_combined_signal(observations, fps)
    reps, low_threshold, high_threshold = count_cycles_from_signal(signal, fps, valid, quality)

    _write_annotated_video(
        video_path,
        annotated_path,
        exercise,
        workout_name,
        profile,
        observations,
        signal,
        reps,
        fps,
        low_threshold,
        high_threshold,
        progress_callback,
    )
    if motion_plot_path is not None:
        _write_signal_plot(
            motion_plot_path, signal, valid, reps, fps, low_threshold, high_threshold,
            exercise, workout_name,
        )

    finite_signal = signal[np.isfinite(signal)]
    signal_range = float(np.percentile(finite_signal, 90) - np.percentile(finite_signal, 10)) if finite_signal.size else 0.0
    duration = frames_read / fps if fps else 0.0
    return OfflineAnalysisResult(
        exercise=exercise,
        detected_count=len(reps),
        final_count=len(reps),
        fps=fps,
        frame_count=frames_read,
        duration_seconds=duration,
        side=None if side == "both" else side,
        reps=reps,
        valid_fraction=float(valid.mean()) if len(valid) else 0.0,
        signal_range=signal_range if signal_range > 0 else primary_range,
        low_threshold=low_threshold,
        high_threshold=high_threshold,
        raw_video_path=str(video_path),
        annotated_video_path=str(annotated_path),
        motion_plot_path=str(motion_plot_path) if motion_plot_path else "",
        workout_name=workout_name,
        profile=profile,
    )


def _write_annotated_video(
    source: Path,
    destination: Path,
    exercise: str,
    workout_name: str,
    profile: str,
    observations: Sequence[FrameObservation],
    signal: np.ndarray,
    reps: Sequence[DetectedRep],
    fps: float,
    low_threshold: float,
    high_threshold: float,
    progress_callback=None,
) -> None:
    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise RuntimeError(f"Could not reopen video for annotation: {source}")
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1280)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 720)
    destination.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(destination), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    if not writer.isOpened():
        cap.release()
        raise RuntimeError(f"Could not create annotated video: {destination}")

    rep_end_map = {rep.end_frame: rep for rep in reps}
    rep_active_map = {rep.active_frame: rep for rep in reps}
    current_count = 0
    flash_until = -1
    frame_index = 0
    # MediaPipe connection objects are available from a lightweight engine only
    # to obtain the canonical connection list. No second inference pass is used.
    import mediapipe as mp
    connections = mp.tasks.vision.PoseLandmarksConnections.POSE_LANDMARKS

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            observation = observations[frame_index] if frame_index < len(observations) else None
            if observation and observation.pose is not None:
                draw_pose(frame, observation.pose, connections, observation.active_landmarks, observation.valid)
            if frame_index in rep_active_map:
                flash_until = max(flash_until, frame_index + max(1, int(fps * 0.25)))
            if frame_index in rep_end_map:
                current_count = rep_end_map[frame_index].number
                flash_until = max(flash_until, frame_index + max(1, int(fps * 0.45)))

            overlay = frame.copy()
            cv2.rectangle(overlay, (0, 0), (width, 150), (0, 0, 0), -1)
            cv2.addWeighted(overlay, 0.67, frame, 0.33, 0, frame)
            cv2.putText(frame, f"OFFLINE ANALYSIS: {DISPLAY_NAMES[exercise].upper()}", (22, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.86, (255, 255, 255), 2, cv2.LINE_AA)
            cv2.putText(frame, f"{profile} | {workout_name}", (22, 72), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (210, 230, 255), 2, cv2.LINE_AA)
            cv2.putText(frame, f"Reps: {current_count}/{len(reps)}", (22, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.88, (80, 235, 120), 2, cv2.LINE_AA)
            value = signal[frame_index] if frame_index < len(signal) else np.nan
            if np.isfinite(value):
                phase = "REST/TOP" if value >= high_threshold else "ACTIVE/DOWN" if value <= low_threshold else "MOVING"
                cv2.putText(frame, f"Phase: {phase} | Motion signal: {value:.2f}", (260, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.56, (80, 230, 255), 2, cv2.LINE_AA)
            if frame_index <= flash_until:
                cv2.putText(frame, "REP DETECTED", (max(20, width - 330), 75), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (50, 255, 90), 3, cv2.LINE_AA)
            cv2.putText(frame, "Analysed after recording with adaptive full-video thresholds", (22, height - 24), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1, cv2.LINE_AA)
            writer.write(frame)
            frame_index += 1
            if progress_callback and frame_index % max(1, int(fps)) == 0:
                progress_callback("annotate", frame_index, len(observations))
    finally:
        cap.release()
        writer.release()



def _write_signal_plot(
    path: Path,
    signal: np.ndarray,
    valid: np.ndarray,
    reps: Sequence[DetectedRep],
    fps: float,
    low_threshold: float,
    high_threshold: float,
    exercise: str,
    workout_name: str,
) -> None:
    import matplotlib.pyplot as plt

    path.parent.mkdir(parents=True, exist_ok=True)
    times = np.arange(len(signal), dtype=float) / max(fps, 1e-6)
    plt.figure(figsize=(14, 5))
    plt.plot(times, signal, linewidth=1.5, label="Adaptive movement signal")
    plt.axhline(high_threshold, linestyle="--", linewidth=1.0, label="Rest/top threshold")
    plt.axhline(low_threshold, linestyle="--", linewidth=1.0, label="Active/down threshold")
    invalid = ~np.asarray(valid, dtype=bool)
    if invalid.any():
        plt.fill_between(times, 0, 1, where=invalid, alpha=0.12, transform=plt.gca().get_xaxis_transform(), label="Pose unavailable")
    for rep in reps:
        plt.axvline(rep.end_time, linewidth=0.9, alpha=0.65)
        plt.text(rep.end_time, 1.02, str(rep.number), ha="center", va="bottom", fontsize=8)
    plt.ylim(-0.05, 1.12)
    plt.xlabel("Time (seconds)")
    plt.ylabel("Normalized movement")
    plt.title(f"{workout_name} — {DISPLAY_NAMES[exercise]} — {len(reps)} detected reps")
    plt.legend(loc="lower right", ncol=4, fontsize=8)
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()

def corrected_rep_times(
    result: OfflineAnalysisResult, final_count: int, started_at: datetime
) -> list[tuple[datetime, float | None, float | None, float | None]]:
    """Return rep timestamps for DB persistence after optional human review."""
    final_count = max(0, int(final_count))
    detected = result.reps
    if final_count <= len(detected):
        selected = detected[:final_count]
        return [
            (
                started_at + timedelta(seconds=rep.end_time),
                rep.quality * 100.0,
                rep.rom,
                rep.duration,
            )
            for rep in selected
        ]
    rows = [
        (
            started_at + timedelta(seconds=rep.end_time),
            rep.quality * 100.0,
            rep.rom,
            rep.duration,
        )
        for rep in detected
    ]
    missing = final_count - len(rows)
    start = detected[-1].end_time if detected else 0.0
    remaining = max(result.duration_seconds - start, 1.0)
    for i in range(missing):
        seconds = start + remaining * (i + 1) / (missing + 1)
        rows.append((started_at + timedelta(seconds=seconds), None, None, None))
    rows.sort(key=lambda item: item[0])
    return rows
