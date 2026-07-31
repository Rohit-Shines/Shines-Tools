from __future__ import annotations

import csv
import json
import shutil
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .constants import DISPLAY_NAMES, EXERCISES, EXERCISE_UNITS, REP_EXERCISES, TIMED_EXERCISES
from .database import WorkoutDatabase
from .settings import AppSettings

SCHEMA_VERSION = "2.5"


def _safe_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in value.strip())
    return cleaned or "profile"


def _rows_to_dicts(rows: Iterable[Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _daily_rows(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for event in events:
        day = str(event["occurred_at"])[:10]
        key = (day, str(event["exercise"]))
        item = grouped.setdefault(
            key,
            {"date": day, "exercise": event["exercise"], "display_name": DISPLAY_NAMES.get(event["exercise"], event["exercise"]), "value": 0, "unit": event.get("unit") or EXERCISE_UNITS.get(event["exercise"], "reps"), "avg_form_score": None},
        )
        item["value"] += int(event.get("value") or 1)
    form_values: dict[tuple[str, str], list[float]] = defaultdict(list)
    for event in events:
        if event.get("form_score") is not None:
            form_values[(str(event["occurred_at"])[:10], str(event["exercise"]))].append(float(event["form_score"]))
    for key, values in form_values.items():
        if key in grouped and values:
            grouped[key]["avg_form_score"] = round(sum(values) / len(values), 2)
    return sorted(grouped.values(), key=lambda row: (row["date"], row["exercise"]))


def _session_rep_counts(events: list[dict[str, Any]]) -> dict[int, dict[str, int]]:
    result: dict[int, dict[str, int]] = defaultdict(lambda: {exercise: 0 for exercise in EXERCISES})
    for event in events:
        result[int(event["session_id"])][str(event["exercise"])] += int(event.get("value") or 1)
    return dict(result)


def _apple_health_bridge(profile: str, sessions: list[dict[str, Any]], rep_counts: dict[int, dict[str, int]]) -> dict[str, Any]:
    workouts: list[dict[str, Any]] = []
    for session in sessions:
        counts = rep_counts.get(int(session["id"]), {exercise: 0 for exercise in EXERCISES})
        total = sum(counts.values())
        if total <= 0:
            continue
        start = session.get("started_at")
        end = session.get("ended_at") or start
        workouts.append(
            {
                "externalId": f"rohit-workout-session-{session['id']}",
                "activityType": "traditionalStrengthTraining",
                "startDate": start,
                "endDate": end,
                "workoutName": session.get("workout_name") or "AI Strength Workout",
                "source": "Workout Version 3",
                "metadata": {
                    "profile": profile,
                    "mode": session.get("mode"),
                    "totalRepetitions": sum(counts.get(e,0) for e in REP_EXERCISES),
                    "totalTimedSeconds": sum(counts.get(e,0) for e in TIMED_EXERCISES),
                    "repetitionsByExercise": {e: counts.get(e,0) for e in REP_EXERCISES},
                    "secondsByExercise": {e: counts.get(e,0) for e in TIMED_EXERCISES},
                    "videoPath": session.get("video_path"),
                    "schemaVersion": SCHEMA_VERSION,
                },
            }
        )
    return {
        "schema": "com.workoutai.healthkit.bridge.v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "profile": profile,
        "note": "Import through a signed iPhone/watchOS HealthKit companion. macOS cannot write to the HealthKit store.",
        "workouts": workouts,
    }


def _fhir_bundle(profile: str, sessions: list[dict[str, Any]], rep_counts: dict[int, dict[str, int]]) -> dict[str, Any]:
    patient_id = f"profile-{_safe_name(profile).lower()}"
    entries: list[dict[str, Any]] = [
        {
            "fullUrl": f"urn:uuid:{patient_id}",
            "resource": {
                "resourceType": "Patient",
                "id": patient_id,
                "identifier": [{"system": "urn:rohit-workout-ai:profile", "value": profile}],
                "name": [{"text": profile}],
            },
        }
    ]
    for session in sessions:
        counts = rep_counts.get(int(session["id"]), {})
        if not counts or sum(counts.values()) == 0:
            continue
        procedure_id = f"workout-{session['id']}"
        entries.append(
            {
                "fullUrl": f"urn:uuid:{procedure_id}",
                "resource": {
                    "resourceType": "Procedure",
                    "id": procedure_id,
                    "status": "completed" if session.get("ended_at") else "in-progress",
                    "code": {
                        "coding": [{"system": "urn:rohit-workout-ai:activity", "code": "strength-workout", "display": "Strength workout"}],
                        "text": session.get("workout_name") or "AI Strength Workout",
                    },
                    "subject": {"reference": f"Patient/{patient_id}"},
                    "performedPeriod": {"start": session.get("started_at"), "end": session.get("ended_at") or session.get("started_at")},
                    "extension": [
                        {
                            "url": "urn:rohit-workout-ai:repetitions",
                            "extension": [
                                {"url": exercise, "valueInteger": int(count)}
                                for exercise, count in counts.items()
                                if count
                            ],
                        }
                    ],
                },
            }
        )
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "meta": {"tag": [{"system": "urn:rohit-workout-ai:schema", "code": SCHEMA_VERSION}]},
        "entry": entries,
    }


def _post_webhook(url: str, token: str, payload: dict[str, Any]) -> str | None:
    if not url:
        return None
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "Workout-AI/2.4"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            return f"HTTP {response.status}"
    except Exception as exc:  # Network sync must never break local workout saving.
        return f"Failed: {exc}"


def export_profile(
    db: WorkoutDatabase,
    profile: str,
    home: Path,
    *,
    cloud_sync_dir: str | Path | None = None,
    webhook_url: str = "",
    webhook_token: str = "",
) -> dict[str, Any]:
    home = home.expanduser()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    profile_key = _safe_name(profile)
    output_dir = home / "exports" / profile_key / stamp
    output_dir.mkdir(parents=True, exist_ok=True)

    sessions = _rows_to_dicts(db.all_sessions(profile))
    events = _rows_to_dicts(db.all_rep_events(profile))
    daily = _daily_rows(events)
    rep_counts = _session_rep_counts(events)
    summary = db.summary(profile)

    full_payload = {
        "schema": "com.workoutai.export.v2",
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "profile": profile,
        "summary": summary,
        "goals": db.goals(profile),
        "sessions": sessions,
        "repEvents": events,
        "dailySummary": daily,
    }
    (output_dir / "workout_data.json").write_text(json.dumps(full_payload, indent=2), encoding="utf-8")
    with (output_dir / "rep_events.ndjson").open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, separators=(",", ":")) + "\n")

    _write_csv(
        output_dir / "sessions.csv",
        sessions,
        ["id", "profile_name", "started_at", "ended_at", "workout_name", "exercise", "mode", "video_path", "raw_video_path", "analysis_json_path", "detected_reps", "final_reps", "manually_corrected", "live_reps"],
    )
    _write_csv(
        output_dir / "rep_events.csv",
        events,
        ["id", "session_id", "profile_name", "exercise", "occurred_at", "form_score", "rom", "duration", "value", "unit", "feedback"],
    )
    _write_csv(
        output_dir / "daily_summary.csv",
        daily,
        ["date", "exercise", "display_name", "value", "unit", "avg_form_score"],
    )

    health_bridge = _apple_health_bridge(profile, sessions, rep_counts)
    (output_dir / "apple_health_bridge.json").write_text(json.dumps(health_bridge, indent=2), encoding="utf-8")
    fhir_bundle = _fhir_bundle(profile, sessions, rep_counts)
    (output_dir / "fhir_r4_bundle.json").write_text(json.dumps(fhir_bundle, indent=2), encoding="utf-8")

    manifest = {
        "profile": profile,
        "generatedAt": full_payload["generatedAt"],
        "totalReps": summary["period_total_reps"]["all"],
        "sessionCount": len(sessions),
        "files": sorted(path.name for path in output_dir.iterdir() if path.is_file()),
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    archive = home / "exports" / profile_key / f"Workout_Version_3_Export_{profile_key}_{stamp}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(output_dir.iterdir()):
            if path.is_file():
                zf.write(path, arcname=path.name)

    latest_dir = home / "exports" / profile_key / "latest"
    if latest_dir.exists():
        shutil.rmtree(latest_dir)
    shutil.copytree(output_dir, latest_dir)

    cloud_result = None
    cloud_path = Path(cloud_sync_dir).expanduser() if cloud_sync_dir else None
    if cloud_path:
        destination = cloud_path / "Workout Version 3" / profile_key
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(archive, destination / archive.name)
        shutil.copy2(output_dir / "manifest.json", destination / "latest_manifest.json")
        shutil.copy2(output_dir / "apple_health_bridge.json", destination / "latest_apple_health_bridge.json")
        cloud_result = str(destination)

    webhook_result = _post_webhook(webhook_url, webhook_token, {"manifest": manifest, "summary": summary})
    return {
        "output_dir": str(output_dir),
        "archive": str(archive),
        "latest_dir": str(latest_dir),
        "cloud_sync": cloud_result,
        "webhook": webhook_result,
        "manifest": manifest,
    }


def auto_export(db: WorkoutDatabase, profile: str, home: Path) -> dict[str, Any] | None:
    settings = AppSettings(home / "data" / "settings.json").load()
    if not bool(settings.get("auto_export_after_workout", True)):
        return None
    return export_profile(
        db,
        profile,
        home,
        cloud_sync_dir=settings.get("cloud_sync_dir") or None,
        webhook_url=str(settings.get("webhook_url") or ""),
        webhook_token=str(settings.get("webhook_token") or ""),
    )
