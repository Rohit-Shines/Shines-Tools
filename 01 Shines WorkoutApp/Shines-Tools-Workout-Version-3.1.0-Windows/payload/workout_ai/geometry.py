from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

import numpy as np


@dataclass(frozen=True)
class Landmark:
    x: float
    y: float
    z: float = 0.0
    visibility: float = 1.0
    presence: float = 1.0


@dataclass
class PoseFrame:
    image: list[Landmark]
    world: list[Landmark]
    timestamp: float

    def lm(self, index: int, *, world: bool = False) -> Landmark:
        points = self.world if world and self.world else self.image
        return points[index]

    def visible(self, indexes: Iterable[int], threshold: float = 0.55) -> bool:
        return all(
            self.image[i].visibility >= threshold and self.image[i].presence >= threshold
            for i in indexes
        )


def as_np(p: Landmark, dimensions: int = 3) -> np.ndarray:
    if dimensions == 2:
        return np.array([p.x, p.y], dtype=np.float64)
    return np.array([p.x, p.y, p.z], dtype=np.float64)


def distance(a: Landmark, b: Landmark, dimensions: int = 2) -> float:
    return float(np.linalg.norm(as_np(a, dimensions) - as_np(b, dimensions)))


def angle(a: Landmark, b: Landmark, c: Landmark, dimensions: int = 3) -> float:
    """Return angle ABC in degrees, robust to near-zero segments."""
    ba = as_np(a, dimensions) - as_np(b, dimensions)
    bc = as_np(c, dimensions) - as_np(b, dimensions)
    denom = float(np.linalg.norm(ba) * np.linalg.norm(bc))
    if denom < 1e-8:
        return float("nan")
    cosine = float(np.clip(np.dot(ba, bc) / denom, -1.0, 1.0))
    return float(np.degrees(np.arccos(cosine)))


def line_angle_to_horizontal(a: Landmark, b: Landmark) -> float:
    """Acute 2-D angle (0-90°) between line AB and the image horizontal."""
    dx = abs(b.x - a.x)
    dy = abs(b.y - a.y)
    if dx + dy < 1e-8:
        return 90.0
    return float(math.degrees(math.atan2(dy, dx)))


def line_angle_to_vertical(a: Landmark, b: Landmark) -> float:
    return 90.0 - line_angle_to_horizontal(a, b)


def midpoint(a: Landmark, b: Landmark) -> Landmark:
    return Landmark(
        x=(a.x + b.x) / 2.0,
        y=(a.y + b.y) / 2.0,
        z=(a.z + b.z) / 2.0,
        visibility=min(a.visibility, b.visibility),
        presence=min(a.presence, b.presence),
    )


def robust_mean(values: Sequence[Optional[float]]) -> Optional[float]:
    usable = [float(v) for v in values if v is not None and np.isfinite(v)]
    if not usable:
        return None
    return float(np.median(usable))


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))
