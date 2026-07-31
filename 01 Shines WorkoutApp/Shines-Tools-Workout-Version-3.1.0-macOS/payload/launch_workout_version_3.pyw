from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    home = Path(__file__).resolve().parent
    python = home / ".venv" / "Scripts" / "python.exe"
    gui = home / "workout_gui.py"
    log = home / "logs" / "windows_launcher.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    if not python.exists() or not gui.exists():
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, "Workout Version 3 is incomplete. Re-run the installer.", "Workout Version 3", 0x10)
        return
    env = os.environ.copy()
    env["PYTHONPATH"] = str(home)
    env["PYTHONUNBUFFERED"] = "1"
    with log.open("a", encoding="utf-8") as stream:
        subprocess.Popen(
            [str(python), str(gui), "--home", str(home), "--port", "8793"],
            cwd=home,
            env=env,
            stdout=stream,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )


if __name__ == "__main__":
    main()
