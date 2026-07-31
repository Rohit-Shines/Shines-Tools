#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import platform
import shlex
import signal
import subprocess
import threading
import time
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from workout_ai.constants import DEFAULT_HOME, DISPLAY_NAMES, EXERCISES, EXERCISE_GUIDES, EXERCISE_SHORTCUTS, EXERCISE_UNITS
from workout_ai.database import WorkoutDatabase
from workout_ai.exporter import export_profile
from workout_ai.settings import AppSettings
from workout_ai.reminders import install_reminder_service, reminder_status


class RuntimeState:
    def __init__(self, home: Path):
        self.home = home
        self.db = WorkoutDatabase(home / "data" / "workouts.sqlite3")
        self.settings = AppSettings(home / "data" / "settings.json")
        self.lock = threading.Lock()
        self.process: subprocess.Popen[str] | None = None
        self.process_kind = ""
        self.last_message = "Ready"
        self.last_error = ""
        self.last_log_path = home / "logs" / "gui_process.log"

    def _read_error_summary(self) -> str:
        path = self.last_log_path
        if not path.exists():
            return ""
        try:
            lines = [line.strip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
        except OSError:
            return ""
        preferred = (
            "RuntimeError:",
            "ImportError:",
            "ModuleNotFoundError:",
            "PermissionError:",
            "OSError:",
            "ValueError:",
            "ERROR:",
        )
        for line in reversed(lines):
            if line.startswith(preferred):
                return line[:500]
        return (lines[-1][:500] if lines else "")

    def _refresh(self) -> None:
        if self.process is not None and self.process.poll() is not None:
            code = self.process.returncode
            kind = self.process_kind or "Process"
            if code == 0:
                self.last_message = f"{kind} finished"
                self.last_error = ""
            else:
                self.last_error = self._read_error_summary()
                suffix = f": {self.last_error}" if self.last_error else ""
                self.last_message = f"{kind} finished with code {code}{suffix}"
            self.process = None
            self.process_kind = ""

    def status(self) -> dict[str, Any]:
        with self.lock:
            self._refresh()
            return {
                "running": self.process is not None,
                "kind": self.process_kind,
                "message": self.last_message,
                "error": self.last_error,
                "log_path": str(self.last_log_path),
                "server_architecture": platform.machine(),
                "version": "3.1.0",
            }

    def _rotate_process_log(self) -> None:
        log_dir = self.home / "logs"
        archive = log_dir / "archive"
        log_dir.mkdir(parents=True, exist_ok=True)
        archive.mkdir(parents=True, exist_ok=True)
        if self.last_log_path.exists() and self.last_log_path.stat().st_size:
            stamp = time.strftime("%Y%m%d_%H%M%S")
            destination = archive / f"gui_process_{stamp}.log"
            try:
                self.last_log_path.replace(destination)
            except OSError:
                pass

    def start(self, args: list[str], kind: str) -> tuple[bool, str]:
        with self.lock:
            self._refresh()
            if self.process is not None:
                return False, f"{self.process_kind} is already running"

            self._rotate_process_log()
            self.last_error = ""
            self.last_log_path.parent.mkdir(parents=True, exist_ok=True)

            native_python = ((self.home / ".venv" / "Scripts" / "python.exe") if os.name == "nt" else (self.home / ".venv" / "bin" / "python"))
            diagnostic = [
                str(native_python),
                "-c",
                (
                    "import platform,sys,numpy,cv2,mediapipe;"
                    "print('Python:',sys.version.split()[0]);"
                    "print('Architecture:',platform.machine());"
                    "print('NumPy:',numpy.__version__);"
                    "print('OpenCV:',cv2.__version__);"
                    "print('MediaPipe:',mediapipe.__version__)"
                ),
            ]
            with self.last_log_path.open("w", encoding="utf-8") as log:
                log.write(f"Started: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                log.write(f"Kind: {kind}\n")
                log.write("Command: " + shlex.join(args) + "\n")
                try:
                    check = subprocess.run(
                        diagnostic,
                        cwd=self.home,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        timeout=30,
                        check=False,
                    )
                    log.write("Native environment check:\n")
                    log.write(check.stdout or "(no output)\n")
                    if check.returncode != 0:
                        self.last_error = "Native Python environment preflight failed"
                        self.last_message = self.last_error
                        return False, self.last_error
                except Exception as exc:
                    self.last_error = f"Environment preflight failed: {exc}"
                    self.last_message = self.last_error
                    log.write(self.last_error + "\n")
                    return False, self.last_error
                log.write("\nProcess output:\n")
                log.flush()
                env = os.environ.copy()
                env["PYTHONUNBUFFERED"] = "1"
                popen_options: dict[str, Any] = {
                    "cwd": self.home,
                    "stdout": log,
                    "stderr": subprocess.STDOUT,
                    "text": True,
                    "env": env,
                }
                if os.name == "nt":
                    popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
                else:
                    popen_options["start_new_session"] = True
                self.process = subprocess.Popen(args, **popen_options)

            self.process_kind = kind
            self.last_message = f"{kind} started"
            return True, self.last_message

    def video_storage(self) -> dict[str, float | int]:
        recordings = self.home / "recordings"
        files = [path for path in recordings.rglob("*.mp4") if path.is_file()] if recordings.exists() else []
        total = sum(path.stat().st_size for path in files)
        return {"video_count": len(files), "video_bytes": total, "video_megabytes": round(total / (1024 * 1024), 1)}

    def cleanup_videos(self) -> dict[str, float | int]:
        recordings = self.home / "recordings"
        deleted = 0
        freed = 0
        if recordings.exists():
            for path in recordings.rglob("*.mp4"):
                if not path.is_file():
                    continue
                try:
                    freed += path.stat().st_size
                    path.unlink()
                    deleted += 1
                except OSError:
                    continue
        if deleted:
            with self.db.connection() as con:
                con.execute("UPDATE sessions SET video_path=NULL WHERE video_path LIKE '%.mp4'")
                con.execute("UPDATE sessions SET raw_video_path=NULL WHERE raw_video_path LIKE '%.mp4'")
        return {"deleted": deleted, "bytes": freed, "megabytes": round(freed / (1024 * 1024), 1)}

    def request_stop(self) -> str:
        with self.lock:
            self._refresh()
            if self.process is None:
                return "No workout is running"
            (self.home / "data" / "stop_request.flag").write_text("stop", encoding="utf-8")
            self.last_message = "Graceful stop requested; saving the workout"
            return self.last_message


PAGE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Workout Version 3.1</title>
<style>
:root{--bg:#081018;--card:#111b25;--card2:#162331;--line:#26394a;--text:#eef6ff;--muted:#93a7b8;--blue:#38bdf8;--green:#4ade80;--amber:#fbbf24;--red:#fb7185;--purple:#c084fc}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 20% 0,#13304a 0,#081018 38%);font:15px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:var(--text)}
.wrap{max-width:1500px;margin:auto;padding:26px}.top{display:flex;justify-content:space-between;align-items:center;gap:18px}.brand h1{margin:0;font-size:32px}.brand p{margin:7px 0;color:var(--muted)}
.status{padding:10px 14px;border:1px solid var(--line);border-radius:999px;background:#0d1822;max-width:720px}.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0}.tab{background:#1b2b3a;color:var(--text)}.tab.active{background:var(--blue);color:#04202e}.tab-pane{display:none}.tab-pane.active{display:block}
.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:16px}.card{background:linear-gradient(145deg,var(--card),#0d1720);border:1px solid var(--line);border-radius:18px;padding:18px;box-shadow:0 14px 35px #0005}.control{grid-column:span 5}.overview{grid-column:span 7}.full{grid-column:1/-1}.half{grid-column:span 6}.third{grid-column:span 4}
h2{font-size:17px;margin:0 0 14px}h3{margin:0 0 10px}label{display:block;color:var(--muted);font-size:12px;margin-bottom:6px}.row{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px}.row3{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:12px}input,select{width:100%;background:#09131c;color:var(--text);border:1px solid var(--line);border-radius:10px;padding:11px 12px;font-size:14px}.buttons{display:flex;flex-wrap:wrap;gap:10px;margin-top:14px}button{border:0;border-radius:11px;padding:11px 15px;font-weight:700;cursor:pointer;background:var(--blue);color:#04202e}button.secondary{background:#24384a;color:var(--text)}button.good{background:var(--green);color:#062811}button.warn{background:var(--amber);color:#322200}button.danger{background:var(--red);color:#3e0713}button:disabled{opacity:.45;cursor:not-allowed}
.stats{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}.stat{background:var(--card2);border:1px solid var(--line);border-radius:14px;padding:15px}.stat b{display:block;font-size:27px;margin-top:5px}.stat span{color:var(--muted);font-size:12px}.mini{display:flex;gap:18px;margin-top:14px;color:var(--muted);flex-wrap:wrap}.mini strong{color:var(--text)}
.table-wrap{overflow:auto}table{border-collapse:collapse;width:100%;min-width:1320px}th,td{text-align:right;padding:9px;border-bottom:1px solid #20313f;font-size:13px}th:nth-child(2),td:nth-child(2),th:nth-child(3),td:nth-child(3){text-align:left}th{color:var(--muted);font-size:11px;text-transform:uppercase}.goal{width:70px;padding:7px}.shortcut{width:58px;text-align:center;text-transform:uppercase;font-weight:800;padding:7px}.pill{display:inline-block;padding:4px 8px;border-radius:999px;background:#18334a;color:#8ed8ff;font-size:11px}.note{color:var(--muted);font-size:12px;line-height:1.55}.message{margin-top:12px;color:#9fe5ff;min-height:20px}.bar{height:7px;background:#26394a;border-radius:20px;overflow:hidden;margin-top:6px}.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--blue),var(--green))}.goal-red{color:var(--red)!important}.goal-green{color:var(--green)!important}.goal-blue{color:var(--blue)!important}.check{width:18px;height:18px}.unit{color:var(--muted);font-size:11px}.storage{padding:11px 12px;border:1px solid var(--line);border-radius:10px;background:#09131c;color:var(--green);font-weight:700}
.exercise-row{transition:background .12s,opacity .12s}.exercise-row[draggable=true]{cursor:grab}.exercise-row.dragging{opacity:.35;background:#24445b}.drag{font-size:20px;color:var(--muted);cursor:grab;text-align:center!important}.move{padding:4px 7px;border-radius:7px;background:#24384a;color:var(--text);margin:0 2px}.guide{display:grid;grid-template-columns:280px 1fr;gap:18px}.guide-box{background:var(--card2);border:1px solid var(--line);border-radius:14px;padding:16px;line-height:1.55}.guide-box h3{margin:0 0 10px}.guide-box p{margin:8px 0}.guide-box strong{color:#a9ddff}.guide-safe{color:#ffd58a}.new-badge{background:#3d2d10;color:#ffd26b;border-radius:999px;padding:3px 7px;font-size:10px;margin-left:6px}
.profile-box{display:grid;grid-template-columns:1fr auto auto;gap:10px;align-items:end}.switch{display:flex;align-items:center;gap:8px;color:var(--muted);font-size:13px}.switch input{width:auto}.insight{background:var(--card2);border:1px solid var(--line);border-radius:14px;padding:15px}.insight b{font-size:20px}.trend-up{color:var(--green)}.trend-down{color:var(--red)}.trend-flat{color:var(--amber)}.score{font-size:26px;font-weight:800}.help-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.diagram{background:#0b1721;border:1px solid var(--line);border-radius:14px;padding:15px;text-align:center}.diagram svg{width:100%;height:170px}.steps{counter-reset:step}.steps li{margin:10px 0;padding-left:5px}.timer-panel{background:linear-gradient(145deg,#152637,#0c1822);border:1px solid #36546a;border-radius:16px;padding:18px}.reminder-state{font-weight:800;color:var(--amber)}.coaching-table{min-width:900px}.document{white-space:pre-wrap;background:#08131c;border:1px solid var(--line);border-radius:12px;padding:14px;color:#cfe5f5;line-height:1.55}
@media(max-width:900px){.control,.overview,.half,.third{grid-column:1/-1}.stats{grid-template-columns:repeat(2,1fr)}.row,.row3,.guide,.help-grid,.profile-box{grid-template-columns:1fr}}
</style></head><body><div class="wrap">
<div class="top"><div class="brand"><h1>Workout Version 3.1</h1><p>Custom controls, true seconds mode, multi-profile coaching and background movement reminders.</p></div><div id="status" class="status">Loading…</div></div>
<div class="tabs"><button class="tab active" data-tab="dashboard">Dashboard</button><button class="tab" data-tab="coaching">Coaching & Improvements</button><button class="tab" data-tab="reminders">Reminders</button><button class="tab" data-tab="help">Help & Exercise Guides</button></div>

<div id="tab-dashboard" class="tab-pane active"><div class="grid">
<section class="card control"><h2>Start workout</h2>
<div class="row"><div><label>Profile</label><select id="profile"></select></div><div><label>Workout name</label><input id="workoutName" placeholder="Morning warm-up"></div></div>
<div class="row"><div><label>Exercise mode</label><select id="exercise"><option value="auto">Automatic mode</option><option value="manual">Manual keyboard mode</option></select></div><div><label>Tolerance: <span id="tolLabel">60%</span></label><input id="tolerance" type="range" min="50" max="80" step="10" value="60"></div></div>
<div class="row"><div><label>Camera number</label><input id="camera" type="number" min="0" max="6" value="0"></div><div><label>Storage mode</label><div class="storage">Video disabled — counts and seconds only</div></div></div>
<div class="buttons"><button class="good" id="start">Start automatic workout</button><button class="danger" id="stop">Stop & save</button><button class="secondary" id="openLog">Open latest log</button></div><div id="message" class="message"></div>
</section>
<section class="card overview"><h2>Progress overview</h2><div class="stats"><div class="stat"><span>Today count</span><b id="totalToday">0</b></div><div class="stat"><span>This week</span><b id="totalWeek">0</b></div><div class="stat"><span>This month</span><b id="totalMonth">0</b></div><div class="stat"><span>This year</span><b id="totalYear">0</b></div><div class="stat"><span>All time</span><b id="totalAll">0</b></div></div><div class="row" style="margin-top:14px"><div><label>Overall daily repetition goal</label><input id="overallGoal" type="number" min="0" value="100"></div><div><label>Timed holds today</label><input id="timedToday" value="0 seconds" disabled></div></div><div class="mini"><span>Current streak: <strong id="streak">0</strong> days</span><span>Active days: <strong id="activeDays">0</strong></span><span>Best day: <strong id="bestDay">—</strong></span></div></section>
<section class="card full"><h2>Profiles</h2><div class="profile-box"><div><label>New profile name</label><input id="newProfile" placeholder="Priya"></div><label class="switch"><input id="copyProfile" type="checkbox" checked> Copy current goals, order and shortcut keys</label><button class="good" id="createProfile">Create profile</button></div><p class="note">Each profile keeps separate counts, goals, exercise order, shortcut keys, personal bests and coaching history. Selecting a profile also makes it the default for the next launch.</p></section>
<section class="card full"><h2>Exercise selection, shortcut keys, order and goals</h2><p class="note">Edit any shortcut using one letter or number. Keys 0, M, X, D and Q are reserved. Every exercise must have a unique shortcut. Automatic mode considers only checked exercises.</p><div class="table-wrap"><table><thead><tr><th>Order</th><th>Track</th><th>Exercise</th><th>Shortcut</th><th>Unit</th><th>Today</th><th>Week</th><th>Month</th><th>Year</th><th>All time</th><th>Personal best</th><th>Daily goal</th><th>Progress</th></tr></thead><tbody id="exerciseRows"></tbody></table></div><div class="buttons"><button class="secondary" id="selectAll">Select all</button><button class="secondary" id="deselectAll">Deselect all</button><button class="warn" id="resetShortcuts">Reset default shortcut keys</button><button class="good" id="saveGoals">Save preferences, shortcut keys, order and goals</button></div></section>
<section class="card half"><h2>Portable data and cloud sync</h2><div><label>Cloud-synced folder (optional)</label><input id="cloudPath" placeholder="~/Library/CloudStorage/GoogleDrive-.../My Drive/Workout Version 3"></div><div class="buttons"><button id="saveSettings" class="secondary">Save settings</button><button id="exportNow">Export now</button><button id="openExports" class="secondary">Open exports</button><button id="cleanVideos" class="danger">Delete old workout videos</button></div><p class="note"><span id="videoStorage">Checking old video storage…</span><br>New workouts never save video. Exports include form feedback and coaching data.</p></section>
<section class="card half"><h2>Recent workouts</h2><table style="min-width:0"><thead><tr><th>Date</th><th>Name</th><th>Mode</th><th>Value</th></tr></thead><tbody id="sessions"></tbody></table></section>
</div></div>

<div id="tab-coaching" class="tab-pane"><div class="grid">
<section class="card full"><h2>Latest coaching update</h2><p class="note">Form percentages are calculated from completed movements recorded by the tracker. Trends compare the latest 20 recorded movements with the previous 20. The app waits for enough data before claiming improvement.</p><div id="topInsights" class="grid" style="margin-top:12px"></div></section>
<section class="card full"><h2>Exercise form report</h2><div class="table-wrap"><table class="coaching-table"><thead><tr><th>Exercise</th><th>Recent form</th><th>Previous</th><th>Trend</th><th>Status</th><th>Recent samples</th><th>Most common correction</th></tr></thead><tbody id="coachingRows"></tbody></table></div></section>
</div></div>

<div id="tab-reminders" class="tab-pane"><div class="grid">
<section class="card half timer-panel"><h2>Movement break reminder</h2><p class="note">A lightweight macOS LaunchAgent checks once per minute. It can alert even while Workout Version 3 is closed. The popup can launch the app or snooze the reminder.</p>
<div class="row"><label class="switch"><input id="reminderEnabled" type="checkbox"> Enable background reminders</label><div><label>Status</label><div id="reminderStatus" class="reminder-state">Checking…</div></div></div>
<div class="row3"><div><label>Every</label><select id="reminderInterval"><option value="20">20 minutes</option><option value="30">30 minutes</option><option value="45">45 minutes</option><option value="60">60 minutes</option><option value="90">90 minutes</option></select></div><div><label>Suggested exercise</label><select id="reminderExercise"></select></div><div><label>Snooze</label><select id="reminderSnooze"><option value="5">5 minutes</option><option value="10">10 minutes</option><option value="15">15 minutes</option></select></div></div>
<div class="row3"><div><label>Active from</label><input id="reminderStart" type="time" value="08:00"></div><div><label>Active until</label><input id="reminderEnd" type="time" value="21:00"></div><div><label>Sound</label><select id="reminderSound"><option>Glass</option><option>Ping</option><option>Pop</option><option>Hero</option><option>Submarine</option></select></div></div>
<div class="buttons"><button class="good" id="saveReminder">Save reminder</button><button class="secondary" id="testReminder">Test popup and sound</button></div><div id="reminderMessage" class="message"></div></section>
<section class="card half"><h2>How it works</h2><ol class="steps"><li>Enable reminders and choose an interval.</li><li>The background service waits until the next due time inside your active hours.</li><li>The popup offers <strong>Launch Workout</strong>, <strong>Snooze</strong>, or <strong>Dismiss</strong>.</li><li>Launching opens the same stable Workout Version 3 application.</li></ol><p class="note">Your operating system may request notification or automation permission. Approve it for reminders to appear.</p></section>
</div></div>

<div id="tab-help" class="tab-pane"><div class="grid">
<section class="card full"><h2>Quick start</h2><div class="help-grid">
<div class="diagram"><h3>Front view</h3><svg viewBox="0 0 220 170" aria-label="front camera setup"><rect x="4" y="4" width="212" height="162" rx="12" fill="#0e2230" stroke="#315065"/><circle cx="110" cy="35" r="16" fill="none" stroke="#4ade80" stroke-width="5"/><line x1="110" y1="51" x2="110" y2="105" stroke="#4ade80" stroke-width="5"/><line x1="65" y1="69" x2="155" y2="69" stroke="#4ade80" stroke-width="5"/><line x1="110" y1="105" x2="80" y2="150" stroke="#4ade80" stroke-width="5"/><line x1="110" y1="105" x2="140" y2="150" stroke="#4ade80" stroke-width="5"/></svg><p>Best for squats, presses, curls, kicks and arm circles. Keep the full body visible.</p></div>
<div class="diagram"><h3>Side view</h3><svg viewBox="0 0 220 170" aria-label="side camera setup"><rect x="4" y="4" width="212" height="162" rx="12" fill="#0e2230" stroke="#315065"/><circle cx="55" cy="76" r="13" fill="none" stroke="#38bdf8" stroke-width="5"/><line x1="68" y1="82" x2="125" y2="92" stroke="#38bdf8" stroke-width="5"/><line x1="125" y1="92" x2="180" y2="100" stroke="#38bdf8" stroke-width="5"/><line x1="92" y1="87" x2="70" y2="125" stroke="#38bdf8" stroke-width="5"/><line x1="145" y1="95" x2="160" y2="135" stroke="#38bdf8" stroke-width="5"/></svg><p>Best for push-ups, planks, squat holds and sit-ups. Keep shoulders, hips and feet visible.</p></div>
<div class="diagram"><h3>Seconds mode</h3><svg viewBox="0 0 220 170" aria-label="seconds timer"><rect x="25" y="28" width="170" height="110" rx="18" fill="#0e2230" stroke="#fbbf24" stroke-width="3"/><text x="110" y="67" fill="#fbbf24" font-size="18" text-anchor="middle">SECONDS MODE</text><text x="110" y="113" fill="#4ade80" font-size="42" text-anchor="middle">12.4s</text></svg><p>Choose Plank or Squat hold in manual mode. The large timer begins after the pose is stable.</p></div>
</div></section>
<section class="card full"><h2>Exercise guide and test reference</h2><div class="guide"><div><label>Select exercise</label><select id="guideExercise"></select><div class="buttons"><button class="secondary" id="useManual">Use as manual mode</button></div></div><div id="guideBox" class="guide-box"></div></div></section>
<section class="card half"><h2>Manual mode guide</h2><div id="shortcutDocument" class="document"></div></section>
<section class="card half"><h2>Accuracy checklist</h2><div class="document">1. Use good front lighting; avoid a bright window behind you.
2. Keep every joint required for the exercise inside the frame.
3. For automatic recognition, enable only exercises planned for that session.
4. Use manual mode for timed holds or when testing a newly configured exercise.
5. Move through the full start → movement → return cycle.
6. Read the live feedback before increasing speed.
7. The coaching tab is guidance from pose landmarks, not medical assessment.</div></section>
</div></div>
</div>
<script>
const names=%DISPLAY_NAMES%; const exercises=%EXERCISES%; const units=%UNITS%; const guides=%GUIDES%; const defaultShortcuts=%SHORTCUTS%;
let currentProfile=''; let formInitialised=false; let exerciseOrder=[...exercises]; let dragging=null; let shortcutMap={...defaultShortcuts};
const $=id=>document.getElementById(id); async function post(path,data={}){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const j=await r.json();if(!r.ok)throw new Error(j.error||'Request failed');return j}
function msg(t){$('message').textContent=t||''} function valueText(e,v){return units[e]==='seconds'?`${v}s`:String(v)}
function showTab(name){document.querySelectorAll('.tab').forEach(b=>b.classList.toggle('active',b.dataset.tab===name));document.querySelectorAll('.tab-pane').forEach(p=>p.classList.toggle('active',p.id==='tab-'+name))}
document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>showTab(b.dataset.tab));
function renderGuide(e){const g=guides[e]||{};$('guideBox').innerHTML=`<h3>${names[e]||e}</h3><p><strong>Camera setup:</strong> ${g.setup||'Keep the full movement visible.'}</p><p><strong>How to do it:</strong> ${g.steps||''}</p><p><strong>How the app counts:</strong> ${g.count_rule||''}</p><p><strong>Current manual shortcut:</strong> ${shortcutMap[e]||'?'}</p><p class="guide-safe"><strong>Safety:</strong> ${g.safety||'Use a comfortable, controlled range.'}</p>`}
$('tolerance').oninput=()=>{$('tolLabel').textContent=$('tolerance').value+'%'};
function rebuildExerciseMode(){const selected=$('exercise').value||'auto';$('exercise').innerHTML='<option value="auto">Automatic mode</option><option value="manual">Manual keyboard mode</option>';$('exercise').value=(selected==='manual')?'manual':'auto';$('start').textContent=$('exercise').value==='manual'?'Start manual workout':'Start automatic workout'}
function rowOrder(){return [...document.querySelectorAll('#exerciseRows tr')].map(r=>r.dataset.ex)} $('exercise').onchange=rebuildExerciseMode;
function moveRow(ex,delta){const rows=[...document.querySelectorAll('#exerciseRows tr')];const row=rows.find(r=>r.dataset.ex===ex);if(!row)return;const index=rows.indexOf(row);const target=rows[index+delta];if(!target)return;if(delta<0)row.parentNode.insertBefore(row,target);else row.parentNode.insertBefore(target,row);exerciseOrder=rowOrder()}
function enableDrag(){document.querySelectorAll('.exercise-row').forEach(row=>{row.addEventListener('dragstart',()=>{dragging=row;row.classList.add('dragging')});row.addEventListener('dragend',()=>{row.classList.remove('dragging');dragging=null;exerciseOrder=rowOrder()});row.addEventListener('dragover',e=>{e.preventDefault();if(!dragging||dragging===row)return;const rect=row.getBoundingClientRect();row.parentNode.insertBefore(dragging,e.clientY<rect.top+rect.height/2?row:row.nextSibling)})})}
function renderRows(d){const t=d.summary.periods;const cfgs=d.summary.exercise_settings||{};shortcutMap=d.summary.shortcuts||defaultShortcuts;exerciseOrder=[...exercises].sort((a,b)=>(cfgs[a]?.order||999)-(cfgs[b]?.order||999));$('exerciseRows').innerHTML=exerciseOrder.map(e=>{const cfg=cfgs[e]||{};const g=cfg.goal||0;const today=t.today[e]||0;const pct=g?Math.min(100,Math.round(today/g*100)):0;const cls=today<g?'goal-red':(today===g?'goal-green':'goal-blue');const pb=(d.summary.personal_bests||{})[e]||0;return `<tr class="exercise-row" draggable="true" data-ex="${e}"><td class="drag">↕ <button class="move up" data-ex="${e}" type="button">↑</button><button class="move down" data-ex="${e}" type="button">↓</button></td><td><input class="check enabled" data-ex="${e}" type="checkbox" ${cfg.enabled?'checked':''}></td><td>${names[e]}</td><td><input class="shortcut" data-ex="${e}" maxlength="1" value="${shortcutMap[e]||''}"></td><td class="unit">${units[e]}</td><td class="${cls}">${valueText(e,today)}</td><td>${valueText(e,t.week[e]||0)}</td><td>${valueText(e,t.month[e]||0)}</td><td>${valueText(e,t.year[e]||0)}</td><td>${valueText(e,t.all[e]||0)}</td><td class="goal-blue">${valueText(e,pb)}</td><td><input class="goal" data-ex="${e}" type="number" min="0" value="${g}"></td><td><span class="pill">${pct}%</span><div class="bar"><i style="width:${pct}%"></i></div></td></tr>`}).join('');enableDrag();document.querySelectorAll('.up').forEach(b=>b.onclick=()=>moveRow(b.dataset.ex,-1));document.querySelectorAll('.down').forEach(b=>b.onclick=()=>moveRow(b.dataset.ex,1));document.querySelectorAll('.shortcut').forEach(i=>i.oninput=()=>{i.value=(i.value||'').slice(0,1).toUpperCase()});renderShortcutDocument()}
function renderShortcutDocument(){const lines=exerciseOrder.map(e=>`${shortcutMap[e]||'?'}  ${names[e]}${units[e]==='seconds'?' (seconds)':''}`);$('shortcutDocument').textContent='Automatic mode: press 0\nManual mode: press M\n\n'+lines.join('\n')+'\n\nX  Reset current exercise\nD  Open report\nQ  Finish and save'}
function renderCoaching(c){const top=c.top_rows||[];$('topInsights').innerHTML=(top.length?top:[{exercise:'pushup',average_form:null,trend:'Collecting baseline',feedback:'Complete a few workouts to generate coaching.'}]).map(i=>`<div class="card third insight"><span>${names[i.exercise]||'Coaching'}</span><div class="score">${i.average_form==null?'—':i.average_form+'%'}</div><b class="${String(i.trend).startsWith('Improved')?'trend-up':String(i.trend).startsWith('Down')?'trend-down':'trend-flat'}">${i.trend||'Collecting baseline'}</b><p>${i.feedback||''}</p></div>`).join('');$('coachingRows').innerHTML=(c.items||[]).map(i=>`<tr><td style="text-align:left">${names[i.exercise]}</td><td>${i.average_form==null?'—':i.average_form+'%'}</td><td>${i.previous_form==null?'—':i.previous_form+'%'}</td><td>${i.trend}</td><td>${i.status}</td><td>${i.sample_count}</td><td style="text-align:left">${i.feedback}</td></tr>`).join('')}
async function load(){const selected=$('profile').value||currentProfile;const r=await fetch('/api/state?profile='+encodeURIComponent(selected));const d=await r.json();currentProfile=d.profile;const wanted=d.profile;const existing=[...$('profile').options].map(o=>o.value);if(existing.join('|')!==d.profiles.join('|')){$('profile').innerHTML='';d.profiles.forEach(p=>{let o=document.createElement('option');o.value=p;o.textContent=p;$('profile').appendChild(o)})}$('profile').value=d.profiles.includes(wanted)?wanted:(d.profiles[0]||'User');$('status').textContent=d.runtime.running?('Running: '+d.runtime.kind):d.runtime.message;$('start').disabled=d.runtime.running;$('stop').disabled=!d.runtime.running;if(d.runtime.error)msg(d.runtime.error);for(const p of ['today','week','month','year','all'])$('total'+p[0].toUpperCase()+p.slice(1)).textContent=d.summary.period_total_reps[p];const og=d.summary.overall_daily_goal||100;if(document.activeElement!==$('overallGoal'))$('overallGoal').value=og;$('timedToday').value=(d.summary.period_total_seconds.today||0)+' seconds';const tv=d.summary.period_total_reps.today||0;$('totalToday').className=tv<og?'goal-red':(tv===og?'goal-green':'goal-blue');$('streak').textContent=d.summary.streak_days;$('activeDays').textContent=d.summary.active_days;$('bestDay').textContent=d.summary.personal_best_day?(d.summary.personal_best_day+' ('+d.summary.personal_best_reps+')'):'—';if(!formInitialised){$('cloudPath').value=d.settings.cloud_sync_dir||'';$('camera').value=d.settings.default_camera||0;$('tolerance').value=d.settings.default_tolerance||60;$('exercise').value=d.settings.default_mode==='manual'?'manual':'auto';$('tolLabel').textContent=$('tolerance').value+'%';$('reminderEnabled').checked=!!d.settings.reminder_enabled;$('reminderInterval').value=String(d.settings.reminder_interval_minutes||30);$('reminderExercise').value=d.settings.reminder_exercise||'pushup';$('reminderStart').value=d.settings.reminder_active_start||'08:00';$('reminderEnd').value=d.settings.reminder_active_end||'21:00';$('reminderSnooze').value=String(d.settings.reminder_snooze_minutes||10);$('reminderSound').value=d.settings.reminder_sound||'Glass';rebuildExerciseMode();formInitialised=true}const editing=document.activeElement&&(document.activeElement.classList.contains('goal')||document.activeElement.classList.contains('enabled')||document.activeElement.classList.contains('move')||document.activeElement.classList.contains('shortcut'));if(!editing&&!dragging)renderRows(d);$('videoStorage').textContent='Old video files: '+(d.storage?.video_count||0)+' ('+(d.storage?.video_megabytes||0)+' MB)';$('sessions').innerHTML=d.sessions.map(s=>`<tr><td>${(s.started_at||'').replace('T',' ').slice(0,16)}</td><td>${s.workout_name||'Workout'}</td><td>${s.mode||'—'}</td><td>${s.final_reps??s.live_reps??0}</td></tr>`).join('')||'<tr><td colspan="4">No workouts yet</td></tr>';renderCoaching(d.coaching||{});$('reminderStatus').textContent=(d.reminder?.installed?'Background service installed':'Background service not installed')+(d.settings.reminder_enabled?' — enabled':' — disabled')}
$('profile').onchange=async()=>{currentProfile=$('profile').value;formInitialised=false;await post('/api/select-profile',{profile:currentProfile});load()};
$('start').onclick=async()=>{try{const d=await post('/api/start',{profile:$('profile').value,workout_name:$('workoutName').value,exercise:$('exercise').value,tolerance:Number($('tolerance').value),camera:Number($('camera').value)});msg(d.message);load()}catch(e){msg(e.message)}};$('stop').onclick=async()=>{try{const d=await post('/api/stop');msg(d.message)}catch(e){msg(e.message)}};
$('createProfile').onclick=async()=>{const name=$('newProfile').value.trim();if(!name){msg('Enter a profile name');return}try{const d=await post('/api/profile',{profile:name,clone_from:$('copyProfile').checked?$('profile').value:''});currentProfile=d.profile;$('newProfile').value='';formInitialised=false;msg(d.message);await load()}catch(e){msg(e.message)}};
async function saveGoalPreferences(){const goals={},enabled={},shortcuts={};document.querySelectorAll('.goal').forEach(i=>goals[i.dataset.ex]=Number(i.value));document.querySelectorAll('.enabled').forEach(i=>enabled[i.dataset.ex]=i.checked);document.querySelectorAll('.shortcut').forEach(i=>shortcuts[i.dataset.ex]=i.value);exerciseOrder=rowOrder();const d=await post('/api/goals',{profile:$('profile').value,goals,enabled,shortcuts,order:exerciseOrder,overall_daily_goal:Number($('overallGoal').value)});msg(d.message);await load()}
$('saveGoals').onclick=()=>saveGoalPreferences().catch(e=>msg(e.message));$('selectAll').onclick=()=>document.querySelectorAll('.enabled').forEach(i=>i.checked=true);$('deselectAll').onclick=()=>document.querySelectorAll('.enabled').forEach(i=>i.checked=false);$('resetShortcuts').onclick=async()=>{if(!confirm('Reset shortcut keys for this profile to the Version 3 defaults?'))return;try{const d=await post('/api/reset-shortcuts',{profile:$('profile').value});msg(d.message);await load()}catch(e){msg(e.message)}};
$('saveSettings').onclick=async()=>{try{const d=await post('/api/settings',{cloud_sync_dir:$('cloudPath').value,default_profile:$('profile').value,default_tolerance:Number($('tolerance').value),default_camera:Number($('camera').value),default_mode:$('exercise').value,record_video:false});msg(d.message)}catch(e){msg(e.message)}};$('exportNow').onclick=async()=>{msg('Creating export…');try{const d=await post('/api/export',{profile:$('profile').value});msg('Export created: '+d.archive)}catch(e){msg(e.message)}};$('openExports').onclick=()=>post('/api/open',{target:'exports'}).catch(e=>msg(e.message));$('cleanVideos').onclick=async()=>{if(!confirm('Delete all existing MP4 workout videos? Counts and history remain.'))return;try{const d=await post('/api/cleanup-videos');msg(d.message);load()}catch(e){msg(e.message)}};$('openLog').onclick=()=>post('/api/open',{target:'latest_log'}).catch(e=>msg(e.message));
$('saveReminder').onclick=async()=>{try{const d=await post('/api/reminder',{enabled:$('reminderEnabled').checked,interval_minutes:Number($('reminderInterval').value),exercise:$('reminderExercise').value,active_start:$('reminderStart').value,active_end:$('reminderEnd').value,snooze_minutes:Number($('reminderSnooze').value),sound:$('reminderSound').value});$('reminderMessage').textContent=d.message;formInitialised=false;await load()}catch(e){$('reminderMessage').textContent=e.message}};$('testReminder').onclick=async()=>{try{const d=await post('/api/reminder/test',{exercise:$('reminderExercise').value,sound:$('reminderSound').value});$('reminderMessage').textContent=d.message}catch(e){$('reminderMessage').textContent=e.message}};
exercises.forEach(e=>{let o=document.createElement('option');o.value=e;o.textContent=names[e];$('guideExercise').appendChild(o);let r=document.createElement('option');r.value=e;r.textContent=names[e];$('reminderExercise').appendChild(r)});$('guideExercise').onchange=()=>renderGuide($('guideExercise').value);$('useManual').onclick=()=>{$('exercise').value='manual';rebuildExerciseMode();showTab('dashboard');window.scrollTo({top:0,behavior:'smooth'});msg('Manual mode ready. Press '+(shortcutMap[$('guideExercise').value]||'?')+' for '+names[$('guideExercise').value])};renderGuide(exercises[0]);rebuildExerciseMode();load();setInterval(load,3000);
</script></body></html>'''



class Handler(BaseHTTPRequestHandler):
    runtime: RuntimeState

    def log_message(self, format: str, *args: object) -> None:
        return

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/ping":
            self._json({"ok": True, "version": "3.1.0", "architecture": platform.machine()})
            return
        if parsed.path == "/api/state":
            query = urllib.parse.parse_qs(parsed.query)
            settings = self.runtime.settings.load()
            profile = (query.get("profile") or [settings.get("default_profile", "User")])[0]
            self.runtime.db.ensure_profile(profile)
            self._json(
                {
                    "profile": profile,
                    "profiles": self.runtime.db.profiles(),
                    "summary": self.runtime.db.summary(profile),
                    "coaching": self.runtime.db.coaching_insights(profile),
                    "sessions": [dict(row) for row in self.runtime.db.recent_sessions(profile, 12)],
                    "settings": settings,
                    "runtime": self.runtime.status(),
                    "storage": self.runtime.video_storage(),
                    "reminder": reminder_status(),
                }
            )
            return
        if parsed.path == "/":
            text = (
                PAGE.replace("%DISPLAY_NAMES%", json.dumps(DISPLAY_NAMES))
                .replace("%EXERCISES%", json.dumps(EXERCISES))
                .replace("%UNITS%", json.dumps(EXERCISE_UNITS))
                .replace("%GUIDES%", json.dumps(EXERCISE_GUIDES))
                .replace("%SHORTCUTS%", json.dumps(EXERCISE_SHORTCUTS))
            )
            body = text.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def do_POST(self) -> None:
        data = self._read_json()
        try:
            if self.path == "/api/start":
                profile = str(data.get("profile") or "User").strip()
                exercise = str(data.get("exercise") or "auto")
                if exercise not in ("auto", "manual"):
                    raise ValueError("Unknown exercise mode")
                if exercise == "auto" and not self.runtime.db.enabled_exercises(profile):
                    raise ValueError("No exercises are enabled. Select at least one exercise and save preferences.")
                tolerance = max(50, min(80, int(data.get("tolerance", 60))))
                camera = max(0, min(6, int(data.get("camera", 0))))
                python = ((self.runtime.home / ".venv" / "Scripts" / "python.exe") if os.name == "nt" else (self.runtime.home / ".venv" / "bin" / "python"))
                record_video = False
                self.runtime.settings.update(
                    default_profile=profile,
                    default_tolerance=tolerance,
                    default_camera=camera,
                    default_mode=exercise,
                    record_video=False,
                )
                command = [
                    str(python),
                    str(self.runtime.home / "workout_tracker.py"),
                    "--home", str(self.runtime.home),
                    "--profile", profile,
                    "--exercise", exercise,
                    "--acceptance", str(tolerance),
                    "--camera", str(camera),
                    "--workout-name", str(data.get("workout_name") or ""),
                ]
                command.append("--no-video")
                ok, message = self.runtime.start(command, "Live workout")
                self._json({"ok": ok, "message": message}, 200 if ok else 409)
                return
            if self.path == "/api/stop":
                self._json({"ok": True, "message": self.runtime.request_stop()})
                return
            if self.path == "/api/profile":
                profile = str(data.get("profile") or "").strip()
                if not profile:
                    raise ValueError("Profile name is required")
                if len(profile) > 50:
                    raise ValueError("Profile name is too long")
                self.runtime.db.ensure_profile(profile)
                clone_from = str(data.get("clone_from") or "").strip()
                if clone_from and clone_from != profile:
                    self.runtime.db.clone_profile_settings(clone_from, profile)
                self.runtime.settings.update(default_profile=profile)
                self._json({"ok": True, "profile": profile, "message": f"Profile {profile} is ready"})
                return
            if self.path == "/api/select-profile":
                profile = str(data.get("profile") or "User").strip() or "User"
                self.runtime.db.ensure_profile(profile)
                self.runtime.settings.update(default_profile=profile)
                self._json({"ok": True, "profile": profile})
                return
            if self.path == "/api/goals":
                profile = str(data.get("profile") or "User")
                goals = data.get("goals") or {}
                enabled = data.get("enabled") or {}
                for exercise in EXERCISES:
                    if exercise in goals:
                        self.runtime.db.set_goal(profile, exercise, int(goals[exercise]))
                    if exercise in enabled:
                        self.runtime.db.set_exercise_enabled(profile, exercise, bool(enabled[exercise]))
                shortcuts = data.get("shortcuts") or {}
                if isinstance(shortcuts, dict):
                    self.runtime.db.set_shortcuts(profile, shortcuts)
                order = data.get("order") or []
                if isinstance(order, list):
                    self.runtime.db.set_exercise_order(profile, [str(value) for value in order])
                if "overall_daily_goal" in data:
                    self.runtime.db.set_overall_daily_goal(profile, int(data["overall_daily_goal"]))
                self._json({"ok": True, "message": "Exercise selection, shortcut keys, order and daily goals saved"})
                return
            if self.path == "/api/reset-shortcuts":
                profile = str(data.get("profile") or "User")
                values = self.runtime.db.reset_shortcuts(profile)
                self._json({"ok": True, "message": "Shortcut keys reset to defaults", "shortcuts": values})
                return
            if self.path == "/api/cleanup-videos":
                result = self.runtime.cleanup_videos()
                self._json({"ok": True, "message": f"Deleted {result['deleted']} old video files and freed {result['megabytes']} MB", **result})
                return
            if self.path == "/api/reminder":
                enabled = bool(data.get("enabled", False))
                interval = max(5, min(240, int(data.get("interval_minutes", 30))))
                snooze = max(1, min(60, int(data.get("snooze_minutes", 10))))
                exercise = str(data.get("exercise") or "pushup")
                if exercise not in EXERCISES:
                    exercise = "pushup"
                active_start = str(data.get("active_start") or "08:00")[:5]
                active_end = str(data.get("active_end") or "21:00")[:5]
                sound = str(data.get("sound") or "Glass")
                saved = self.runtime.settings.update(
                    reminder_enabled=enabled,
                    reminder_interval_minutes=interval,
                    reminder_exercise=exercise,
                    reminder_active_start=active_start,
                    reminder_active_end=active_end,
                    reminder_snooze_minutes=snooze,
                    reminder_sound=sound,
                )
                state_path = self.runtime.home / "data" / "reminder_state.json"
                state_path.unlink(missing_ok=True)
                install_reminder_service(self.runtime.home)
                self._json({"ok": True, "message": "Background reminder enabled" if enabled else "Background reminder disabled", "settings": saved})
                return
            if self.path == "/api/reminder/test":
                exercise = str(data.get("exercise") or "pushup")
                sound = str(data.get("sound") or "Glass")
                label = DISPLAY_NAMES.get(exercise, exercise.replace("_", " ").title())
                if os.name == "nt":
                    script = (
                        "Add-Type -AssemblyName PresentationFramework;"
                        "[System.Media.SystemSounds]::Exclamation.Play();"
                        f"[System.Windows.MessageBox]::Show('Reminder test: time for {label}.','Workout Version 3 Reminder','OK','Information') | Out-Null"
                    )
                    subprocess.Popen(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script])
                else:
                    sound_path = Path("/System/Library/Sounds") / f"{sound}.aiff"
                    if sound_path.exists():
                        subprocess.Popen(["afplay", str(sound_path)])
                    script = f'display dialog "Reminder test: time for {label}." with title "Workout Version 3 Reminder" buttons {{"OK"}} default button "OK" with icon note'
                    subprocess.Popen(["osascript", "-e", script])
                self._json({"ok": True, "message": "Test reminder opened"})
                return
            if self.path == "/api/settings":
                data["record_video"] = False
                saved = self.runtime.settings.save(data)
                self._json({"ok": True, "message": "Settings saved", "settings": saved})
                return
            if self.path == "/api/export":
                profile = str(data.get("profile") or "User")
                settings = self.runtime.settings.load()
                result = export_profile(
                    self.runtime.db,
                    profile,
                    self.runtime.home,
                    cloud_sync_dir=settings.get("cloud_sync_dir") or None,
                    webhook_url=str(settings.get("webhook_url") or ""),
                    webhook_token=str(settings.get("webhook_token") or ""),
                )
                self._json({"ok": True, **result})
                return
            if self.path == "/api/open":
                allowed = {
                    "exports": self.runtime.home / "exports",
                    "recordings": self.runtime.home / "recordings",
                    "reports": self.runtime.home / "reports",
                    "latest_log": self.runtime.home / "logs" / "gui_process.log",
                }
                target = allowed.get(str(data.get("target") or ""))
                if target is None:
                    raise ValueError("Unknown folder")
                target.mkdir(parents=True, exist_ok=True)
                os.startfile(str(target)) if os.name == "nt" else subprocess.Popen(["open", str(target)])
                self._json({"ok": True})
                return
            self._json({"error": "Not found"}, 404)
        except Exception as exc:
            self._json({"error": str(exc)}, 500)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path, default=Path(os.environ.get("WORKOUT_HOME", DEFAULT_HOME)))
    parser.add_argument("--port", type=int, default=8793)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    home = args.home.expanduser()
    home.mkdir(parents=True, exist_ok=True)
    runtime = RuntimeState(home)
    Handler.runtime = runtime
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Workout Version 3 GUI: {url}")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
