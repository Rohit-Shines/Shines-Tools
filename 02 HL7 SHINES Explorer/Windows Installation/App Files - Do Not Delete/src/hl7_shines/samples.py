from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class SampleMessage:
    title: str
    category: str
    message_type: str
    description: str
    raw: str
    featured: bool = False


_PATIENTS = [
    ("SANTOS", "RONALDO", "MRN840271", "VIS770021", "19840418", "M"),
    ("MERCER", "LIONEL", "MRN558420", "VIS770022", "19870624", "M"),
    ("PATEL", "SACHIN", "MRN771902", "VIS770023", "19730424", "M"),
    ("KIM", "JORDAN", "MRN992104", "VIS770024", "19920109", "F"),
]


def _ts(offset_minutes: int = 0) -> str:
    return (datetime.now().astimezone() + timedelta(minutes=offset_minutes)).strftime("%Y%m%d%H%M%S%z")


def featured_samples() -> list[SampleMessage]:
    adt = (
        f"MSH|^~\\&|EPIC_TRAINING|MAPLE_GRAND_HOSPITAL|HL7_SHINES|TRAINING_LAB|{_ts()}||ADT^A01^ADT_A01|MSG000001|P|2.5.1|||AL|AL|CAN|UNICODE UTF-8|EN^English^ISO639|ISO 2022-1994|HL7_SHINES_TRAINING_PROFILE\r"
        f"EVN|A01|{_ts()}|||1001^ADAMS^ALEX^^^^^TRAINING|{_ts()}\r"
        "PID|1||MRN840271^^^MAPLE_GRAND_HOSPITAL^MR||SANTOS^RONALDO^^^^^L||19840418|M||2028-9^Asian^HL70005|88 HARBOUR LIGHTS AVENUE^^TORONTO^ON^M5J2N8^CAN^H||4165550101^PRN^PH^^1^416^5550101|4165550110^WPN^PH|EN^English^ISO639|M^Married^HL70002||ACC840271^^^MAPLE_GRAND_HOSPITAL^AN||||||||||||N\r"
        "NK1|1|SANTOS^JORDAN^^^^^L|SPO^Spouse^HL70063|88 HARBOUR LIGHTS AVENUE^^TORONTO^ON^M5J2N8^CAN|4165550101^PRN^PH|4165550110^WPN^PH|EC^Emergency Contact^HL70131\r"
        f"PV1|1|I|7E^712^1^MAPLE_GRAND_HOSPITAL^^N^O^N|R|||1001^ADAMS^ALEX^^^^^TRAINING|1002^BROWN^SAM^^^^^TRAINING||MED|||||||||VIS770021^^^MAPLE_GRAND_HOSPITAL^VN|||||||||||||||||||||||||{_ts(-45)}\r"
        "PV2|||INTAKE^Initial assessment^L|||Ambulatory^L|J18.9^SYNTHETIC RESPIRATORY CONDITION^ICD10||||||||||||||||||||||||||||||||||||||||||||\r"
        "AL1|1|DA|7980^PENICILLIN^RXNORM|MO^Moderate^HL70128|SYNTHETIC RASH HISTORY|20240101\r"
        "DG1|1|ICD10|J18.9^SYNTHETIC RESPIRATORY CONDITION^ICD10|Training diagnosis only|20260729103000|A\r"
        "IN1|1|TRAINING_PLAN^Training Insurance Plan^L|POL840271^TRAINING_INSURANCE^L|DEMONSTRATION INSURANCE||||GRP840271|||||||20260101|SANTOS^RONALDO^^^^^L|SEL^Self^HL70063\r"
        "GT1|1|GT-840271|SANTOS^RONALDO^^^^^L|88 HARBOUR LIGHTS AVENUE^^TORONTO^ON^M5J2N8^CAN|4165550101^PRN^PH\r"
        "NTE|1|L|All identities, facilities, diagnoses, and coverage details are synthetic training data.|TRAINING"
    )
    oru = (
        f"MSH|^~\\&|LAB_TRAINING|MAPLE_GRAND_HOSPITAL|HL7_SHINES|TRAINING_EHR|{_ts()}||ORU^R01^ORU_R01|MSG000002|P|2.5.1|||AL|AL|CAN|UNICODE UTF-8\r"
        "PID|1||MRN558420^^^MAPLE_GRAND_HOSPITAL^MR||MERCER^LIONEL^^^^^L||19870624|M|||22 LAKEVIEW ROAD^^TORONTO^ON^M4W1A1^CAN\r"
        "PV1|1|O|LAB^01^CHAIR2^MAPLE_GRAND_HOSPITAL||||1003^LEE^MORGAN^^^^^TRAINING|||||||||||VIS770022^^^MAPLE_GRAND_HOSPITAL^VN\r"
        "ORC|RE|ORD1002|FIL1002||||||20260729113000|||1003^LEE^MORGAN^^^^^TRAINING\r"
        "OBR|1|ORD1002|FIL1002|718-7^HEMOGLOBIN^LN|||20260729110000||||||Routine synthetic result|||1003^LEE^MORGAN^^^^^TRAINING||||||LAB|F\r"
        "OBX|1|NM|718-7^HEMOGLOBIN^LN||145|g/L^grams per litre^UCUM|130-170|N|||F|||20260729110000||2001^TECH^TAYLOR^^^^^TRAINING\r"
        "OBX|2|NM|6690-2^LEUKOCYTES^LN||6.8|10*9/L^10^9 per litre^UCUM|4.0-11.0|N|||F|||20260729110000||2001^TECH^TAYLOR^^^^^TRAINING\r"
        "NTE|1|L|Synthetic laboratory values for software training only.|TRAINING"
    )
    siu = (
        f"MSH|^~\\&|SCHED_TRAINING|MAPLE_GRAND_HOSPITAL|HL7_SHINES|TRAINING_CLINIC|{_ts()}||SIU^S12^SIU_S12|MSG000003|P|2.5.1|||AL|AL|CAN|UNICODE UTF-8\r"
        "SCH|APT770023|FILL770023||||FOLLOWUP^Follow-up appointment^L|CARDIOLOGY^Cardiology consultation^L|30|min^UCUM|^^^20260805140000-0400^20260805143000-0400||||||||1004^CLARK^JAMIE^^^^^TRAINING||||||||BOOKED\r"
        "PID|1||MRN771902^^^MAPLE_GRAND_HOSPITAL^MR||PATEL^SACHIN^^^^^L||19730424|M|||17 MAPLE WALK^^BRAMPTON^ON^L6Y1N1^CAN\r"
        "PV1|1|O|CARD^201^1^MAPLE_GRAND_HOSPITAL||||1004^CLARK^JAMIE^^^^^TRAINING|||||||||||VIS770023^^^MAPLE_GRAND_HOSPITAL^VN\r"
        "RGS|1\rAIS|1||CARDIOLOGY^Cardiology consultation^L|20260805140000-0400|30|min^UCUM\r"
        "AIP|1||1004^CLARK^JAMIE^^^^^TRAINING|CONSULTANT^Consultant^L|20260805140000-0400|30|min^UCUM\r"
        "AIL|1||CARD^201^1^MAPLE_GRAND_HOSPITAL|CLINIC^Clinic^L|20260805140000-0400|30|min^UCUM\r"
        "NTE|1|L|Synthetic appointment for software training only.|TRAINING"
    )
    ack = (
        f"MSH|^~\\&|HL7_SHINES|TRAINING_EHR|EPIC_TRAINING|MAPLE_GRAND_HOSPITAL|{_ts()}||ACK^A01^ACK|ACK000004|P|2.5.1\r"
        "MSA|AA|MSG000001|Message accepted by HL7 Shines training listener\r"
        "NTE|1|L|Synthetic acknowledgement for software training only.|TRAINING"
    )
    return [
        SampleMessage("Featured ADT Admission", "Patient Administration", "ADT^A01", "Rich synthetic admission message", adt, True),
        SampleMessage("Featured ORU Result", "Orders and Results", "ORU^R01", "Synthetic laboratory result", oru, True),
        SampleMessage("Featured SIU Appointment", "Scheduling", "SIU^S12", "Synthetic scheduling message", siu, True),
        SampleMessage("Featured ACK", "Acknowledgements", "ACK^A01", "Positive application acknowledgement", ack, True),
    ]


_CATALOG = [
    ("Patient Administration", "ADT", ["A01", "A02", "A03", "A04", "A05", "A06", "A07", "A08", "A09", "A10", "A11", "A12", "A13", "A18", "A28", "A31", "A40"]),
    ("Orders and Results", "ORM", ["O01"]),
    ("Orders and Results", "OML", ["O21", "O33"]),
    ("Orders and Results", "ORU", ["R01", "R30"]),
    ("Scheduling", "SIU", ["S12", "S13", "S14", "S15", "S16", "S17", "S18", "S26"]),
    ("Pharmacy", "RDE", ["O11", "O25"]),
    ("Pharmacy", "RAS", ["O17"]),
    ("Immunization", "VXU", ["V04"]),
    ("Financial", "DFT", ["P03", "P11"]),
    ("Master File", "MFN", ["M02", "M04", "M05", "M06", "M08", "M10"]),
    ("Queries", "QBP", ["Q11", "Q21", "Q22", "Q23"]),
    ("Queries", "RSP", ["K11", "K21", "K22", "K23"]),
    ("Documents", "MDM", ["T01", "T02", "T05", "T06", "T08", "T09", "T10", "T11"]),
    ("Acknowledgements", "ACK", ["A01", "R01", "S12"]),
]


def _generic_message(category: str, code: str, trigger: str, index: int) -> str:
    family, given, mrn, visit, dob, sex = _PATIENTS[index % len(_PATIENTS)]
    control = f"TRN{index + 1:06d}"
    structure = f"{code}_{trigger}"
    segments = [
        f"MSH|^~\\&|HL7_SHINES_TRAINING|MAPLE_GRAND_HOSPITAL|PRACTICE_RECEIVER|TRAINING_ONLY|{_ts(index)}||{code}^{trigger}^{structure}|{control}|T|2.5.1|||AL|AL|CAN|UNICODE UTF-8|EN^English^ISO639|ISO 2022-1994|HL7_SHINES_PRACTICE_PROFILE",
    ]
    if code == "ACK":
        segments += [f"MSA|AA|SOURCE{index:06d}|Synthetic acknowledgement {index + 1}"]
    elif code == "SIU":
        segments += [
            f"SCH|APT{index:06d}|FILL{index:06d}||||TRAINING^Training appointment^L|FOLLOWUP^Follow-up^L|30|min^UCUM|^^^{_ts(index + 1440)}^{_ts(index + 1470)}||||||||1004^CLARK^JAMIE^^^^^TRAINING||||||||BOOKED",
            f"PID|1||{mrn}^^^MAPLE_GRAND_HOSPITAL^MR||{family}^{given}^^^^^L||{dob}|{sex}",
            "RGS|1",
            f"AIS|1||TRAINING_SERVICE^Synthetic service^L|{_ts(index + 1440)}|30|min^UCUM",
        ]
    elif code in {"ORU", "ORM", "OML"}:
        segments += [
            f"PID|1||{mrn}^^^MAPLE_GRAND_HOSPITAL^MR||{family}^{given}^^^^^L||{dob}|{sex}",
            f"PV1|1|O|LAB^01^1^MAPLE_GRAND_HOSPITAL||||1003^LEE^MORGAN^^^^^TRAINING|||||||||||{visit}^^^MAPLE_GRAND_HOSPITAL^VN",
            f"ORC|NW|ORD{index:06d}|FIL{index:06d}||||||{_ts(index)}|||1003^LEE^MORGAN^^^^^TRAINING",
            f"OBR|1|ORD{index:06d}|FIL{index:06d}|718-7^HEMOGLOBIN^LN|||{_ts(index)}||||||Synthetic order/result|||1003^LEE^MORGAN^^^^^TRAINING||||||LAB|F",
        ]
        if code == "ORU":
            segments.append(f"OBX|1|NM|718-7^HEMOGLOBIN^LN||{130 + (index % 35)}|g/L^grams per litre^UCUM|130-170|N|||F|||{_ts(index)}")
    elif code in {"RDE", "RAS", "VXU"}:
        segments += [
            f"PID|1||{mrn}^^^MAPLE_GRAND_HOSPITAL^MR||{family}^{given}^^^^^L||{dob}|{sex}",
            f"PV1|1|O|PHARM^01^1^MAPLE_GRAND_HOSPITAL||||1003^LEE^MORGAN^^^^^TRAINING|||||||||||{visit}^^^MAPLE_GRAND_HOSPITAL^VN",
            f"ORC|NW|RX{index:06d}|RXF{index:06d}||||||{_ts(index)}|||1003^LEE^MORGAN^^^^^TRAINING",
            f"RXA|0|1|{_ts(index)}|{_ts(index)}|TRAINING_DRUG^Synthetic medication^L|1|dose^UCUM||||||||A",
        ]
    elif code == "DFT":
        segments += [
            f"PID|1||{mrn}^^^MAPLE_GRAND_HOSPITAL^MR||{family}^{given}^^^^^L||{dob}|{sex}",
            f"PV1|1|O|BILL^01^1^MAPLE_GRAND_HOSPITAL||||1003^LEE^MORGAN^^^^^TRAINING|||||||||||{visit}^^^MAPLE_GRAND_HOSPITAL^VN",
            f"FT1|1|TX{index:06d}||{_ts(index)}|{_ts(index)}|CG|TRAINING_FEE^Synthetic charge^L|1|100.00|CAD",
        ]
    else:
        segments += [
            f"EVN|{trigger}|{_ts(index)}",
            f"PID|1||{mrn}^^^MAPLE_GRAND_HOSPITAL^MR||{family}^{given}^^^^^L||{dob}|{sex}||2028-9^Asian^HL70005|{index + 1} TRAINING ROAD^^TORONTO^ON^M5J2N8^CAN",
            f"PV1|1|I|7E^{700 + (index % 30)}^{1 + (index % 2)}^MAPLE_GRAND_HOSPITAL||||1001^ADAMS^ALEX^^^^^TRAINING|||||||||||{visit}^^^MAPLE_GRAND_HOSPITAL^VN|||||||||||||||||||||||||{_ts(index - 60)}",
        ]
    segments.append("NTE|1|L|Synthetic training message. Not for clinical use.|TRAINING")
    return "\r".join(segments)


def practice_library(total: int = 347) -> list[SampleMessage]:
    samples = featured_samples()
    combinations = [(category, code, trigger) for category, code, triggers in _CATALOG for trigger in triggers]
    index = 0
    while len(samples) < total:
        category, code, trigger = combinations[index % len(combinations)]
        raw = _generic_message(category, code, trigger, index)
        samples.append(
            SampleMessage(
                title=f"{code}^{trigger} Practice {index + 1}",
                category=category,
                message_type=f"{code}^{trigger}",
                description="Synthetic, training-only HL7 v2.5.1 example",
                raw=raw,
                featured=False,
            )
        )
        index += 1
    return samples[:total]
