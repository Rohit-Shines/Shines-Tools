#!/usr/bin/env python3
from __future__ import annotations

import importlib
import os
import platform
import sqlite3
import sys
from pathlib import Path


def main() -> None:
    home = Path(os.environ.get("WORKOUT_HOME", Path(__file__).resolve().parent)).resolve()
    print("Workout Version 3 diagnostics")
    print("Home:", home)
    print("OS:", platform.platform())
    print("Python:", sys.version)
    print("Architecture:", platform.machine())
    for module in ("numpy", "cv2", "mediapipe", "matplotlib"):
        try:
            imported = importlib.import_module(module)
            print(module, "OK", getattr(imported, "__version__", ""))
        except Exception as exc:
            print(module, "FAILED", exc)
    model = home / "models" / "pose_landmarker_full.task"
    print("Pose model:", "OK" if model.exists() else "MISSING", model)
    database = home / "data" / "workouts.sqlite3"
    if database.exists():
        try:
            sqlite3.connect(database).execute("PRAGMA integrity_check").fetchone()
            print("Database: OK", database)
        except Exception as exc:
            print("Database: FAILED", exc)
    else:
        print("Database: not created yet")


if __name__ == "__main__":
    main()
