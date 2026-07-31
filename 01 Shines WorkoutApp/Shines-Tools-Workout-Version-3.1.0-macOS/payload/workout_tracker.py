#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import cv2

WINDOW_NAME = "Workout Version 3 - Live"

from workout_ai.classifier import ExerciseClassifier
from workout_ai.constants import (
    DEFAULT_HOME,
    DISPLAY_NAMES,
    EXERCISES,
    EXERCISE_UNITS,
    REP_EXERCISES,
    TIMED_EXERCISES,
)
from workout_ai.database import WorkoutDatabase
from workout_ai.exercises import TrackerOutput, create_trackers
from workout_ai.gestures import HeadTouchExerciseSelector
from workout_ai.pose_engine import PoseEngine
from workout_ai.reporting import build_dashboard
from workout_ai.exporter import auto_export
from workout_ai.router import AutoExerciseRouter
from workout_ai.ui import draw_dashboard, draw_pose


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Automatic Mac camera workout tracker")
    parser.add_argument("--home", type=Path, default=Path(os.environ.get("WORKOUT_HOME", DEFAULT_HOME)))
    parser.add_argument("--profile", default="User")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--exercise", choices=["auto", "manual"], default="auto")
    # Retained for backward-compatible launch commands. Version 2.6 never records video.
    parser.add_argument("--no-video", action="store_true")
    parser.add_argument("--workout-name", default="", help="Optional session label shown in history and exports")
    parser.add_argument(
        "--acceptance",
        type=float,
        default=60.0,
        help="Minimum human-like movement quality percentage (45-85, default 60)",
    )
    return parser.parse_args()


def open_camera(index: int) -> cv2.VideoCapture:
    camera = cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
    if not camera.isOpened():
        camera = cv2.VideoCapture(index)
    if not camera.isOpened():
        raise RuntimeError("Could not open camera. Allow Terminal in System Settings > Privacy & Security > Camera.")
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    camera.set(cv2.CAP_PROP_FPS, 30)
    return camera



def add_completed_value(
    db: WorkoutDatabase,
    session_id: int,
    profile: str,
    exercise: str,
    output: TrackerOutput,
    session_counts: dict[str, int],
    today: dict[str, int],
) -> int:
    increment = max(1, int(output.value_increment or 1))
    session_counts[exercise] = session_counts.get(exercise, 0) + increment
    today[exercise] = today.get(exercise, 0) + increment
    db.add_rep(
        session_id,
        profile,
        exercise,
        datetime.now(),
        output.form_score,
        output.rep_rom,
        output.rep_duration,
        value=increment,
        unit=output.unit or EXERCISE_UNITS.get(exercise, "reps"),
        feedback=output.feedback,
    )
    return increment


def main() -> None:
    args = parse_args()
    home = args.home.expanduser()
    model_dir = home / "models"
    data_dir = home / "data"
    reports = home / "reports"
    summaries = data_dir / "session_summaries"
    for directory in (model_dir, data_dir, reports, summaries):
        directory.mkdir(parents=True, exist_ok=True)

    db = WorkoutDatabase(data_dir / "workouts.sqlite3")
    camera = open_camera(args.camera)

    # Use the profile selected in the dashboard immediately. No face scan delay.
    profile = (args.profile or "User").strip() or "User"
    db.ensure_profile(profile)
    if args.exercise == "auto":
        enabled_exercises = db.enabled_exercises(profile)
        if not enabled_exercises:
            raise RuntimeError("No exercises are enabled. Select at least one exercise in the dashboard and save preferences.")
    else:
        # Manual mode makes every exercise available from the keyboard, while
        # preserving the user's preferred dashboard order in the live panel.
        enabled_exercises = db.ordered_exercises(profile)
    goals = db.goals(profile)
    shortcut_map = db.shortcuts(profile)
    key_to_exercise = {str(key).lower(): exercise for exercise, key in shortcut_map.items()}
    period_totals = db.period_overview(profile)
    today = period_totals["today"]
    overall_daily_goal = db.overall_daily_goal(profile)
    historical_bests = db.personal_bests(profile)
    live_bests = dict(historical_bests)

    pose_engine = PoseEngine(model_dir / "pose_landmarker_full.task")
    acceptance = max(45.0, min(85.0, float(args.acceptance))) / 100.0
    trackers = create_trackers(acceptance, enabled_exercises)
    classifier = ExerciseClassifier(enabled_exercises=enabled_exercises)
    router = AutoExerciseRouter()
    gesture_selector = HeadTouchExerciseSelector(tuple(trackers.keys()))
    mode = args.exercise
    manual_exercise: str | None = None

    started_at = datetime.now()
    session_stamp = started_at.strftime("%Y%m%d_%H%M%S")
    summary_path = summaries / f"{profile}_{session_stamp}.json"

    ok, frame = camera.read()
    if not ok:
        raise RuntimeError("Camera opened but did not return a frame.")
    frame = cv2.flip(frame, 1)
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    actual_height, actual_width = frame.shape[:2]
    cv2.resizeWindow(WINDOW_NAME, min(actual_width, 1720), min(actual_height, 970))
    fps = camera.get(cv2.CAP_PROP_FPS)
    if fps < 5 or fps > 90:
        fps = 30.0

    # Version 2.6 deliberately stores no workout video. Only small structured
    # summaries and database events are retained.
    session_id = db.start_session(profile, started_at, None, mode, workout_name=args.workout_name or None)
    stop_flag = data_dir / "stop_request.flag"
    stop_flag.unlink(missing_ok=True)
    start_clock = time.perf_counter()
    last_clock = start_clock
    smoothed_fps = fps
    session_counts = {name: 0 for name in trackers}
    live_counts: dict[str, float] = {name: 0.0 for name in trackers}
    last_period_refresh = 0.0
    active_day = datetime.now().date()

    gesture_hint: str | None = None
    gesture_hint_until = 0.0
    gesture_progress = 0.0
    gesture_contact_side: str | None = None
    gesture_event = ""
    gesture_event_until = 0.0
    celebration_message = ""
    celebration_started = 0.0
    celebration_until = 0.0
    pb_celebrated: set[str] = set()
    goal_celebrated = {
        exercise
        for exercise, goal in goals.items()
        if int(goal) > 0 and int(today.get(exercise, 0)) >= int(goal)
    }
    milestone_levels: dict[str, int] = {exercise: 0 for exercise in trackers}

    def register_achievement(exercise: str, previous_today: int, timestamp: float) -> None:
        nonlocal celebration_message, celebration_started, celebration_until
        current = int(session_counts.get(exercise, 0))
        current_today = int(today.get(exercise, 0))
        previous_pb = int(historical_bests.get(exercise, 0))
        live_bests[exercise] = max(int(live_bests.get(exercise, 0)), current)
        unit = EXERCISE_UNITS.get(exercise, "reps")
        name = DISPLAY_NAMES.get(exercise, exercise)

        message = ""
        if previous_pb > 0 and current > previous_pb and exercise not in pb_celebrated:
            pb_celebrated.add(exercise)
            message = f"NEW PERSONAL BEST - {current}{'s' if unit == 'seconds' else ''} {name}!"

        goal = int(goals.get(exercise, 0))
        if not message and goal > 0 and previous_today < goal <= current_today and exercise not in goal_celebrated:
            goal_celebrated.add(exercise)
            message = f"DAILY GOAL ACHIEVED - {current_today}{'s' if unit == 'seconds' else ''} {name}!"

        if unit == "reps" and current >= 50:
            level = current // 50
            if level > milestone_levels.get(exercise, 0):
                milestone_levels[exercise] = level
                if not message:
                    message = f"{current} {name} MILESTONE!"

        if message:
            celebration_message = message
            celebration_started = timestamp
            celebration_until = timestamp + 3.2

    try:
        while True:
            ok, frame = camera.read()
            if not ok:
                break
            frame = cv2.flip(frame, 1)
            now_clock = time.perf_counter()
            timestamp = now_clock - start_clock
            delta = max(now_clock - last_clock, 1e-4)
            last_clock = now_clock
            smoothed_fps = 0.90 * smoothed_fps + 0.10 * (1.0 / delta)

            current_day = datetime.now().date()
            if current_day != active_day or now_clock - last_period_refresh >= 2.0:
                period_totals = db.period_overview(profile, current_day)
                today = period_totals["today"]
                active_day = current_day
                last_period_refresh = now_clock

            if stop_flag.exists():
                stop_flag.unlink(missing_ok=True)
                break

            pose = pose_engine.process(frame, timestamp)
            display_output: TrackerOutput | None = None
            display_exercise: str | None = manual_exercise
            candidate_name: str | None = None
            candidate_confidence = 0.0

            if pose is not None:
                classification = classifier.update(pose)
                # Show an exercise name only after temporal confirmation. A
                # one-frame candidate remains hidden as ANALYSING so the live
                # screen does not announce the wrong workout.
                candidate_name = classification.exercise
                candidate_confidence = classification.confidence if classification.exercise else 0.0

                if mode == "auto":
                    outputs = {name: tracker.update(pose) for name, tracker in trackers.items()}
                    # Timed holds expose a live fractional timer immediately,
                    # while the database continues to store compact whole seconds.
                    for name, output in outputs.items():
                        if name in TIMED_EXERCISES and output.live_value is not None:
                            live_counts[name] = max(float(session_counts.get(name, 0)), float(output.live_value))
                        else:
                            live_counts[name] = float(session_counts.get(name, 0))
                    active_output = outputs.get(router.active) if router.active else None
                    gesture_allowed = (
                        router.active is None
                        or active_output is None
                        or not active_output.valid_pose
                        or active_output.phase in ("search", "neutral", "position")
                    )
                    gesture_result = gesture_selector.update(pose, timestamp, allowed=gesture_allowed)
                    gesture_progress = gesture_result.progress
                    gesture_contact_side = gesture_result.contact_side
                    if gesture_result.event:
                        gesture_hint = gesture_result.selected_exercise
                        gesture_hint_until = timestamp + 6.0
                        gesture_event = gesture_result.event
                        gesture_event_until = timestamp + 2.2
                    elif gesture_hint is not None and timestamp > gesture_hint_until:
                        # A gesture is a temporary routing preference, not a manual lock.
                        # After the lease expires, pure automatic recognition resumes.
                        gesture_hint = None

                    decision = router.update(timestamp, classification, outputs, gesture_hint)

                    completed = [name for name, output in outputs.items() if output.rep_completed]
                    if completed:
                        evidence = router.evidence_scores(classification, outputs, gesture_hint)
                        completed.sort(key=lambda name: evidence.get(name, 0.0), reverse=True)
                        for exercise in completed:
                            timed_direct = (
                                exercise in TIMED_EXERCISES
                                and outputs[exercise].valid_pose
                                and (
                                    router.active in (None, exercise)
                                    or gesture_hint == exercise
                                    or classification.exercise == exercise
                                    or classification.candidate == exercise
                                    or len(completed) == 1
                                )
                            )
                            if timed_direct or router.accept_completed_rep(exercise, timestamp, classification, outputs, gesture_hint):
                                previous_today = int(today.get(exercise, 0))
                                increment = add_completed_value(
                                    db,
                                    session_id,
                                    profile,
                                    exercise,
                                    outputs[exercise],
                                    session_counts,
                                    today,
                                )
                                for period in ("week", "month", "year", "all"):
                                    period_totals[period][exercise] = period_totals[period].get(exercise, 0) + increment
                                live_counts[exercise] = max(
                                    float(session_counts.get(exercise, 0)),
                                    float(outputs[exercise].live_value or 0.0),
                                )
                                register_achievement(exercise, previous_today, timestamp)
                                break

                    # A valid timed hold becomes visible immediately, before
                    # the first whole second is saved to the database.
                    timed_holding = [
                        name for name, output in outputs.items()
                        if name in TIMED_EXERCISES and output.phase == "holding" and output.valid_pose
                    ]
                    if timed_holding:
                        timed_holding.sort(key=lambda name: outputs[name].confidence, reverse=True)
                        router.active = timed_holding[0]
                        router.last_active_evidence = timestamp

                    display_exercise = router.active or classification.exercise or gesture_hint
                    if display_exercise is not None and display_exercise in outputs:
                        shown_value = live_counts.get(display_exercise, float(session_counts.get(display_exercise, 0)))
                        display_output = replace(
                            outputs[display_exercise],
                            reps=int(shown_value),
                            live_value=shown_value if display_exercise in TIMED_EXERCISES else None,
                        )
                        draw_pose(
                            frame,
                            pose,
                            pose_engine.connections,
                            display_output.active_landmarks,
                            display_output.valid_pose,
                        )
                    else:
                        draw_pose(frame, pose, pose_engine.connections, (), False)
                elif manual_exercise is not None:
                    output = trackers[manual_exercise].update(pose)
                    if manual_exercise in TIMED_EXERCISES and output.live_value is not None:
                        live_counts[manual_exercise] = max(
                            float(session_counts.get(manual_exercise, 0)),
                            float(output.live_value),
                        )
                    else:
                        live_counts[manual_exercise] = float(session_counts.get(manual_exercise, 0))
                    if output.rep_completed:
                        previous_today = int(today.get(manual_exercise, 0))
                        increment = add_completed_value(
                            db,
                            session_id,
                            profile,
                            manual_exercise,
                            output,
                            session_counts,
                            today,
                        )
                        for period in ("week", "month", "year", "all"):
                            period_totals[period][manual_exercise] = period_totals[period].get(manual_exercise, 0) + increment
                        live_counts[manual_exercise] = max(
                            float(session_counts.get(manual_exercise, 0)),
                            float(output.live_value or 0.0),
                        )
                        register_achievement(manual_exercise, previous_today, timestamp)
                    shown_value = live_counts.get(manual_exercise, float(session_counts.get(manual_exercise, 0)))
                    display_output = replace(
                        output,
                        reps=int(shown_value),
                        live_value=shown_value if manual_exercise in TIMED_EXERCISES else None,
                    )
                    display_exercise = manual_exercise
                    draw_pose(frame, pose, pose_engine.connections, output.active_landmarks, output.valid_pose)
                else:
                    # Manual mode is intentionally idle until a keyboard shortcut
                    # selects an exercise.
                    display_exercise = None
                    display_output = None
                    candidate_name = None
                    candidate_confidence = 0.0
                    draw_pose(frame, pose, pose_engine.connections, (), False)

            current_event = gesture_event if timestamp <= gesture_event_until else ""
            current_celebration = celebration_message if timestamp <= celebration_until else ""
            celebration_progress = (
                max(0.0, min(1.0, (timestamp - celebration_started) / max(celebration_until - celebration_started, 0.01)))
                if current_celebration
                else 0.0
            )
            draw_dashboard(
                frame,
                display_output,
                profile,
                mode,
                candidate_name,
                candidate_confidence,
                period_totals,
                goals,
                live_counts,
                display_exercise,
                smoothed_fps,
                "NO VIDEO",
                acceptance,
                tuple(trackers.keys()),
                overall_daily_goal,
                live_bests,
                gesture_hint,
                current_event,
                gesture_progress,
                gesture_contact_side,
                current_celebration,
                celebration_progress,
                shortcut_map,
            )
            cv2.imshow(WINDOW_NAME, frame)

            key = cv2.waitKey(1) & 0xFF
            char = chr(key).lower() if 0 <= key < 256 else ""
            if char == "0":
                mode = "auto"
                manual_exercise = None
                classifier.reset()
                router.reset()
                gesture_selector.clear()
                gesture_hint = None
                gesture_hint_until = 0.0
                gesture_progress = 0.0
                gesture_contact_side = None
                for tracker in trackers.values():
                    tracker.reset()
            elif char == "m":
                mode = "manual"
                manual_exercise = None
                classifier.reset()
                router.reset()
                gesture_selector.clear()
                gesture_hint = None
                gesture_hint_until = 0.0
                gesture_progress = 0.0
                gesture_contact_side = None
                for tracker in trackers.values():
                    tracker.reset()
            elif char in key_to_exercise and key_to_exercise[char] in trackers:
                mode = "manual"
                manual_exercise = key_to_exercise[char]
                classifier.reset()
                router.reset()
                gesture_selector.clear()
                gesture_hint = None
                gesture_hint_until = 0.0
                gesture_progress = 0.0
                gesture_contact_side = None
                trackers[manual_exercise].reset()
            elif char == "x" and display_exercise:
                trackers[display_exercise].reset()
                classifier.reset()
                router.reset()
            elif char == "t":
                levels = [0.50, 0.60, 0.70, 0.80]
                acceptance = next((level for level in levels if level > acceptance + 0.01), levels[0])
                for tracker in trackers.values():
                    tracker.set_quality_threshold(acceptance)
            elif char == "d":
                build_dashboard(db, profile, reports, open_browser=True)
            elif char == "q" or key == 27:
                break
    finally:
        ended_at = datetime.now()
        db.finish_session(session_id, ended_at)
        camera.release()
        pose_engine.close()
        cv2.destroyAllWindows()
        summary = {
            "profile": profile,
            "started_at": started_at.isoformat(timespec="seconds"),
            "ended_at": ended_at.isoformat(timespec="seconds"),
            "duration_seconds": round((ended_at - started_at).total_seconds(), 1),
            "mode": mode,
            "session_counts": session_counts,
            "units": {exercise: EXERCISE_UNITS[exercise] for exercise in session_counts},
            "today_totals": period_totals.get("today", today),
            "period_totals": period_totals,
            "workout_name": args.workout_name or None,
            "video_file": None,
            "database": str(db.path),
            "movement_acceptance_percent": round(acceptance * 100),
            "enabled_exercises": list(trackers),
            "overall_daily_goal": overall_daily_goal,
            "personal_bests": live_bests,
        }
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        try:
            export_result = auto_export(db, profile, home)
            if export_result is not None:
                summary["automatic_export"] = export_result
                summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        except Exception as exc:
            summary["automatic_export_error"] = str(exc)
            summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
