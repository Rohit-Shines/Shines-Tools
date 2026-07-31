from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from .catalog import REQUIRED_FIELDS, SEGMENT_NAMES
from .models import HL7Message


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    path: str
    message: str
    suggestion: str = ""


_TS_RE = re.compile(r"^\d{4}(?:\d{2}(?:\d{2}(?:\d{2}(?:\d{2}(?:\d{2}(?:\.\d{1,4})?)?)?)?)?)?(?:[+-]\d{4})?$|")
_NUMERIC_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)$")


class HL7Validator:
    @staticmethod
    def validate(message: HL7Message) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for path in sorted(REQUIRED_FIELDS):
            if not message.value_at(path):
                issues.append(ValidationIssue("error", path, "Required field is empty.", "Populate the field according to the interface specification."))

        for segment in message.segments:
            if segment.name not in SEGMENT_NAMES:
                if segment.name.startswith("Z"):
                    issues.append(ValidationIssue("info", segment.name, "Custom Z-segment detected.", "Validate this segment against the local implementation guide."))
                else:
                    issues.append(ValidationIssue("warning", segment.name, "Segment is not in the bundled quick-reference catalog.", "Confirm the segment name and HL7 version."))

        for path in ("MSH-7", "EVN-2", "EVN-6", "PV1-44", "PV1-45", "OBR-7", "OBR-22", "OBX-14", "DG1-5"):
            value = message.value_at(path)
            if value and not HL7Validator._valid_timestamp(value):
                issues.append(ValidationIssue("warning", path, f"Timestamp has an unexpected format: {value}", "Use HL7 TS format such as YYYYMMDDHHMMSS-0400."))

        message_code = message.value_at("MSH-9.1")
        trigger = message.value_at("MSH-9.2")
        if not message_code or not trigger:
            issues.append(ValidationIssue("error", "MSH-9", "Message type or trigger event is incomplete.", "Populate MSH-9.1 and MSH-9.2."))

        version = message.value_at("MSH-12")
        if version and not re.fullmatch(r"\d+(?:\.\d+){1,2}", version):
            issues.append(ValidationIssue("warning", "MSH-12", f"Unrecognized version format: {version}", "Use a version such as 2.3, 2.5.1, or 2.8."))

        for obx in message.segments_named("OBX"):
            value_type = obx.value(2).upper()
            value = obx.value(5)
            path = f"OBX[{obx.occurrence}]-5"
            if value_type == "NM" and value and not _NUMERIC_RE.fullmatch(value):
                issues.append(ValidationIssue("error", path, "OBX-5 is not numeric while OBX-2 is NM.", "Provide a numeric value or change OBX-2 to the correct datatype."))
            if not value_type:
                issues.append(ValidationIssue("warning", f"OBX[{obx.occurrence}]-2", "Observation value type is empty.", "Populate OBX-2 before interpreting OBX-5."))
            if not obx.value(3):
                issues.append(ValidationIssue("error", f"OBX[{obx.occurrence}]-3", "Observation identifier is empty.", "Populate the observation code and description."))

        return issues

    @staticmethod
    def validate_collection(messages: Iterable[HL7Message]) -> dict[str, list[ValidationIssue]]:
        message_list = list(messages)
        result = {message.id: HL7Validator.validate(message) for message in message_list}
        controls: dict[str, list[HL7Message]] = {}
        for message in message_list:
            if message.control_id:
                controls.setdefault(message.control_id, []).append(message)
        for control, duplicates in controls.items():
            if len(duplicates) > 1:
                for message in duplicates:
                    result[message.id].append(
                        ValidationIssue("warning", "MSH-10", f"Duplicate message control ID: {control}", "Assign a unique control ID within the interface stream.")
                    )
        return result

    @staticmethod
    def _valid_timestamp(value: str) -> bool:
        if not value:
            return True
        return bool(re.fullmatch(r"\d{4}(?:\d{2}(?:\d{2}(?:\d{2}(?:\d{2}(?:\d{2}(?:\.\d{1,4})?)?)?)?)?)?(?:[+-]\d{4})?", value))
