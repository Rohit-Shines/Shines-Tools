from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import re
import uuid
from typing import Iterable


@dataclass(frozen=True)
class Delimiters:
    field: str = "|"
    component: str = "^"
    repetition: str = "~"
    escape: str = "\\"
    subcomponent: str = "&"

    @property
    def encoding_characters(self) -> str:
        return f"{self.component}{self.repetition}{self.escape}{self.subcomponent}"


@dataclass
class HL7Segment:
    name: str
    fields: list[str]
    occurrence: int = 1
    raw: str = ""

    def value(self, field_number: int) -> str:
        if self.name == "MSH":
            if field_number == 1:
                return self.raw[3] if len(self.raw) > 3 else "|"
            if field_number == 2:
                return self.fields[0] if self.fields else ""
            index = field_number - 2
        else:
            index = field_number - 1
        return self.fields[index] if 0 <= index < len(self.fields) else ""

    def set_value(self, field_number: int, value: str, delimiters: Delimiters) -> None:
        if self.name == "MSH" and field_number == 1:
            raise ValueError("MSH-1 must be changed in raw mode and reparsed.")
        index = field_number - 2 if self.name == "MSH" else field_number - 1
        while len(self.fields) <= index:
            self.fields.append("")
        self.fields[index] = value
        self.raw = self.to_er7(delimiters)

    def to_er7(self, delimiters: Delimiters) -> str:
        if self.name == "MSH":
            return "MSH" + delimiters.field + delimiters.field.join(self.fields)
        return self.name + delimiters.field + delimiters.field.join(self.fields)


@dataclass
class HL7Message:
    raw: str
    delimiters: Delimiters
    segments: list[HL7Segment]
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def segments_named(self, name: str) -> list[HL7Segment]:
        target = name.upper()
        return [segment for segment in self.segments if segment.name == target]

    def segment(self, name: str, occurrence: int = 1) -> HL7Segment | None:
        matches = self.segments_named(name)
        return matches[occurrence - 1] if 0 < occurrence <= len(matches) else None

    def value_at(self, path: str) -> str:
        parsed = parse_path(path)
        segment = self.segment(parsed.segment, parsed.segment_occurrence)
        if not segment:
            return ""
        value = segment.value(parsed.field)
        repetitions = value.split(self.delimiters.repetition) if value else [""]
        rep_index = parsed.repetition - 1
        if rep_index >= len(repetitions):
            return ""
        value = repetitions[rep_index]
        if parsed.component is not None:
            components = value.split(self.delimiters.component)
            comp_index = parsed.component - 1
            if comp_index >= len(components):
                return ""
            value = components[comp_index]
        if parsed.subcomponent is not None:
            subcomponents = value.split(self.delimiters.subcomponent)
            sub_index = parsed.subcomponent - 1
            if sub_index >= len(subcomponents):
                return ""
            value = subcomponents[sub_index]
        return value

    def set_value_at(self, path: str, new_value: str) -> None:
        parsed = parse_path(path)
        segment = self.segment(parsed.segment, parsed.segment_occurrence)
        if not segment:
            raise KeyError(f"Segment not found: {parsed.segment}[{parsed.segment_occurrence}]")
        if parsed.component is None and parsed.subcomponent is None and parsed.repetition == 1:
            segment.set_value(parsed.field, new_value, self.delimiters)
            self.rebuild_raw()
            return

        field_value = segment.value(parsed.field)
        repetitions = field_value.split(self.delimiters.repetition) if field_value else [""]
        while len(repetitions) < parsed.repetition:
            repetitions.append("")
        rep_index = parsed.repetition - 1

        if parsed.component is None:
            repetitions[rep_index] = new_value
        else:
            components = repetitions[rep_index].split(self.delimiters.component) if repetitions[rep_index] else [""]
            while len(components) < parsed.component:
                components.append("")
            comp_index = parsed.component - 1
            if parsed.subcomponent is None:
                components[comp_index] = new_value
            else:
                subs = components[comp_index].split(self.delimiters.subcomponent) if components[comp_index] else [""]
                while len(subs) < parsed.subcomponent:
                    subs.append("")
                subs[parsed.subcomponent - 1] = new_value
                components[comp_index] = self.delimiters.subcomponent.join(subs)
            repetitions[rep_index] = self.delimiters.component.join(components)

        segment.set_value(parsed.field, self.delimiters.repetition.join(repetitions), self.delimiters)
        self.rebuild_raw()

    def rebuild_raw(self) -> None:
        self.raw = "\r".join(segment.to_er7(self.delimiters) for segment in self.segments)

    @property
    def message_type(self) -> str:
        code = self.value_at("MSH-9.1")
        trigger = self.value_at("MSH-9.2")
        return "^".join(part for part in (code, trigger) if part) or "Unknown"

    @property
    def message_structure(self) -> str:
        return self.value_at("MSH-9.3")

    @property
    def control_id(self) -> str:
        return self.value_at("MSH-10")

    @property
    def patient_name(self) -> str:
        family = self.value_at("PID-5.1")
        given = self.value_at("PID-5.2")
        middle = self.value_at("PID-5.3")
        return " ".join(part for part in (given, middle, family) if part) or "Not present"

    @property
    def mrn(self) -> str:
        return self.value_at("PID-3.1") or "Not present"

    @property
    def visit(self) -> str:
        return self.value_at("PV1-19.1") or self.value_at("PID-18.1") or "Not present"

    @property
    def location(self) -> str:
        parts = [self.value_at(f"PV1-3.{idx}") for idx in range(1, 5)]
        return " · ".join(part for part in parts if part) or "Not present"

    @property
    def message_date(self) -> str:
        raw = self.value_at("MSH-7")
        if not raw:
            return "Not present"
        for fmt in ("%Y%m%d%H%M%S%z", "%Y%m%d%H%M%S", "%Y%m%d%H%M", "%Y%m%d"):
            try:
                dt = datetime.strptime(raw, fmt)
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
        return raw

    @property
    def size_bytes(self) -> int:
        return len(self.raw.encode("utf-8"))

    def metadata(self) -> dict[str, str]:
        return {
            "Patient Name": self.patient_name,
            "MRN": self.mrn,
            "Visit": self.visit,
            "Location": self.location,
            "Message Date": self.message_date,
            "Control ID": self.control_id or "Not present",
            "Sending Application": self.value_at("MSH-3") or "Not present",
            "Receiving Application": self.value_at("MSH-5") or "Not present",
            "Version ID": self.value_at("MSH-12") or "Not present",
            "Segments": str(len(self.segments)),
            "Size": format_bytes(self.size_bytes),
        }

    def all_paths(self, include_components: bool = True) -> Iterable[tuple[str, str]]:
        for segment in self.segments:
            for field_number in range(1, self._max_field_number(segment) + 1):
                value = segment.value(field_number)
                path = f"{segment.name}[{segment.occurrence}]-{field_number}"
                yield path, value
                if include_components and value:
                    for rep_idx, repetition in enumerate(value.split(self.delimiters.repetition), start=1):
                        components = repetition.split(self.delimiters.component)
                        if len(components) > 1:
                            for comp_idx, component in enumerate(components, start=1):
                                comp_path = f"{path}[{rep_idx}].{comp_idx}"
                                yield comp_path, component
                                subs = component.split(self.delimiters.subcomponent)
                                if len(subs) > 1:
                                    for sub_idx, sub in enumerate(subs, start=1):
                                        yield f"{comp_path}.{sub_idx}", sub

    @staticmethod
    def _max_field_number(segment: HL7Segment) -> int:
        return len(segment.fields) + (1 if segment.name == "MSH" else 0)


@dataclass(frozen=True)
class FieldPath:
    segment: str
    segment_occurrence: int
    field: int
    repetition: int = 1
    component: int | None = None
    subcomponent: int | None = None


_PATH_RE = re.compile(
    r"^(?P<segment>[A-Za-z0-9]{3})(?:\[(?P<seg_occ>\d+)\])?-(?P<field>\d+)"
    r"(?:\[(?P<rep>\d+)\])?(?:\.(?P<component>\d+))?(?:\.(?P<subcomponent>\d+))?$"
)


def parse_path(path: str) -> FieldPath:
    match = _PATH_RE.fullmatch(path.strip())
    if not match:
        raise ValueError(f"Invalid HL7 path: {path}")
    return FieldPath(
        segment=match.group("segment").upper(),
        segment_occurrence=int(match.group("seg_occ") or 1),
        field=int(match.group("field")),
        repetition=int(match.group("rep") or 1),
        component=int(match.group("component")) if match.group("component") else None,
        subcomponent=int(match.group("subcomponent")) if match.group("subcomponent") else None,
    )


def format_bytes(value: int) -> str:
    if value < 1024:
        return f"{value} B"
    if value < 1024 * 1024:
        return f"{value / 1024:.1f} KB"
    return f"{value / (1024 * 1024):.1f} MB"
