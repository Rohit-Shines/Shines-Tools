from __future__ import annotations

import numpy as np

from workout_ai.offline_analyzer import count_cycles_from_signal


def make_cycles(count: int, fps: float = 30.0, top: float = 0.88, bottom: float = 0.18):
    parts = [np.full(int(0.4 * fps), top)]
    for _ in range(count):
        parts.append(np.linspace(top, bottom, int(0.35 * fps), endpoint=False))
        parts.append(np.linspace(bottom, top, int(0.35 * fps), endpoint=False))
        parts.append(np.full(int(0.12 * fps), top))
    return np.concatenate(parts)


def test_offline_counter_detects_ten_complete_pushup_like_cycles():
    rng = np.random.default_rng(42)
    signal = make_cycles(10) + rng.normal(0.0, 0.025, size=len(make_cycles(10)))
    reps, _, _ = count_cycles_from_signal(signal, 30.0)
    assert len(reps) == 10


def test_offline_counter_accepts_shallow_but_consistent_human_range():
    rng = np.random.default_rng(7)
    signal = make_cycles(8, top=0.68, bottom=0.36)
    signal += rng.normal(0.0, 0.012, size=len(signal))
    reps, _, _ = count_cycles_from_signal(signal, 30.0)
    assert len(reps) == 8


def test_offline_counter_tolerates_short_pose_dropouts():
    signal = make_cycles(6)
    valid = np.ones(len(signal), dtype=bool)
    # Four-frame dropouts mimic a wrist/elbow being briefly hidden.
    for start in (45, 102, 160):
        signal[start : start + 4] = np.nan
        valid[start : start + 4] = False
    reps, _, _ = count_cycles_from_signal(signal, 30.0, valid)
    assert len(reps) == 6


def test_offline_counter_does_not_count_static_motion_noise():
    rng = np.random.default_rng(9)
    signal = 0.7 + rng.normal(0.0, 0.02, size=240)
    reps, _, _ = count_cycles_from_signal(signal, 30.0)
    assert len(reps) == 0
