from __future__ import annotations

import html
import webbrowser
from urllib.parse import quote
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt

from .constants import DISPLAY_NAMES, EXERCISES
from .database import WorkoutDatabase


def _pivot(rows):
    data = defaultdict(lambda: {exercise: 0 for exercise in EXERCISES})
    forms = defaultdict(list)
    for row in rows:
        data[row["bucket"]][row["exercise"]] = int(row["reps"])
        if row["avg_form"] is not None:
            forms[row["bucket"]].append(float(row["avg_form"]))
    return data, forms


def build_dashboard(db: WorkoutDatabase, profile: str, output_dir: Path, open_browser: bool = True) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    sections = []
    for period, limit in (("daily", 30), ("weekly", 16), ("monthly", 12), ("yearly", 10)):
        rows = db.aggregate(profile, period, limit)
        data, forms = _pivot(rows)
        buckets = sorted(data.keys())[-limit:]
        chart_path = output_dir / f"{profile}_{period}.png"
        plt.figure(figsize=(12, 5))
        bottoms = [0] * len(buckets)
        for exercise in EXERCISES:
            values = [data[b][exercise] for b in buckets]
            plt.bar(buckets, values, bottom=bottoms, label=DISPLAY_NAMES[exercise])
            bottoms = [a + b for a, b in zip(bottoms, values)]
        plt.title(f"{profile} - {period.capitalize()} workout reps")
        plt.ylabel("Repetitions")
        plt.xticks(rotation=45, ha="right")
        plt.legend(ncol=3)
        plt.tight_layout()
        plt.savefig(chart_path, dpi=140)
        plt.close()

        table_rows = []
        for bucket in reversed(buckets):
            total = sum(data[bucket].values())
            avg_form = sum(forms[bucket]) / len(forms[bucket]) if forms[bucket] else 0.0
            cells = "".join(f"<td>{data[bucket][e]}</td>" for e in EXERCISES)
            table_rows.append(f"<tr><td>{html.escape(bucket)}</td>{cells}<td>{total}</td><td>{avg_form:.0f}</td></tr>")
        headers = "".join(f"<th>{html.escape(DISPLAY_NAMES[e])}</th>" for e in EXERCISES)
        sections.append(
            f"<h2>{period.capitalize()}</h2><img src='{chart_path.name}' class='chart'>"
            f"<table><thead><tr><th>Period</th>{headers}<th>Total</th><th>Avg form</th></tr></thead>"
            f"<tbody>{''.join(table_rows)}</tbody></table>"
        )

    session_rows = []
    for row in db.recent_sessions(profile, 25):
        workout_name = row["workout_name"] or row["mode"] or "Workout"
        exercise = DISPLAY_NAMES.get(row["exercise"], row["exercise"] or "Mixed")
        final_reps = row["final_reps"]
        if final_reps is None:
            final_reps = "—"
        review = "Human confirmed" if row["manually_corrected"] else "AI count"
        video = row["video_path"]
        video_link = "—"
        if video:
            video_link = f"<a href='file://{quote(str(video))}'>Open analysed video</a>"
        session_rows.append(
            f"<tr><td>{html.escape(str(row['started_at']))}</td>"
            f"<td>{html.escape(str(workout_name))}</td>"
            f"<td>{html.escape(str(exercise))}</td><td>{final_reps}</td>"
            f"<td>{html.escape(review)}</td><td>{video_link}</td></tr>"
        )
    recent_sessions = (
        "<h2>Recent named sessions</h2><table><thead><tr><th>Date</th><th>Workout</th>"
        "<th>Exercise</th><th>Reps</th><th>Review</th><th>Video</th></tr></thead>"
        f"<tbody>{''.join(session_rows)}</tbody></table>"
    )

    page = output_dir / "dashboard.html"
    page.write_text(
        """<!doctype html><html><head><meta charset='utf-8'><title>Workout Dashboard</title>
        <style>body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;max-width:1250px;margin:30px auto;padding:0 20px;background:#f5f7fa;color:#18212b}h1,h2{color:#152f4a}.card{background:white;padding:22px;border-radius:14px;box-shadow:0 3px 15px #0001;margin-bottom:24px}.chart{width:100%;max-width:1150px}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:9px;border-bottom:1px solid #dde4ea;text-align:right}th:first-child,td:first-child{text-align:left}</style></head><body>"""
        f"<h1>{html.escape(profile)} — Workout History</h1>"
        + f"<div class='card'>{recent_sessions}</div>"
        + "".join(f"<div class='card'>{section}</div>" for section in sections)
        + "</body></html>",
        encoding="utf-8",
    )
    if open_browser:
        webbrowser.open(page.as_uri())
    return page
