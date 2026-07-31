#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from workout_ai.constants import DISPLAY_NAMES
from workout_ai.settings import AppSettings


def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    temp.replace(path)


def within_hours(now: datetime, start: str, end: str) -> bool:
    try:
        sh, sm = (int(value) for value in start.split(":", 1))
        eh, em = (int(value) for value in end.split(":", 1))
    except Exception:
        return True
    minute = now.hour * 60 + now.minute
    low, high = sh * 60 + sm, eh * 60 + em
    return low <= minute <= high if low <= high else minute >= low or minute <= high


def _launch_workout(home: Path) -> None:
    system = platform.system()
    if system == "Darwin":
        subprocess.Popen(["open", str(Path.home() / "Applications" / "Workout Version 3.app")])
    elif system == "Windows":
        launcher = home / "Start Workout Version 3.bat"
        if launcher.exists():
            os.startfile(str(launcher))  # type: ignore[attr-defined]


def _mac_prompt(name: str, snooze: int, sound: str, home: Path) -> str:
    sound_path = Path("/System/Library/Sounds") / f"{sound}.aiff"
    if sound_path.exists():
        subprocess.Popen(["afplay", str(sound_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    applescript = (
        f'display dialog "Time for a movement break: {name}." '
        f'with title "Workout Version 3 Reminder" '
        f'buttons {{"Dismiss", "Snooze {snooze} min", "Launch Workout"}} '
        f'default button "Launch Workout" with icon note giving up after 60'
    )
    result = subprocess.run(["osascript", "-e", applescript], capture_output=True, text=True)
    output = (result.stdout or "").strip()
    if "Launch Workout" in output:
        _launch_workout(home)
        return "launch"
    if "Snooze" in output:
        return "snooze"
    return "dismiss"


def _windows_prompt(name: str, snooze: int, home: Path) -> str:
    # Yes = launch, No = snooze, Cancel = dismiss.
    script = rf"""
Add-Type -AssemblyName PresentationFramework
[System.Media.SystemSounds]::Exclamation.Play()
$result = [System.Windows.MessageBox]::Show(
  "Time for a movement break: {name}.`n`nYes = Launch workout`nNo = Snooze {snooze} minutes`nCancel = Dismiss",
  "Workout Version 3 Reminder",
  "YesNoCancel",
  "Information"
)
Write-Output $result
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
    )
    answer = (result.stdout or "").strip().lower()
    if "yes" in answer:
        _launch_workout(home)
        return "launch"
    if "no" in answer:
        return "snooze"
    return "dismiss"


def show_prompt(exercise: str, snooze: int, sound: str, home: Path) -> str:
    name = DISPLAY_NAMES.get(exercise, exercise.replace("_", " ").title())
    system = platform.system()
    if system == "Darwin":
        return _mac_prompt(name, snooze, sound, home)
    if system == "Windows":
        return _windows_prompt(name, snooze, home)
    return "dismiss"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path, required=True)
    args = parser.parse_args()
    home = args.home.expanduser().resolve()
    settings = AppSettings(home / "data" / "settings.json").load()
    if not bool(settings.get("reminder_enabled", False)):
        return

    now = datetime.now()
    if not within_hours(
        now,
        str(settings.get("reminder_active_start", "08:00")),
        str(settings.get("reminder_active_end", "21:00")),
    ):
        return

    state_path = home / "data" / "reminder_state.json"
    state = load_state(state_path)
    interval = max(5, int(settings.get("reminder_interval_minutes", 30)))
    snooze = max(1, int(settings.get("reminder_snooze_minutes", 10)))
    due_timestamp = float(state.get("next_due_ts", 0) or 0)

    if due_timestamp <= 0:
        state["next_due_ts"] = (now + timedelta(minutes=interval)).timestamp()
        save_state(state_path, state)
        return
    if now.timestamp() < due_timestamp:
        return

    action = show_prompt(
        str(settings.get("reminder_exercise", "pushup")),
        snooze,
        str(settings.get("reminder_sound", "Glass")),
        home,
    )
    delay = snooze if action == "snooze" else interval
    state.update(
        {
            "last_action": action,
            "last_alert_ts": now.timestamp(),
            "next_due_ts": (now + timedelta(minutes=delay)).timestamp(),
        }
    )
    save_state(state_path, state)


if __name__ == "__main__":
    main()
