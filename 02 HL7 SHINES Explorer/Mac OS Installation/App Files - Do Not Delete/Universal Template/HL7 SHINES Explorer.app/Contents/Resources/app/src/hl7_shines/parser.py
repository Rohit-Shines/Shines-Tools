from __future__ import annotations

import re

from .models import Delimiters, HL7Message, HL7Segment


class HL7ParseError(ValueError):
    pass


class HL7Parser:
    @staticmethod
    def parse_message(raw: str) -> HL7Message:
        cleaned = HL7Parser._clean_input(raw)
        lines = [line for line in re.split(r"\r\n|\n|\r", cleaned) if line.strip()]
        if not lines or not lines[0].startswith("MSH"):
            raise HL7ParseError("HL7 message must begin with an MSH segment.")

        msh = lines[0]
        if len(msh) < 8:
            raise HL7ParseError("MSH segment is too short to declare delimiters.")
        field = msh[3]
        encoding = msh[4:8]
        if len(encoding) < 4:
            raise HL7ParseError("MSH-2 must declare component, repetition, escape, and subcomponent delimiters.")
        delimiters = Delimiters(field, encoding[0], encoding[1], encoding[2], encoding[3])

        counts: dict[str, int] = {}
        segments: list[HL7Segment] = []
        for line in lines:
            if len(line) < 3:
                raise HL7ParseError(f"Invalid segment line: {line!r}")
            name = line[:3].upper()
            if not re.fullmatch(r"[A-Z0-9]{3}", name):
                raise HL7ParseError(f"Invalid segment name: {name!r}")
            if len(line) == 3:
                fields: list[str] = []
            elif line[3] != field:
                raise HL7ParseError(f"Segment {name} does not use the MSH field separator {field!r}.")
            else:
                fields = line[4:].split(field)
            counts[name] = counts.get(name, 0) + 1
            segments.append(HL7Segment(name=name, fields=fields, occurrence=counts[name], raw=line))

        normalized = "\r".join(segment.to_er7(delimiters) for segment in segments)
        return HL7Message(raw=normalized, delimiters=delimiters, segments=segments)

    @staticmethod
    def parse_stream(raw: str) -> list[HL7Message]:
        cleaned = HL7Parser._clean_input(raw)
        if not cleaned.strip():
            raise HL7ParseError("No HL7 content was provided.")

        # Normalize line endings and split whenever a new MSH starts at a segment boundary.
        normalized = re.sub(r"\r\n|\n", "\r", cleaned)
        normalized = re.sub(r"\r+", "\r", normalized).strip("\r\x00 \t")
        starts = [match.start() for match in re.finditer(r"(?:(?<=\r)|\A)MSH.", normalized)]
        if not starts:
            raise HL7ParseError("No MSH segment was found.")

        messages: list[HL7Message] = []
        for index, start in enumerate(starts):
            end = starts[index + 1] if index + 1 < len(starts) else len(normalized)
            chunk = normalized[start:end].strip("\r")
            messages.append(HL7Parser.parse_message(chunk))
        return messages

    @staticmethod
    def _clean_input(raw: str) -> str:
        if raw is None:
            return ""
        text = str(raw).replace("\ufeff", "")
        # MLLP framing: VT (0x0B) before message and FS (0x1C) followed by CR.
        text = text.replace("\x0b", "").replace("\x1c", "")
        return text.strip("\x00 \t\r\n")
