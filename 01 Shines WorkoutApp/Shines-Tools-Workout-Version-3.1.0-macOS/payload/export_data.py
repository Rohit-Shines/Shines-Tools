#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from workout_ai.constants import DEFAULT_HOME
from workout_ai.database import WorkoutDatabase
from workout_ai.exporter import export_profile
from workout_ai.settings import AppSettings

parser = argparse.ArgumentParser(description="Export workout history to portable formats")
parser.add_argument("--home", type=Path, default=Path(os.environ.get("WORKOUT_HOME", DEFAULT_HOME)))
parser.add_argument("--profile", default="User")
args = parser.parse_args()
settings = AppSettings(args.home / "data" / "settings.json").load()
db = WorkoutDatabase(args.home / "data" / "workouts.sqlite3")
result = export_profile(
    db,
    args.profile,
    args.home,
    cloud_sync_dir=settings.get("cloud_sync_dir") or None,
    webhook_url=str(settings.get("webhook_url") or ""),
    webhook_token=str(settings.get("webhook_token") or ""),
)
print(json.dumps(result, indent=2))
