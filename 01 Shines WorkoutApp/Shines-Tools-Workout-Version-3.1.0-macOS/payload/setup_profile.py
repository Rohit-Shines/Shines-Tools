#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from workout_ai.database import WorkoutDatabase
from workout_ai.settings import AppSettings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--profile", default="User")
    args = parser.parse_args()
    home = args.home.expanduser().resolve()
    profile = args.profile.strip() or "User"
    (home / "data").mkdir(parents=True, exist_ok=True)
    db = WorkoutDatabase(home / "data" / "workouts.sqlite3")
    db.ensure_profile(profile)
    AppSettings(home / "data" / "settings.json").update(
        default_profile=profile,
        default_tolerance=60,
        default_camera=0,
        default_mode="auto",
        record_video=False,
    )
    print(f"Profile ready: {profile}")


if __name__ == "__main__":
    main()
