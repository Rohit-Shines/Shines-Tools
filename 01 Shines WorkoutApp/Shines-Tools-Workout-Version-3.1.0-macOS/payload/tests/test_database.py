from __future__ import annotations

from datetime import datetime

from workout_ai.database import WorkoutDatabase


def test_database_records_reps_and_goals(tmp_path):
    db = WorkoutDatabase(tmp_path / "workouts.sqlite3")
    db.ensure_profile("Rohit")
    db.set_goal("Rohit", "pushup", 25)
    assert db.goals("Rohit")["pushup"] == 25
    session = db.start_session("Rohit", datetime.now(), tmp_path / "video.mp4", "manual")
    db.add_rep(session, "Rohit", "pushup", datetime.now(), 92.0, 70.0, 1.2)
    db.add_rep(session, "Rohit", "pushup", datetime.now(), 90.0, 68.0, 1.3)
    assert db.totals_for_day("Rohit")["pushup"] == 2
