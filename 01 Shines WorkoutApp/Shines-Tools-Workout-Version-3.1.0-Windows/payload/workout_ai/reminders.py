from __future__ import annotations

import os
import platform
import plistlib
import subprocess
from pathlib import Path

MAC_LABEL = "com.shinestools.workoutversion3.reminder"
WINDOWS_TASK = "Shines Tools - Workout Version 3 Reminder"


def _venv_python(home: Path, *, windowless: bool = False) -> Path:
    if os.name == "nt":
        name = "pythonw.exe" if windowless else "python.exe"
        return home / ".venv" / "Scripts" / name
    return home / ".venv" / "bin" / "python"


def _mac_launchagent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{MAC_LABEL}.plist"


def _windows_wrapper_path(home: Path) -> Path:
    return home / "run_reminder_agent.cmd"


def install_reminder_service(home: Path) -> str:
    """Install or refresh the per-user reminder service.

    No administrator rights are required. macOS uses a LaunchAgent and Windows
    uses a per-user Task Scheduler task that runs once per minute.
    """
    home = home.expanduser().resolve()
    system = platform.system()
    (home / "logs").mkdir(parents=True, exist_ok=True)

    if system == "Darwin":
        path = _mac_launchagent_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "Label": MAC_LABEL,
            "ProgramArguments": [
                str(_venv_python(home)),
                str(home / "reminder_agent.py"),
                "--home",
                str(home),
            ],
            "StartInterval": 60,
            "RunAtLoad": True,
            "ProcessType": "Background",
            "StandardOutPath": str(home / "logs" / "reminder_agent.log"),
            "StandardErrorPath": str(home / "logs" / "reminder_agent.log"),
        }
        path.write_bytes(plistlib.dumps(payload))
        uid = str(os.getuid())
        subprocess.run(
            ["launchctl", "bootout", f"gui/{uid}", str(path)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(path)], check=False)
        subprocess.run(["launchctl", "enable", f"gui/{uid}/{MAC_LABEL}"], check=False)
        return str(path)

    if system == "Windows":
        wrapper = _windows_wrapper_path(home)
        pythonw = _venv_python(home, windowless=True)
        wrapper.write_text(
            "@echo off\r\n"
            f'"{pythonw}" "{home / "reminder_agent.py"}" --home "{home}"\r\n',
            encoding="utf-8",
        )
        task_command = f'"{wrapper}"'
        result = subprocess.run(
            [
                "schtasks.exe",
                "/Create",
                "/TN",
                WINDOWS_TASK,
                "/SC",
                "MINUTE",
                "/MO",
                "1",
                "/TR",
                task_command,
                "/F",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "Task Scheduler setup failed").strip())
        return WINDOWS_TASK

    raise RuntimeError(f"Background reminders are not supported on {system}.")


def uninstall_reminder_service(home: Path | None = None) -> None:
    system = platform.system()
    if system == "Darwin":
        path = _mac_launchagent_path()
        uid = str(os.getuid())
        subprocess.run(
            ["launchctl", "bootout", f"gui/{uid}", str(path)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        path.unlink(missing_ok=True)
        return
    if system == "Windows":
        subprocess.run(
            ["schtasks.exe", "/Delete", "/TN", WINDOWS_TASK, "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if home is not None:
            _windows_wrapper_path(home).unlink(missing_ok=True)


def reminder_status() -> dict[str, object]:
    system = platform.system()
    if system == "Darwin":
        path = _mac_launchagent_path()
        return {"installed": path.exists(), "platform": "macOS", "path": str(path)}
    if system == "Windows":
        result = subprocess.run(
            ["schtasks.exe", "/Query", "/TN", WINDOWS_TASK],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return {"installed": result.returncode == 0, "platform": "Windows", "path": WINDOWS_TASK}
    return {"installed": False, "platform": system, "path": ""}


# Backward-compatible aliases for older local patches.
install_launchagent = install_reminder_service
uninstall_launchagent = uninstall_reminder_service
