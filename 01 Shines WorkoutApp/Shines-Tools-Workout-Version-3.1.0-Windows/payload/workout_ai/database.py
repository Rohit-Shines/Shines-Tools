from __future__ import annotations

import json
import sqlite3
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterator

from .constants import (
    DEFAULT_ENABLED,
    DEFAULT_GOALS,
    DEFAULT_OVERALL_DAILY_GOAL,
    EXERCISE_SHORTCUTS,
    RESERVED_SHORTCUT_KEYS,
    EXERCISES,
    EXERCISE_UNITS,
    REP_EXERCISES,
    TIMED_EXERCISES,
)


class WorkoutDatabase:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def initialize(self) -> None:
        with self.connection() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS profiles (
                    name TEXT PRIMARY KEY,
                    embedding_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS goals (
                    profile_name TEXT NOT NULL,
                    exercise TEXT NOT NULL,
                    daily_goal INTEGER NOT NULL CHECK(daily_goal >= 0),
                    enabled INTEGER NOT NULL DEFAULT 1,
                    unit TEXT NOT NULL DEFAULT 'reps',
                    display_order INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(profile_name, exercise)
                );
                CREATE TABLE IF NOT EXISTS profile_preferences (
                    profile_name TEXT PRIMARY KEY,
                    overall_daily_goal INTEGER NOT NULL DEFAULT 100 CHECK(overall_daily_goal >= 0)
                );
                CREATE TABLE IF NOT EXISTS profile_shortcuts (
                    profile_name TEXT NOT NULL,
                    exercise TEXT NOT NULL,
                    shortcut TEXT NOT NULL,
                    PRIMARY KEY(profile_name, exercise),
                    UNIQUE(profile_name, shortcut)
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_name TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    video_path TEXT,
                    mode TEXT NOT NULL,
                    workout_name TEXT,
                    exercise TEXT,
                    raw_video_path TEXT,
                    analysis_json_path TEXT,
                    detected_reps INTEGER,
                    final_reps INTEGER,
                    manually_corrected INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS rep_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    profile_name TEXT NOT NULL,
                    exercise TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    form_score REAL,
                    rom REAL,
                    duration REAL,
                    value INTEGER NOT NULL DEFAULT 1,
                    unit TEXT NOT NULL DEFAULT 'reps',
                    feedback TEXT,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                );
                CREATE INDEX IF NOT EXISTS idx_rep_profile_date
                    ON rep_events(profile_name, occurred_at);
                CREATE INDEX IF NOT EXISTS idx_rep_session
                    ON rep_events(session_id);
                """
            )

            session_columns = {row[1] for row in con.execute("PRAGMA table_info(sessions)").fetchall()}
            session_additions = {
                "workout_name": "TEXT",
                "exercise": "TEXT",
                "raw_video_path": "TEXT",
                "analysis_json_path": "TEXT",
                "detected_reps": "INTEGER",
                "final_reps": "INTEGER",
                "manually_corrected": "INTEGER NOT NULL DEFAULT 0",
            }
            for column, definition in session_additions.items():
                if column not in session_columns:
                    con.execute(f"ALTER TABLE sessions ADD COLUMN {column} {definition}")

            goal_columns = {row[1] for row in con.execute("PRAGMA table_info(goals)").fetchall()}
            if "enabled" not in goal_columns:
                con.execute("ALTER TABLE goals ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")
            if "unit" not in goal_columns:
                con.execute("ALTER TABLE goals ADD COLUMN unit TEXT NOT NULL DEFAULT 'reps'")
            if "display_order" not in goal_columns:
                con.execute("ALTER TABLE goals ADD COLUMN display_order INTEGER NOT NULL DEFAULT 0")

            # Backfill a deterministic order for existing profiles. New exercises
            # are appended in the canonical EXERCISES order.
            profiles = [str(row[0]) for row in con.execute("SELECT name FROM profiles").fetchall()]
            for profile_name in profiles:
                existing = {
                    str(row["exercise"]): int(row["display_order"] or 0)
                    for row in con.execute(
                        "SELECT exercise, display_order FROM goals WHERE profile_name=?",
                        (profile_name,),
                    ).fetchall()
                }
                used = {value for value in existing.values() if value > 0}
                next_order = max(used, default=0) + 1
                for index, exercise in enumerate(EXERCISES, start=1):
                    current = existing.get(exercise, 0)
                    if current <= 0:
                        con.execute(
                            "UPDATE goals SET display_order=? WHERE profile_name=? AND exercise=?",
                            (next_order, profile_name, exercise),
                        )
                        next_order += 1

            event_columns = {row[1] for row in con.execute("PRAGMA table_info(rep_events)").fetchall()}
            if "value" not in event_columns:
                con.execute("ALTER TABLE rep_events ADD COLUMN value INTEGER NOT NULL DEFAULT 1")
            if "unit" not in event_columns:
                con.execute("ALTER TABLE rep_events ADD COLUMN unit TEXT NOT NULL DEFAULT 'reps'")
            if "feedback" not in event_columns:
                con.execute("ALTER TABLE rep_events ADD COLUMN feedback TEXT")

    def ensure_profile(self, name: str) -> None:
        name = name.strip() or "User"
        now = datetime.now().isoformat(timespec="seconds")
        with self.connection() as con:
            con.execute(
                "INSERT OR IGNORE INTO profiles(name, created_at, updated_at) VALUES(?,?,?)",
                (name, now, now),
            )
            con.execute(
                "INSERT OR IGNORE INTO profile_preferences(profile_name, overall_daily_goal) VALUES(?,?)",
                (name, DEFAULT_OVERALL_DAILY_GOAL),
            )
            for exercise in EXERCISES:
                con.execute(
                    "INSERT OR IGNORE INTO goals(profile_name, exercise, daily_goal, enabled, unit, display_order) VALUES(?,?,?,?,?,?)",
                    (
                        name,
                        exercise,
                        int(DEFAULT_GOALS.get(exercise, 0)),
                        int(bool(DEFAULT_ENABLED.get(exercise, True))),
                        EXERCISE_UNITS.get(exercise, "reps"),
                        EXERCISES.index(exercise) + 1,
                    ),
                )
                # Unit is a schema fact rather than a user preference.
                con.execute(
                    "UPDATE goals SET unit=? WHERE profile_name=? AND exercise=?",
                    (EXERCISE_UNITS.get(exercise, "reps"), name, exercise),
                )
                con.execute(
                    "INSERT OR IGNORE INTO profile_shortcuts(profile_name, exercise, shortcut) VALUES(?,?,?)",
                    (name, exercise, EXERCISE_SHORTCUTS.get(exercise, "")[:1].lower()),
                )

    def profiles(self) -> list[str]:
        with self.connection() as con:
            rows = con.execute("SELECT name FROM profiles ORDER BY lower(name)").fetchall()
        names = [str(row["name"]) for row in rows]
        return names or ["User"]

    @staticmethod
    def _normalise_shortcut(value: object) -> str:
        key = str(value or "").strip().lower()[:1]
        if not key or not key.isalnum():
            raise ValueError("Shortcut must be one letter or number")
        if key in RESERVED_SHORTCUT_KEYS:
            raise ValueError(f"Shortcut {key.upper()} is reserved by the application")
        return key

    def shortcuts(self, profile: str) -> dict[str, str]:
        self.ensure_profile(profile)
        with self.connection() as con:
            rows = con.execute(
                "SELECT exercise, shortcut FROM profile_shortcuts WHERE profile_name=?",
                (profile,),
            ).fetchall()
        values = {str(row["exercise"]): str(row["shortcut"]).upper() for row in rows}
        return {
            exercise: values.get(exercise, EXERCISE_SHORTCUTS.get(exercise, "")).upper()
            for exercise in EXERCISES
        }

    def set_shortcuts(self, profile: str, values: dict[str, object]) -> dict[str, str]:
        self.ensure_profile(profile)
        current = self.shortcuts(profile)
        proposed: dict[str, str] = {}
        used: dict[str, str] = {}
        for exercise in EXERCISES:
            raw = values.get(exercise, current.get(exercise, EXERCISE_SHORTCUTS.get(exercise, "")))
            key = self._normalise_shortcut(raw)
            if key in used:
                other = used[key]
                raise ValueError(
                    f"Shortcut {key.upper()} is assigned to both {other} and {exercise}. Every exercise needs a unique key."
                )
            used[key] = exercise
            proposed[exercise] = key
        with self.connection() as con:
            con.execute("DELETE FROM profile_shortcuts WHERE profile_name=?", (profile,))
            con.executemany(
                "INSERT INTO profile_shortcuts(profile_name, exercise, shortcut) VALUES(?,?,?)",
                [(profile, exercise, proposed[exercise]) for exercise in EXERCISES],
            )
        return {exercise: key.upper() for exercise, key in proposed.items()}

    def reset_shortcuts(self, profile: str) -> dict[str, str]:
        return self.set_shortcuts(profile, EXERCISE_SHORTCUTS)

    def clone_profile_settings(self, source: str, target: str) -> None:
        self.ensure_profile(source)
        self.ensure_profile(target)
        source_settings = self.exercise_settings(source)
        for exercise, config in source_settings.items():
            self.set_goal(target, exercise, int(config["goal"]))
            self.set_exercise_enabled(target, exercise, bool(config["enabled"]))
        self.set_exercise_order(target, list(self.ordered_exercises(source)))
        self.set_overall_daily_goal(target, self.overall_daily_goal(source))
        self.set_shortcuts(target, self.shortcuts(source))

    def save_embedding(self, name: str, embedding: list[float]) -> None:
        self.ensure_profile(name)
        with self.connection() as con:
            con.execute(
                "UPDATE profiles SET embedding_json=?, updated_at=? WHERE name=?",
                (json.dumps(embedding), datetime.now().isoformat(timespec="seconds"), name),
            )

    def embeddings(self) -> dict[str, list[float]]:
        with self.connection() as con:
            rows = con.execute(
                "SELECT name, embedding_json FROM profiles WHERE embedding_json IS NOT NULL"
            ).fetchall()
        return {row["name"]: json.loads(row["embedding_json"]) for row in rows}

    def set_goal(self, profile: str, exercise: str, goal: int) -> None:
        if exercise not in EXERCISES:
            raise ValueError(f"Unknown exercise: {exercise}")
        self.ensure_profile(profile)
        with self.connection() as con:
            con.execute(
                "INSERT INTO goals(profile_name, exercise, daily_goal, enabled, unit, display_order) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(profile_name, exercise) DO UPDATE SET daily_goal=excluded.daily_goal",
                (
                    profile,
                    exercise,
                    max(0, int(goal)),
                    int(bool(DEFAULT_ENABLED.get(exercise, True))),
                    EXERCISE_UNITS.get(exercise, "reps"),
                    EXERCISES.index(exercise) + 1,
                ),
            )

    def set_exercise_enabled(self, profile: str, exercise: str, enabled: bool) -> None:
        if exercise not in EXERCISES:
            raise ValueError(f"Unknown exercise: {exercise}")
        self.ensure_profile(profile)
        with self.connection() as con:
            con.execute(
                "UPDATE goals SET enabled=? WHERE profile_name=? AND exercise=?",
                (int(bool(enabled)), profile, exercise),
            )

    def exercise_settings(self, profile: str) -> dict[str, dict[str, object]]:
        self.ensure_profile(profile)
        with self.connection() as con:
            rows = con.execute(
                "SELECT exercise, daily_goal, enabled, unit, display_order FROM goals WHERE profile_name=?",
                (profile,),
            ).fetchall()
        by_name = {str(row["exercise"]): row for row in rows}
        result: dict[str, dict[str, object]] = {}
        for exercise in EXERCISES:
            row = by_name.get(exercise)
            result[exercise] = {
                "goal": int(row["daily_goal"]) if row is not None else int(DEFAULT_GOALS.get(exercise, 0)),
                "enabled": bool(row["enabled"]) if row is not None else bool(DEFAULT_ENABLED.get(exercise, True)),
                "unit": EXERCISE_UNITS.get(exercise, "reps"),
                "order": int(row["display_order"]) if row is not None else EXERCISES.index(exercise) + 1,
            }
        return result

    def ordered_exercises(self, profile: str) -> tuple[str, ...]:
        settings = self.exercise_settings(profile)
        return tuple(sorted(EXERCISES, key=lambda exercise: (int(settings[exercise]["order"]), EXERCISES.index(exercise))))

    def set_exercise_order(self, profile: str, ordered_exercises: list[str] | tuple[str, ...]) -> None:
        self.ensure_profile(profile)
        clean: list[str] = []
        for exercise in ordered_exercises:
            if exercise in EXERCISES and exercise not in clean:
                clean.append(exercise)
        for exercise in EXERCISES:
            if exercise not in clean:
                clean.append(exercise)
        with self.connection() as con:
            for index, exercise in enumerate(clean, start=1):
                con.execute(
                    "UPDATE goals SET display_order=? WHERE profile_name=? AND exercise=?",
                    (index, profile, exercise),
                )

    def enabled_exercises(self, profile: str) -> tuple[str, ...]:
        settings = self.exercise_settings(profile)
        enabled = tuple(exercise for exercise in self.ordered_exercises(profile) if bool(settings[exercise]["enabled"]))
        return enabled

    def goals(self, profile: str) -> dict[str, int]:
        settings = self.exercise_settings(profile)
        return {exercise: int(settings[exercise]["goal"]) for exercise in EXERCISES}

    def set_overall_daily_goal(self, profile: str, goal: int) -> None:
        self.ensure_profile(profile)
        with self.connection() as con:
            con.execute(
                "INSERT INTO profile_preferences(profile_name, overall_daily_goal) VALUES(?,?) "
                "ON CONFLICT(profile_name) DO UPDATE SET overall_daily_goal=excluded.overall_daily_goal",
                (profile, max(0, int(goal))),
            )

    def overall_daily_goal(self, profile: str) -> int:
        self.ensure_profile(profile)
        with self.connection() as con:
            row = con.execute(
                "SELECT overall_daily_goal FROM profile_preferences WHERE profile_name=?",
                (profile,),
            ).fetchone()
        return int(row["overall_daily_goal"]) if row else DEFAULT_OVERALL_DAILY_GOAL

    def start_session(
        self,
        profile: str,
        started_at: datetime,
        video_path: Path | None,
        mode: str,
        *,
        workout_name: str | None = None,
        exercise: str | None = None,
        raw_video_path: Path | None = None,
        analysis_json_path: Path | None = None,
    ) -> int:
        self.ensure_profile(profile)
        with self.connection() as con:
            cursor = con.execute(
                "INSERT INTO sessions(profile_name, started_at, video_path, mode, workout_name, exercise, "
                "raw_video_path, analysis_json_path) VALUES(?,?,?,?,?,?,?,?)",
                (
                    profile,
                    started_at.isoformat(timespec="seconds"),
                    str(video_path) if video_path else None,
                    mode,
                    workout_name,
                    exercise,
                    str(raw_video_path) if raw_video_path else None,
                    str(analysis_json_path) if analysis_json_path else None,
                ),
            )
            return int(cursor.lastrowid)

    def finish_session(self, session_id: int, ended_at: datetime) -> None:
        with self.connection() as con:
            con.execute(
                "UPDATE sessions SET ended_at=? WHERE id=?",
                (ended_at.isoformat(timespec="seconds"), session_id),
            )

    def update_offline_analysis(
        self,
        session_id: int,
        *,
        detected_reps: int,
        final_reps: int,
        manually_corrected: bool,
        video_path: Path | None,
        raw_video_path: Path,
        analysis_json_path: Path,
    ) -> None:
        with self.connection() as con:
            con.execute(
                "UPDATE sessions SET detected_reps=?, final_reps=?, manually_corrected=?, video_path=?, "
                "raw_video_path=?, analysis_json_path=? WHERE id=?",
                (
                    int(detected_reps),
                    int(final_reps),
                    int(bool(manually_corrected)),
                    str(video_path) if video_path else None,
                    str(raw_video_path),
                    str(analysis_json_path),
                    session_id,
                ),
            )

    def add_rep(
        self,
        session_id: int,
        profile: str,
        exercise: str,
        occurred_at: datetime,
        form_score: float | None,
        rom: float | None,
        duration: float | None,
        value: int = 1,
        unit: str | None = None,
        feedback: str | None = None,
    ) -> None:
        if exercise not in EXERCISES:
            raise ValueError(f"Unknown exercise: {exercise}")
        event_unit = unit or EXERCISE_UNITS.get(exercise, "reps")
        with self.connection() as con:
            con.execute(
                "INSERT INTO rep_events(session_id, profile_name, exercise, occurred_at, form_score, rom, duration, value, unit, feedback) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    session_id,
                    profile,
                    exercise,
                    occurred_at.isoformat(timespec="milliseconds"),
                    form_score,
                    rom,
                    duration,
                    max(1, int(value)),
                    event_unit,
                    str(feedback or "")[:300] or None,
                ),
            )

    def delete_session_reps(self, session_id: int) -> None:
        with self.connection() as con:
            con.execute("DELETE FROM rep_events WHERE session_id=?", (session_id,))

    @staticmethod
    def _blank_totals() -> dict[str, int]:
        return {exercise: 0 for exercise in EXERCISES}

    def totals_between(
        self,
        profile: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> dict[str, int]:
        clauses = ["profile_name=?"]
        params: list[object] = [profile]
        if start is not None:
            clauses.append("occurred_at>=?")
            params.append(start.isoformat())
        if end is not None:
            clauses.append("occurred_at<?")
            params.append(end.isoformat())
        sql = (
            "SELECT exercise, SUM(COALESCE(value,1)) AS total FROM rep_events WHERE "
            + " AND ".join(clauses)
            + " GROUP BY exercise"
        )
        with self.connection() as con:
            rows = con.execute(sql, params).fetchall()
        totals = self._blank_totals()
        totals.update({str(row["exercise"]): int(row["total"] or 0) for row in rows})
        return totals

    def totals_for_day(self, profile: str, day: date | None = None) -> dict[str, int]:
        day = day or date.today()
        start = datetime.combine(day, datetime.min.time())
        return self.totals_between(profile, start, start + timedelta(days=1))

    def period_totals(
        self,
        profile: str,
        period: str,
        reference: date | None = None,
    ) -> dict[str, int]:
        ref = reference or date.today()
        if period == "today":
            start_date = ref
            end_date = ref + timedelta(days=1)
        elif period == "week":
            start_date = ref - timedelta(days=ref.weekday())
            end_date = start_date + timedelta(days=7)
        elif period == "month":
            start_date = ref.replace(day=1)
            end_date = date(start_date.year + (start_date.month == 12), 1 if start_date.month == 12 else start_date.month + 1, 1)
        elif period == "year":
            start_date = date(ref.year, 1, 1)
            end_date = date(ref.year + 1, 1, 1)
        elif period == "all":
            return self.totals_between(profile)
        else:
            raise ValueError("period must be today, week, month, year, or all")
        return self.totals_between(
            profile,
            datetime.combine(start_date, datetime.min.time()),
            datetime.combine(end_date, datetime.min.time()),
        )

    def period_overview(self, profile: str, reference: date | None = None) -> dict[str, dict[str, int]]:
        return {
            period: self.period_totals(profile, period, reference)
            for period in ("today", "week", "month", "year", "all")
        }

    def session_counts(self, session_id: int) -> dict[str, int]:
        with self.connection() as con:
            rows = con.execute(
                "SELECT exercise, SUM(COALESCE(value,1)) AS total FROM rep_events WHERE session_id=? GROUP BY exercise",
                (session_id,),
            ).fetchall()
        totals = self._blank_totals()
        totals.update({str(row["exercise"]): int(row["total"] or 0) for row in rows})
        return totals

    def recent_sessions(self, profile: str, limit: int = 25) -> list[sqlite3.Row]:
        with self.connection() as con:
            rows = con.execute(
                "SELECT s.id, s.started_at, s.ended_at, s.workout_name, s.exercise, s.mode, "
                "s.video_path, s.raw_video_path, s.analysis_json_path, s.detected_reps, "
                "s.final_reps, s.manually_corrected, COALESCE(SUM(COALESCE(r.value,1)),0) AS live_reps "
                "FROM sessions s LEFT JOIN rep_events r ON r.session_id=s.id "
                "WHERE s.profile_name=? GROUP BY s.id ORDER BY s.started_at DESC LIMIT ?",
                (profile, int(limit)),
            ).fetchall()
        return list(rows)

    def all_sessions(self, profile: str) -> list[sqlite3.Row]:
        return self.recent_sessions(profile, 1_000_000)

    def all_rep_events(self, profile: str) -> list[sqlite3.Row]:
        with self.connection() as con:
            rows = con.execute(
                "SELECT id, session_id, profile_name, exercise, occurred_at, form_score, rom, duration, feedback, "
                "COALESCE(value,1) AS value, COALESCE(unit,'reps') AS unit "
                "FROM rep_events WHERE profile_name=? ORDER BY occurred_at",
                (profile,),
            ).fetchall()
        return list(rows)

    def aggregate(self, profile: str, period: str, limit: int = 30) -> list[sqlite3.Row]:
        formats = {
            "daily": "%Y-%m-%d",
            "weekly": "%Y-W%W",
            "monthly": "%Y-%m",
            "yearly": "%Y",
        }
        if period not in formats:
            raise ValueError("period must be daily, weekly, monthly, or yearly")
        fmt = formats[period]
        with self.connection() as con:
            rows = con.execute(
                "SELECT strftime(?, occurred_at) AS bucket, exercise, SUM(COALESCE(value,1)) AS reps, "
                "AVG(form_score) AS avg_form FROM rep_events WHERE profile_name=? "
                "GROUP BY bucket, exercise ORDER BY bucket DESC LIMIT ?",
                (fmt, profile, int(limit) * len(EXERCISES)),
            ).fetchall()
        return list(rows)

    def active_days(self, profile: str) -> list[date]:
        with self.connection() as con:
            rows = con.execute(
                "SELECT DISTINCT substr(occurred_at,1,10) AS day FROM rep_events "
                "WHERE profile_name=? ORDER BY day DESC",
                (profile,),
            ).fetchall()
        result: list[date] = []
        for row in rows:
            try:
                result.append(date.fromisoformat(str(row["day"])))
            except ValueError:
                continue
        return result

    def streak(self, profile: str, reference: date | None = None) -> int:
        ref = reference or date.today()
        days = set(self.active_days(profile))
        if not days:
            return 0
        cursor = ref if ref in days else ref - timedelta(days=1)
        if cursor not in days:
            return 0
        streak = 0
        while cursor in days:
            streak += 1
            cursor -= timedelta(days=1)
        return streak

    def personal_bests(self, profile: str) -> dict[str, int]:
        """Highest value completed in one saved session for every exercise."""
        self.ensure_profile(profile)
        with self.connection() as con:
            rows = con.execute(
                "SELECT exercise, MAX(session_total) AS best FROM ("
                "SELECT session_id, exercise, SUM(COALESCE(value,1)) AS session_total "
                "FROM rep_events WHERE profile_name=? GROUP BY session_id, exercise"
                ") GROUP BY exercise",
                (profile,),
            ).fetchall()
        result = self._blank_totals()
        result.update({str(row["exercise"]): int(row["best"] or 0) for row in rows})
        return result

    def personal_best_day(self, profile: str) -> tuple[str | None, int]:
        placeholders = ",".join("?" for _ in REP_EXERCISES)
        with self.connection() as con:
            row = con.execute(
                f"SELECT substr(occurred_at,1,10) AS day, SUM(COALESCE(value,1)) AS reps FROM rep_events "
                f"WHERE profile_name=? AND exercise IN ({placeholders}) GROUP BY day ORDER BY reps DESC, day DESC LIMIT 1",
                (profile, *REP_EXERCISES),
            ).fetchone()
        if row is None:
            return None, 0
        return str(row["day"]), int(row["reps"] or 0)

    def coaching_insights(self, profile: str) -> dict[str, object]:
        """Build conservative form trends from stored completed movements."""
        self.ensure_profile(profile)
        rows_by_exercise: dict[str, list[sqlite3.Row]] = {}
        with self.connection() as con:
            for exercise in EXERCISES:
                rows_by_exercise[exercise] = list(
                    con.execute(
                        "SELECT form_score, feedback, occurred_at, COALESCE(value,1) AS value "
                        "FROM rep_events WHERE profile_name=? AND exercise=? AND form_score IS NOT NULL "
                        "ORDER BY occurred_at DESC LIMIT 40",
                        (profile, exercise),
                    ).fetchall()
                )

        items: list[dict[str, object]] = []
        for exercise in self.ordered_exercises(profile):
            rows = rows_by_exercise.get(exercise, [])
            recent = rows[:20]
            previous = rows[20:40]
            recent_scores = [float(row["form_score"]) for row in recent if row["form_score"] is not None]
            previous_scores = [float(row["form_score"]) for row in previous if row["form_score"] is not None]
            current = round(sum(recent_scores) / len(recent_scores), 1) if recent_scores else None
            prior = round(sum(previous_scores) / len(previous_scores), 1) if previous_scores else None
            delta = round(current - prior, 1) if current is not None and prior is not None else None
            feedbacks = [str(row["feedback"]).strip() for row in recent if row["feedback"]]
            common_feedback = (
                Counter(feedbacks).most_common(1)[0][0]
                if feedbacks
                else "Complete more repetitions to generate personalised guidance."
            )
            if current is None:
                status = "No data"
            elif current >= 85:
                status = "Excellent"
            elif current >= 75:
                status = "Good"
            elif current >= 65:
                status = "Improving"
            else:
                status = "Needs attention"
            if delta is None:
                trend = "Collecting baseline"
            elif delta >= 3:
                trend = f"Improved {delta:.1f}%"
            elif delta <= -3:
                trend = f"Down {abs(delta):.1f}%"
            else:
                trend = "Stable"
            items.append({
                "exercise": exercise,
                "average_form": current,
                "previous_form": prior,
                "delta": delta,
                "status": status,
                "trend": trend,
                "feedback": common_feedback,
                "sample_count": len(recent_scores),
            })

        populated = [item for item in items if item["average_form"] is not None]
        strongest = max(populated, key=lambda item: float(item["average_form"]), default=None)
        attention = min(populated, key=lambda item: float(item["average_form"]), default=None)
        improved = max(
            [item for item in populated if item["delta"] is not None],
            key=lambda item: float(item["delta"]),
            default=None,
        )
        top_rows: list[dict[str, object]] = []
        for candidate in (improved, attention):
            if candidate and candidate not in top_rows:
                top_rows.append(candidate)
        return {
            "items": items,
            "top_rows": top_rows[:2],
            "strongest": strongest,
            "attention": attention,
        }

    def summary(self, profile: str) -> dict[str, object]:
        overview = self.period_overview(profile)
        best_day, best_reps = self.personal_best_day(profile)
        rep_totals = {
            period: sum(values.get(exercise, 0) for exercise in REP_EXERCISES)
            for period, values in overview.items()
        }
        timed_totals = {
            period: sum(values.get(exercise, 0) for exercise in TIMED_EXERCISES)
            for period, values in overview.items()
        }
        overall_goal = self.overall_daily_goal(profile)
        today_reps = rep_totals["today"]
        if overall_goal <= 0:
            overall_status = "none"
        elif today_reps < overall_goal:
            overall_status = "below"
        elif today_reps == overall_goal:
            overall_status = "met"
        else:
            overall_status = "exceeded"
        return {
            "profile": profile,
            "periods": overview,
            "period_total_reps": rep_totals,
            "period_total_seconds": timed_totals,
            "goals": self.goals(profile),
            "exercise_settings": self.exercise_settings(profile),
            "overall_daily_goal": overall_goal,
            "overall_goal_status": overall_status,
            "streak_days": self.streak(profile),
            "active_days": len(self.active_days(profile)),
            "personal_best_day": best_day,
            "personal_best_reps": best_reps,
            "personal_bests": self.personal_bests(profile),
            "shortcuts": self.shortcuts(profile),
        }
