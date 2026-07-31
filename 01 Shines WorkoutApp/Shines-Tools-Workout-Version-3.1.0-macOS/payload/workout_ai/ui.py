from __future__ import annotations

import random
from typing import Iterable

import cv2

from .constants import DISPLAY_NAMES, EXERCISE_UNITS, REP_EXERCISES, TIMED_EXERCISES
from .geometry import PoseFrame
from .exercises import TrackerOutput


RED = (70, 70, 255)
GREEN = (70, 225, 90)
BLUE = (255, 165, 65)
WHITE = (245, 245, 245)
MUTED = (175, 185, 195)
AMBER = (60, 205, 255)


def draw_pose(frame, pose: PoseFrame, connections, active: Iterable[int], valid: bool) -> None:
    height, width = frame.shape[:2]
    active_set = set(active)
    line_color = GREEN if valid else (0, 170, 255)
    for connection in connections:
        start, end = int(connection.start), int(connection.end)
        if pose.image[start].visibility < 0.42 or pose.image[end].visibility < 0.42:
            continue
        a = (int(pose.image[start].x * width), int(pose.image[start].y * height))
        b = (int(pose.image[end].x * width), int(pose.image[end].y * height))
        color = line_color if start in active_set or end in active_set else (95, 95, 95)
        thickness = 4 if start in active_set and end in active_set else 2
        cv2.line(frame, a, b, color, thickness, cv2.LINE_AA)
    for idx, landmark in enumerate(pose.image):
        if landmark.visibility < 0.42:
            continue
        center = (int(landmark.x * width), int(landmark.y * height))
        if idx in active_set:
            color, radius = (GREEN if valid else (0, 170, 255)), 7
        else:
            color, radius = (210, 210, 210), 3
        cv2.circle(frame, center, radius, color, -1, cv2.LINE_AA)


def _goal_color(value: int, goal: int):
    if goal <= 0:
        return WHITE
    if value < goal:
        return RED
    if value == goal:
        return GREEN
    return BLUE


def _format_value(exercise: str, value: float | int) -> str:
    if EXERCISE_UNITS.get(exercise) == "seconds":
        number = float(value)
        if abs(number - round(number)) < 0.04:
            return f"{int(round(number))}s"
        return f"{number:.1f}s"
    return str(int(round(float(value))))


def progress_bar(frame, x: int, y: int, width: int, height: int, progress: float, color=GREEN) -> None:
    progress = max(0.0, min(1.0, progress))
    cv2.rectangle(frame, (x, y), (x + width, y + height), (85, 85, 85), 1)
    cv2.rectangle(
        frame,
        (x + 2, y + 2),
        (x + 2 + int((width - 4) * progress), y + height - 2),
        color,
        -1,
    )


def _fit_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max(1, max_chars - 1)] + "…"


def _selector_neighbors(enabled_exercises: tuple[str, ...], selected: str | None) -> tuple[str | None, str | None, str | None]:
    rows = tuple(enabled_exercises)
    if not rows or selected not in rows:
        return None, selected, None
    index = rows.index(selected)
    return rows[(index - 1) % len(rows)], selected, rows[(index + 1) % len(rows)]


def draw_totals_panel(
    frame,
    period_totals: dict[str, dict[str, int]],
    goals: dict[str, int],
    count_values: dict[str, int],
    active_exercise: str | None,
    enabled_exercises: tuple[str, ...],
    personal_bests: dict[str, int] | None = None,
    gesture_hint: str | None = None,
) -> None:
    height, width = frame.shape[:2]
    panel_width = 430
    x0 = max(0, width - panel_width)
    y0 = 160
    overlay = frame.copy()
    cv2.rectangle(overlay, (x0, y0), (width, height), (8, 12, 18), -1)
    cv2.addWeighted(overlay, 0.82, frame, 0.18, 0, frame)

    today_totals = period_totals.get("today", {})
    personal_bests = personal_bests or {}
    cv2.putText(frame, "WORKOUT COUNTS", (x0 + 14, y0 + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.62, WHITE, 2, cv2.LINE_AA)
    cv2.putText(frame, "Exercise", (x0 + 14, y0 + 52), cv2.FONT_HERSHEY_SIMPLEX, 0.40, MUTED, 1, cv2.LINE_AA)
    cv2.putText(frame, "Count", (x0 + 214, y0 + 52), cv2.FONT_HERSHEY_SIMPLEX, 0.40, MUTED, 1, cv2.LINE_AA)
    cv2.putText(frame, "PB", (x0 + 282, y0 + 52), cv2.FONT_HERSHEY_SIMPLEX, 0.40, AMBER, 1, cv2.LINE_AA)
    cv2.putText(frame, "Today / Goal", (x0 + 330, y0 + 52), cv2.FONT_HERSHEY_SIMPLEX, 0.36, MUTED, 1, cv2.LINE_AA)

    rows = enabled_exercises or ("pushup",)
    usable = max(300, height - y0 - 145)
    row_height = max(25, min(38, int(usable / max(len(rows), 1))))
    y = y0 + 76
    for exercise in rows:
        active = exercise == active_exercise
        hinted = exercise == gesture_hint
        if active:
            cv2.rectangle(frame, (x0 + 7, y - 21), (width - 7, y + 8), (42, 76, 48), -1)
            marker_color = GREEN
        elif hinted:
            cv2.rectangle(frame, (x0 + 7, y - 21), (width - 7, y + 8), AMBER, 2)
            marker_color = AMBER
        else:
            marker_color = (110, 120, 130)
        cv2.circle(frame, (x0 + 16, y - 6), 4, marker_color, -1, cv2.LINE_AA)
        label = _fit_text(DISPLAY_NAMES[exercise], 19)
        cv2.putText(frame, label, (x0 + 28, y), cv2.FONT_HERSHEY_SIMPLEX, 0.39, WHITE, 1, cv2.LINE_AA)

        count = float(count_values.get(exercise, 0))
        today = int(today_totals.get(exercise, 0))
        goal = int(goals.get(exercise, 0))
        historic_pb = int(personal_bests.get(exercise, 0))
        live_pb = max(historic_pb, count)
        color = _goal_color(today, goal)
        count_color = BLUE if count > historic_pb and count > 0 else (100, 220, 255)
        cv2.putText(frame, _format_value(exercise, count), (x0 + 214, y), cv2.FONT_HERSHEY_SIMPLEX, 0.44, count_color, 2, cv2.LINE_AA)
        cv2.putText(frame, _format_value(exercise, live_pb), (x0 + 282, y), cv2.FONT_HERSHEY_SIMPLEX, 0.40, AMBER, 1, cv2.LINE_AA)
        cv2.putText(
            frame,
            f"{_format_value(exercise, today)}/{_format_value(exercise, goal)}",
            (x0 + 330, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.35,
            color,
            1,
            cv2.LINE_AA,
        )
        y += row_height

    trend_exercise = active_exercise if active_exercise in rows else rows[0]
    trend_y = min(height - 68, y + 4)
    if trend_y - 20 > y0 + 70:
        cv2.line(frame, (x0 + 12, trend_y - 18), (width - 12, trend_y - 18), (85, 95, 105), 1)
        labels = (("W", "week"), ("M", "month"), ("Y", "year"), ("ALL", "all"))
        positions = (x0 + 18, x0 + 112, x0 + 208, x0 + 312)
        for (short, period), x in zip(labels, positions):
            value = int(period_totals.get(period, {}).get(trend_exercise, 0))
            cv2.putText(frame, short, (x, trend_y + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.34, MUTED, 1, cv2.LINE_AA)
            cv2.putText(frame, _format_value(trend_exercise, value), (x, trend_y + 29), cv2.FONT_HERSHEY_SIMPLEX, 0.49, WHITE, 2, cv2.LINE_AA)


def draw_celebration(frame, message: str, progress: float) -> None:
    """Lightweight in-camera celebration; no media assets or video files."""
    height, width = frame.shape[:2]
    progress = max(0.0, min(1.0, progress))
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, int(height * 0.30)), (width, int(height * 0.67)), (10, 15, 28), -1)
    cv2.addWeighted(overlay, 0.72, frame, 0.28, 0, frame)
    rng = random.Random(int(progress * 10_000) + len(message) * 97)
    palette = (RED, GREEN, BLUE, AMBER, (255, 80, 220), (255, 255, 255))
    for _ in range(75):
        x = rng.randint(10, max(11, width - 10))
        y = rng.randint(int(height * 0.18), int(height * 0.78))
        radius = rng.randint(2, 6)
        cv2.circle(frame, (x, y), radius, palette[rng.randrange(len(palette))], -1, cv2.LINE_AA)
    cv2.putText(frame, "ACHIEVEMENT UNLOCKED", (max(22, width // 2 - 245), int(height * 0.43)), cv2.FONT_HERSHEY_SIMPLEX, 0.95, AMBER, 3, cv2.LINE_AA)
    cv2.putText(frame, _fit_text(message, 55), (max(22, width // 2 - 275), int(height * 0.53)), cv2.FONT_HERSHEY_SIMPLEX, 0.78, WHITE, 2, cv2.LINE_AA)
    cv2.putText(frame, "KEEP GOING!", (max(22, width // 2 - 110), int(height * 0.61)), cv2.FONT_HERSHEY_SIMPLEX, 0.70, GREEN, 2, cv2.LINE_AA)


def draw_dashboard(
    frame,
    output: TrackerOutput | None,
    profile: str,
    mode: str,
    classification_name: str | None,
    classification_confidence: float,
    period_totals: dict[str, dict[str, int]],
    goals: dict[str, int],
    count_values: dict[str, int],
    active_exercise: str | None,
    fps: float,
    recording_name: str,
    acceptance: float,
    enabled_exercises: tuple[str, ...],
    overall_daily_goal: int,
    personal_bests: dict[str, int] | None = None,
    gesture_hint: str | None = None,
    gesture_event: str | None = None,
    gesture_progress: float = 0.0,
    gesture_contact_side: str | None = None,
    celebration_message: str | None = None,
    celebration_progress: float = 0.0,
    shortcut_map: dict[str, str] | None = None,
) -> None:
    height, width = frame.shape[:2]
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (width, 160), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.68, frame, 0.32, 0, frame)

    today_totals = period_totals.get("today", {})
    today_rep_total = sum(int(today_totals.get(exercise, 0)) for exercise in REP_EXERCISES)
    overall_color = _goal_color(today_rep_total, overall_daily_goal)

    if output is None:
        if mode == "manual":
            title = "MANUAL MODE: PRESS AN EXERCISE KEY"
            shortcut_map = shortcut_map or {}
            priority = ["pushup", "squat", "shoulder_press", "curl", "taekwondo_kick"]
            feedback = " | ".join(
                f"{shortcut_map.get(exercise, '?')} {DISPLAY_NAMES[exercise]}" for exercise in priority
            )
        else:
            title = "TRACKING: ANALYSING MOVEMENT"
            feedback = "Start an enabled exercise; the name appears only after confirmation"
        current_count, phase, score = 0, "search", 0.0
        metric = ""
        today_active = 0
        count_text = "0"
    else:
        title = f"TRACKING: {DISPLAY_NAMES[output.exercise].upper()}"
        current_count = output.live_value if output.live_value is not None else output.reps
        phase, feedback, score = output.phase, output.feedback, output.form_score
        today_active = int(today_totals.get(output.exercise, 0))
        count_text = _format_value(output.exercise, current_count)
        if output.metric_value is None:
            metric = ""
        elif any(word in output.metric_name.lower() for word in ("width", "height", "lift")):
            metric = f"{output.metric_name}: {output.metric_value:.1f}"
        else:
            metric = f"{output.metric_name}: {output.metric_value:.0f} deg"

    cv2.putText(frame, title, (22, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.92, WHITE, 2, cv2.LINE_AA)
    cv2.putText(
        frame,
        f"{profile}  |  Mode: {mode.upper()}  |  Count: {count_text}  |  Today: {today_active}  |  Phase: {phase}",
        (22, 74),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.54,
        (210, 230, 255),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(frame, _fit_text(feedback, 88), (22, 106), cv2.FONT_HERSHEY_SIMPLEX, 0.60, (80, 230, 255), 2, cv2.LINE_AA)
    form_color = GREEN if score >= acceptance * 100 else (0, 190, 255)
    cv2.putText(
        frame,
        f"Live form {score:.0f}/100  |  T tolerance {acceptance*100:.0f}%  |  {metric}",
        (22, 136),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.48,
        form_color,
        1,
        cv2.LINE_AA,
    )

    if output is not None and output.exercise in TIMED_EXERCISES:
        timer_text = _format_value(output.exercise, current_count)
        timer_x = 24
        timer_y = 194
        overlay_timer = frame.copy()
        cv2.rectangle(overlay_timer, (timer_x, timer_y - 42), (timer_x + 330, timer_y + 82), (7, 23, 35), -1)
        cv2.addWeighted(overlay_timer, 0.78, frame, 0.22, 0, frame)
        cv2.putText(frame, "SECONDS MODE", (timer_x + 14, timer_y - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.55, AMBER, 2, cv2.LINE_AA)
        cv2.putText(frame, timer_text, (timer_x + 14, timer_y + 55), cv2.FONT_HERSHEY_SIMPLEX, 1.65, GREEN if output.phase == "holding" else WHITE, 4, cv2.LINE_AA)
        if output.phase != "holding":
            cv2.putText(frame, "Move into position to start", (timer_x + 14, timer_y + 78), cv2.FONT_HERSHEY_SIMPLEX, 0.38, MUTED, 1, cv2.LINE_AA)

    candidate = "ANALYSING" if not classification_name else DISPLAY_NAMES[classification_name].upper()
    right_x = max(20, width - 430)
    cv2.putText(frame, f"AI: {candidate} {classification_confidence*100:.0f}%", (right_x, 72), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (205, 205, 205), 1, cv2.LINE_AA)
    cv2.putText(frame, f"DAILY COUNT {today_rep_total}/{overall_daily_goal}", (right_x, 103), cv2.FONT_HERSHEY_SIMPLEX, 0.52, overall_color, 2, cv2.LINE_AA)
    selected_for_menu = gesture_hint if gesture_hint in enabled_exercises else (active_exercise if active_exercise in enabled_exercises else None)
    previous_exercise, selected_exercise, next_exercise = _selector_neighbors(enabled_exercises, selected_for_menu)
    selected_name = DISPLAY_NAMES.get(selected_exercise, selected_exercise or "AUTO")
    selector_text = f"LIVE SELECT: {selected_name.upper()}"
    if gesture_event:
        selector_text += f" | {gesture_event}"
    cv2.putText(frame, _fit_text(selector_text, 50), (right_x, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.38, AMBER if gesture_hint else MUTED, 1, cv2.LINE_AA)

    if gesture_contact_side:
        direction_name = "UP / PREVIOUS" if gesture_contact_side == "left" else "DOWN / NEXT"
        cv2.putText(frame, f"{gesture_contact_side.upper()} FACE: {direction_name}", (right_x, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.30, WHITE, 1, cv2.LINE_AA)
        progress_bar(frame, right_x, 153, 300, 5, gesture_progress, AMBER)
    else:
        previous_name = DISPLAY_NAMES.get(previous_exercise, "-")
        next_name = DISPLAY_NAMES.get(next_exercise, "-")
        cv2.putText(frame, _fit_text(f"UP {previous_name} | DOWN {next_name}", 52), (right_x, 151), cv2.FONT_HERSHEY_SIMPLEX, 0.30, MUTED, 1, cv2.LINE_AA)

    cv2.putText(frame, f"NO VIDEO | {fps:.0f} FPS", (max(20, width - 245), 34), cv2.FONT_HERSHEY_SIMPLEX, 0.42, MUTED, 2, cv2.LINE_AA)

    draw_totals_panel(frame, period_totals, goals, count_values, active_exercise, enabled_exercises, personal_bests, gesture_hint)
    shortcut_map = shortcut_map or {}
    priority = ("pushup", "squat", "shoulder_press", "curl", "taekwondo_kick", "plank", "squat_hold")
    shortcut_text = " | ".join(
        f"{shortcut_map.get(exercise, '?')} {DISPLAY_NAMES[exercise]}" for exercise in priority
    )
    cv2.putText(
        frame,
        _fit_text(f"0 Auto | M Manual | {shortcut_text} | X Reset | D Report | Q Quit", 170),
        (20, height - 18),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.31,
        WHITE,
        1,
        cv2.LINE_AA,
    )

    if celebration_message:
        draw_celebration(frame, celebration_message, celebration_progress)
