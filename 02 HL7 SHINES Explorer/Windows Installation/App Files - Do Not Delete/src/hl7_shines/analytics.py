from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import re
from typing import Iterable

from .models import HL7Message


@dataclass(frozen=True)
class FieldStatistic:
    path: str
    present_count: int
    message_count: int
    unique_values: tuple[tuple[str, int], ...]
    min_length: int
    max_length: int

    @property
    def fill_rate(self) -> float:
        return self.present_count / self.message_count if self.message_count else 0.0


@dataclass(frozen=True)
class DiffEntry:
    path: str
    left: str
    right: str
    kind: str


class HL7Analytics:
    @staticmethod
    def matches(message: HL7Message, query: str) -> bool:
        search = query.strip()
        if not search:
            return True
        if ":" in search:
            possible_path, expected = search.split(":", 1)
            if re.fullmatch(r"[A-Za-z0-9]{3}(?:\[\d+\])?-\d+(?:\[\d+\])?(?:\.\d+){0,2}", possible_path.strip()):
                try:
                    return expected.casefold() in message.value_at(possible_path.strip()).casefold()
                except ValueError:
                    return False
        return search.casefold() in message.raw.casefold() or search.casefold() in " ".join(message.metadata().values()).casefold()

    @staticmethod
    def statistics(messages: Iterable[HL7Message]) -> list[FieldStatistic]:
        message_list = list(messages)
        values_by_path: dict[str, list[str]] = defaultdict(list)
        present_by_path: dict[str, set[str]] = defaultdict(set)
        known_paths: set[str] = set()
        for message in message_list:
            for path, value in message.all_paths(include_components=False):
                # Aggregate repeated-segment occurrences into the base path while
                # counting fill rate once per message.
                base = re.sub(r"\[\d+\]", "", path)
                known_paths.add(base)
                if value:
                    values_by_path[base].append(value)
                    present_by_path[base].add(message.id)

        stats: list[FieldStatistic] = []
        for path in known_paths:
            values = values_by_path.get(path, [])
            counts = Counter(values)
            lengths = [len(value) for value in values]
            stats.append(
                FieldStatistic(
                    path=path,
                    present_count=len(present_by_path.get(path, set())),
                    message_count=len(message_list),
                    unique_values=tuple(counts.most_common(12)),
                    min_length=min(lengths) if lengths else 0,
                    max_length=max(lengths) if lengths else 0,
                )
            )
        return sorted(stats, key=lambda item: (item.path.split("-")[0], int(item.path.split("-")[1])))

    @staticmethod
    def message_type_counts(messages: Iterable[HL7Message]) -> Counter[str]:
        return Counter(message.message_type for message in messages)

    @staticmethod
    def diff(left: HL7Message, right: HL7Message, include_unchanged: bool = True) -> list[DiffEntry]:
        left_map = dict(left.all_paths(include_components=False))
        right_map = dict(right.all_paths(include_components=False))
        entries: list[DiffEntry] = []
        for path in sorted(set(left_map) | set(right_map), key=HL7Analytics._path_sort):
            left_value = left_map.get(path, "")
            right_value = right_map.get(path, "")
            if path not in left_map:
                kind = "added"
            elif path not in right_map:
                kind = "removed"
            elif left_value != right_value:
                kind = "changed"
            else:
                kind = "unchanged"
            if include_unchanged or kind != "unchanged":
                entries.append(DiffEntry(path, left_value, right_value, kind))
        return entries

    @staticmethod
    def _path_sort(path: str) -> tuple:
        match = re.match(r"([A-Z0-9]{3})\[(\d+)\]-(\d+)", path)
        if not match:
            return (path, 0, 0)
        return (match.group(1), int(match.group(2)), int(match.group(3)))
