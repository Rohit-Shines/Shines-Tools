from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_SETTINGS: dict[str, Any] = {
    "cloud_sync_dir": "",
    "auto_export_after_workout": True,
    "webhook_url": "",
    "webhook_token": "",
    "default_profile": "User",
    "default_tolerance": 60,
    "default_camera": 0,
    "default_mode": "auto",
    "record_video": False,
    "reminder_enabled": False,
    "reminder_interval_minutes": 30,
    "reminder_exercise": "pushup",
    "reminder_active_start": "08:00",
    "reminder_active_end": "21:00",
    "reminder_snooze_minutes": 10,
    "reminder_sound": "Glass",
}


class AppSettings:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        data = dict(DEFAULT_SETTINGS)
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    data.update(raw)
            except (OSError, json.JSONDecodeError):
                pass
        return data

    def save(self, values: dict[str, Any]) -> dict[str, Any]:
        data = self.load()
        for key in DEFAULT_SETTINGS:
            if key in values:
                data[key] = values[key]
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temp.replace(self.path)
        return data

    def update(self, **values: Any) -> dict[str, Any]:
        return self.save(values)
