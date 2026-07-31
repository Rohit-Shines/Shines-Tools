from __future__ import annotations

from collections import Counter

from .models import HL7Message
from .validator import HL7Validator


INTENTS = {
    "ADT": "patient administration or encounter movement",
    "ORU": "unsolicited clinical observation results",
    "ORM": "a general clinical order",
    "OML": "a laboratory order",
    "SIU": "scheduling information",
    "RDE": "a pharmacy encoded order",
    "RAS": "pharmacy or treatment administration",
    "DFT": "financial transaction detail",
    "ACK": "an application acknowledgement",
    "MDM": "medical document management",
    "VXU": "an immunization update",
    "QBP": "a query request",
    "RSP": "a query response",
}


def message_summary(message: HL7Message) -> str:
    code = message.value_at("MSH-9.1") or "Unknown"
    trigger = message.value_at("MSH-9.2") or "unspecified"
    intent = INTENTS.get(code, "an HL7 workflow")
    issues = HL7Validator.validate(message)
    counts = Counter(issue.severity for issue in issues)
    segments = ", ".join(segment.name for segment in message.segments)
    lines = [
        f"This {message.message_type} message represents {intent} with trigger event {trigger}.",
        f"It was sent from {message.value_at('MSH-3') or 'an unspecified application'} / {message.value_at('MSH-4') or 'facility not supplied'} to {message.value_at('MSH-5') or 'an unspecified receiver'} / {message.value_at('MSH-6') or 'facility not supplied'}.",
        f"The declared HL7 version is {message.value_at('MSH-12') or 'not present'}, and the message control ID is {message.control_id or 'not present'}.",
        f"Patient context: {message.patient_name}; MRN {message.mrn}; visit {message.visit}; location {message.location}.",
        f"The message contains {len(message.segments)} segments in this order: {segments}.",
        f"Validation found {counts.get('error', 0)} error(s), {counts.get('warning', 0)} warning(s), and {counts.get('info', 0)} informational note(s).",
    ]
    if message.segments_named("OBX"):
        observations = []
        for obx in message.segments_named("OBX")[:5]:
            label = obx.value(3).split(message.delimiters.component)
            text = label[1] if len(label) > 1 else label[0]
            observations.append(f"{text or 'Unnamed observation'} = {obx.value(5) or 'empty'} {obx.value(6).split(message.delimiters.component)[0]}".strip())
        lines.append("Observation highlights: " + "; ".join(observations) + ".")
    lines.append("All analysis is rule-based and runs locally. Confirm meaning against the applicable implementation guide and trading-partner specification.")
    return "\n\n".join(lines)


def comparison_summary(left: HL7Message, right: HL7Message, changes: list) -> str:
    meaningful = [entry for entry in changes if entry.kind != "unchanged"]
    counts = Counter(entry.kind for entry in meaningful)
    lines = [
        f"Compared {left.message_type} ({left.control_id or 'no control ID'}) with {right.message_type} ({right.control_id or 'no control ID'}).",
        f"Detected {counts.get('changed', 0)} changed, {counts.get('added', 0)} added, and {counts.get('removed', 0)} removed fields.",
    ]
    for entry in meaningful[:10]:
        lines.append(f"• {entry.path}: {entry.kind}; left={entry.left or '<empty>'}; right={entry.right or '<empty>'}")
    if len(meaningful) > 10:
        lines.append(f"• {len(meaningful) - 10} additional differences are available in Compare.")
    return "\n".join(lines)
