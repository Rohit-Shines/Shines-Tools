from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Hashable, Optional

import numpy as np


class MedianEMAFilter:
    """Short median window followed by exponential smoothing.

    The median suppresses one-frame pose glitches. EMA keeps the UI responsive
    while preventing threshold chatter around rep boundaries.
    """

    def __init__(self, window: int = 5, alpha: float = 0.38):
        self.window = max(3, int(window))
        self.alpha = float(alpha)
        self._values: dict[Hashable, deque[float]] = defaultdict(
            lambda: deque(maxlen=self.window)
        )
        self._ema: dict[Hashable, float] = {}

    def update(self, key: Hashable, value: Optional[float]) -> Optional[float]:
        if value is None or not np.isfinite(value):
            return self._ema.get(key)
        values = self._values[key]
        values.append(float(value))
        median = float(np.median(values))
        previous = self._ema.get(key, median)
        current = self.alpha * median + (1.0 - self.alpha) * previous
        self._ema[key] = current
        return current

    def reset(self, key: Hashable | None = None) -> None:
        if key is None:
            self._values.clear()
            self._ema.clear()
            return
        self._values.pop(key, None)
        self._ema.pop(key, None)


@dataclass
class StabilityCounter:
    required_frames: int
    count: int = 0

    def update(self, condition: bool) -> bool:
        self.count = min(self.required_frames, self.count + 1) if condition else 0
        return self.count >= self.required_frames

    def reset(self) -> None:
        self.count = 0
