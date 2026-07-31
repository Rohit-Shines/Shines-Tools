from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path

import cv2

from .constants import DISPLAY_NAMES


def safe_slug(value: str) -> str:
    value = value.strip()
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    return value.strip("_") or "workout"


def open_camera(index: int = 0) -> cv2.VideoCapture:
    camera = cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
    if not camera.isOpened():
        camera = cv2.VideoCapture(index)
    if not camera.isOpened():
        raise RuntimeError(
            "Could not open camera. Enable Terminal/Python under System Settings > Privacy & Security > Camera."
        )
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    camera.set(cv2.CAP_PROP_FPS, 30)
    return camera


def record_video(
    output_path: Path,
    exercise: str,
    workout_name: str,
    profile: str,
    camera_index: int = 0,
) -> tuple[datetime, float, int]:
    camera = open_camera(camera_index)
    ok, frame = camera.read()
    if not ok:
        camera.release()
        raise RuntimeError("Camera opened but did not return a frame.")
    height, width = frame.shape[:2]
    fps = float(camera.get(cv2.CAP_PROP_FPS) or 30.0)
    if fps < 5.0 or fps > 90.0:
        fps = 30.0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(output_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    if not writer.isOpened():
        camera.release()
        raise RuntimeError(f"Could not create video: {output_path}")

    countdown_end = time.monotonic() + 3.0
    while time.monotonic() < countdown_end:
        ok, frame = camera.read()
        if not ok:
            continue
        frame = cv2.flip(frame, 1)
        remaining = max(1, int(countdown_end - time.monotonic()) + 1)
        cv2.putText(frame, f"Starting in {remaining}", (40, 90), cv2.FONT_HERSHEY_SIMPLEX, 1.8, (80, 230, 255), 4, cv2.LINE_AA)
        cv2.putText(frame, DISPLAY_NAMES[exercise].upper(), (40, 145), cv2.FONT_HERSHEY_SIMPLEX, 0.95, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.imshow("Workout Accuracy Recorder", frame)
        if cv2.waitKey(1) & 0xFF == 27:
            camera.release()
            writer.release()
            cv2.destroyAllWindows()
            raise KeyboardInterrupt

    started_wall = datetime.now()
    started = time.monotonic()
    frames = 0
    try:
        while True:
            ok, raw = camera.read()
            if not ok:
                break
            # Write the unmodified camera frame. Offline analysis receives the
            # cleanest possible video and is not slowed down by live inference.
            writer.write(raw)
            display = cv2.flip(raw, 1)
            elapsed = time.monotonic() - started
            overlay = display.copy()
            cv2.rectangle(overlay, (0, 0), (width, 135), (0, 0, 0), -1)
            cv2.addWeighted(overlay, 0.68, display, 0.32, 0, display)
            cv2.putText(display, f"RECORDING: {DISPLAY_NAMES[exercise].upper()}", (25, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.90, (255, 255, 255), 2, cv2.LINE_AA)
            cv2.putText(display, f"{profile} | {workout_name} | {elapsed:0.1f}s", (25, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (210, 230, 255), 2, cv2.LINE_AA)
            cv2.putText(display, "Press Q when finished. Press Esc to cancel.", (25, 115), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (80, 230, 255), 2, cv2.LINE_AA)
            cv2.putText(display, "Raw recording now; high-accuracy pose analysis runs afterwards.", (25, height - 22), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1, cv2.LINE_AA)
            cv2.imshow("Workout Accuracy Recorder", display)
            frames += 1
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), ord("Q")):
                break
            if key == 27:
                raise KeyboardInterrupt
    finally:
        camera.release()
        writer.release()
        cv2.destroyAllWindows()
    return started_wall, (frames / fps if fps else 0.0), frames
