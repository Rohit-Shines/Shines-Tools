from __future__ import annotations

SEGMENT_NAMES: dict[str, str] = {
    "MSH": "Message Header", "MSA": "Message Acknowledgment", "ERR": "Error",
    "EVN": "Event Type", "PID": "Patient Identification", "PD1": "Additional Demographics",
    "NK1": "Next of Kin / Associated Parties", "PV1": "Patient Visit", "PV2": "Patient Visit - Additional",
    "AL1": "Patient Allergy", "DG1": "Diagnosis", "DRG": "Diagnosis Related Group",
    "PR1": "Procedures", "ROL": "Role", "IN1": "Insurance", "IN2": "Insurance Additional Information",
    "GT1": "Guarantor", "ACC": "Accident", "UB1": "UB82", "UB2": "UB92",
    "ORC": "Common Order", "OBR": "Observation Request", "OBX": "Observation Result",
    "NTE": "Notes and Comments", "SPM": "Specimen", "SAC": "Specimen Container Detail",
    "SCH": "Scheduling Activity Information", "AIP": "Appointment Personnel", "AIS": "Appointment Information - Service",
    "AIL": "Appointment Information - Location", "AIG": "Appointment Information - General Resource",
    "RXA": "Pharmacy/Treatment Administration", "RXE": "Pharmacy/Treatment Encoded Order",
    "RXR": "Pharmacy/Treatment Route", "RXC": "Pharmacy/Treatment Component Order",
    "FT1": "Financial Transaction", "DG1": "Diagnosis", "PRD": "Provider Data",
    "QPD": "Query Parameter Definition", "RCP": "Response Control Parameter", "DSP": "Display Data",
    "MFI": "Master File Identification", "MFE": "Master File Entry", "OM1": "General Segment",
    "TXA": "Transcription Document Header", "CON": "Consent", "IAM": "Patient Adverse Reaction Information",
}

FIELD_NAMES: dict[str, str] = {
    "MSH-1": "Field Separator", "MSH-2": "Encoding Characters", "MSH-3": "Sending Application",
    "MSH-4": "Sending Facility", "MSH-5": "Receiving Application", "MSH-6": "Receiving Facility",
    "MSH-7": "Date/Time of Message", "MSH-8": "Security", "MSH-9": "Message Type",
    "MSH-10": "Message Control ID", "MSH-11": "Processing ID", "MSH-12": "Version ID",
    "MSH-13": "Sequence Number", "MSH-14": "Continuation Pointer", "MSH-15": "Accept Acknowledgment Type",
    "MSH-16": "Application Acknowledgment Type", "MSH-17": "Country Code", "MSH-18": "Character Set",
    "MSH-19": "Principal Language of Message", "MSH-20": "Alternate Character Set Handling Scheme",
    "MSH-21": "Message Profile Identifier",
    "EVN-1": "Event Type Code", "EVN-2": "Recorded Date/Time", "EVN-3": "Date/Time Planned Event",
    "EVN-4": "Event Reason Code", "EVN-5": "Operator ID", "EVN-6": "Event Occurred",
    "PID-1": "Set ID - PID", "PID-2": "Patient ID", "PID-3": "Patient Identifier List",
    "PID-4": "Alternate Patient ID", "PID-5": "Patient Name", "PID-6": "Mother's Maiden Name",
    "PID-7": "Date/Time of Birth", "PID-8": "Administrative Sex", "PID-9": "Patient Alias",
    "PID-10": "Race", "PID-11": "Patient Address", "PID-12": "County Code", "PID-13": "Phone Number - Home",
    "PID-14": "Phone Number - Business", "PID-15": "Primary Language", "PID-16": "Marital Status",
    "PID-17": "Religion", "PID-18": "Patient Account Number", "PID-19": "SSN Number - Patient",
    "PID-20": "Driver's License Number", "PID-21": "Mother's Identifier", "PID-22": "Ethnic Group",
    "PID-23": "Birth Place", "PID-24": "Multiple Birth Indicator", "PID-25": "Birth Order",
    "PID-26": "Citizenship", "PID-27": "Veterans Military Status", "PID-28": "Nationality",
    "PID-29": "Patient Death Date and Time", "PID-30": "Patient Death Indicator",
    "PV1-1": "Set ID - PV1", "PV1-2": "Patient Class", "PV1-3": "Assigned Patient Location",
    "PV1-4": "Admission Type", "PV1-5": "Preadmit Number", "PV1-6": "Prior Patient Location",
    "PV1-7": "Attending Doctor", "PV1-8": "Referring Doctor", "PV1-9": "Consulting Doctor",
    "PV1-10": "Hospital Service", "PV1-11": "Temporary Location", "PV1-12": "Preadmit Test Indicator",
    "PV1-13": "Re-admission Indicator", "PV1-14": "Admit Source", "PV1-15": "Ambulatory Status",
    "PV1-16": "VIP Indicator", "PV1-17": "Admitting Doctor", "PV1-18": "Patient Type",
    "PV1-19": "Visit Number", "PV1-20": "Financial Class", "PV1-21": "Charge Price Indicator",
    "PV1-36": "Discharge Disposition", "PV1-44": "Admit Date/Time", "PV1-45": "Discharge Date/Time",
    "ORC-1": "Order Control", "ORC-2": "Placer Order Number", "ORC-3": "Filler Order Number",
    "ORC-5": "Order Status", "ORC-9": "Date/Time of Transaction", "ORC-12": "Ordering Provider",
    "OBR-1": "Set ID - OBR", "OBR-2": "Placer Order Number", "OBR-3": "Filler Order Number",
    "OBR-4": "Universal Service Identifier", "OBR-7": "Observation Date/Time", "OBR-13": "Relevant Clinical Information",
    "OBR-16": "Ordering Provider", "OBR-18": "Placer Field 1", "OBR-22": "Results Report/Status Change Date/Time",
    "OBR-24": "Diagnostic Service Section ID", "OBR-25": "Result Status",
    "OBX-1": "Set ID - OBX", "OBX-2": "Value Type", "OBX-3": "Observation Identifier",
    "OBX-4": "Observation Sub-ID", "OBX-5": "Observation Value", "OBX-6": "Units",
    "OBX-7": "References Range", "OBX-8": "Abnormal Flags", "OBX-11": "Observation Result Status",
    "OBX-14": "Date/Time of Observation", "OBX-16": "Responsible Observer",
    "MSA-1": "Acknowledgment Code", "MSA-2": "Message Control ID", "MSA-3": "Text Message",
    "AL1-1": "Set ID - AL1", "AL1-2": "Allergen Type Code", "AL1-3": "Allergen Code/Mnemonic/Description",
    "AL1-4": "Allergy Severity Code", "AL1-5": "Allergy Reaction Code",
    "DG1-1": "Set ID - DG1", "DG1-2": "Diagnosis Coding Method", "DG1-3": "Diagnosis Code",
    "DG1-4": "Diagnosis Description", "DG1-5": "Diagnosis Date/Time", "DG1-6": "Diagnosis Type",
    "NK1-1": "Set ID - NK1", "NK1-2": "Name", "NK1-3": "Relationship", "NK1-4": "Address",
    "NK1-5": "Phone Number", "NK1-7": "Contact Role",
    "IN1-1": "Set ID - IN1", "IN1-2": "Insurance Plan ID", "IN1-3": "Insurance Company ID",
    "IN1-4": "Insurance Company Name", "IN1-8": "Group Number", "IN1-16": "Name of Insured",
    "GT1-1": "Set ID - GT1", "GT1-2": "Guarantor Number", "GT1-3": "Guarantor Name",
    "SCH-1": "Placer Appointment ID", "SCH-2": "Filler Appointment ID", "SCH-6": "Event Reason",
    "SCH-7": "Appointment Reason", "SCH-11": "Appointment Timing Quantity", "SCH-25": "Filler Status Code",
    "NTE-1": "Set ID - NTE", "NTE-2": "Source of Comment", "NTE-3": "Comment", "NTE-4": "Comment Type",
}

COMPONENT_NAMES: dict[str, list[str]] = {
    "MSH-9": ["Message Code", "Trigger Event", "Message Structure"],
    "PID-3": ["ID Number", "Check Digit", "Check Digit Scheme", "Assigning Authority", "Identifier Type Code", "Assigning Facility"],
    "PID-5": ["Family Name", "Given Name", "Second and Further Given Names", "Suffix", "Prefix", "Degree", "Name Type Code"],
    "PID-11": ["Street Address", "Other Designation", "City", "State/Province", "Postal Code", "Country", "Address Type"],
    "PV1-3": ["Point of Care", "Room", "Bed", "Facility", "Location Status", "Person Location Type"],
    "PV1-7": ["ID Number", "Family Name", "Given Name", "Second Names", "Suffix", "Prefix", "Degree"],
    "OBR-4": ["Identifier", "Text", "Name of Coding System", "Alternate Identifier", "Alternate Text", "Alternate Coding System"],
    "OBX-3": ["Identifier", "Text", "Name of Coding System", "Alternate Identifier", "Alternate Text", "Alternate Coding System"],
    "OBX-6": ["Identifier", "Text", "Name of Coding System"],
    "AL1-3": ["Identifier", "Text", "Name of Coding System", "Alternate Identifier", "Alternate Text", "Alternate Coding System"],
    "DG1-3": ["Identifier", "Text", "Name of Coding System", "Alternate Identifier", "Alternate Text", "Alternate Coding System"],
}

REQUIRED_FIELDS = {"MSH-1", "MSH-2", "MSH-7", "MSH-9", "MSH-10", "MSH-11", "MSH-12"}

CODE_SUGGESTIONS: dict[str, list[str]] = {
    "PID-8": ["F", "M", "O", "U", "A", "N"],
    "PV1-2": ["E", "I", "O", "P", "R", "B", "C", "N", "U"],
    "MSH-11": ["P", "T", "D"],
    "MSH-15": ["AL", "ER", "NE", "SU"],
    "MSH-16": ["AL", "ER", "NE", "SU"],
    "MSA-1": ["AA", "AE", "AR", "CA", "CE", "CR"],
    "OBX-2": ["AD", "CE", "CWE", "CX", "DT", "ED", "FT", "NM", "SN", "ST", "TM", "TS", "TX"],
    "OBX-11": ["C", "D", "F", "I", "N", "O", "P", "R", "S", "U", "W", "X"],
    "AL1-4": ["MI", "MO", "SV", "U"],
}


def segment_name(name: str) -> str:
    return SEGMENT_NAMES.get(name.upper(), "Custom Z-segment" if name.upper().startswith("Z") else "Unknown segment")


def field_name(segment: str, field_number: int) -> str:
    return FIELD_NAMES.get(f"{segment.upper()}-{field_number}", f"Field {field_number}")


def component_name(segment: str, field_number: int, component_number: int) -> str:
    values = COMPONENT_NAMES.get(f"{segment.upper()}-{field_number}", [])
    if 0 < component_number <= len(values):
        return values[component_number - 1]
    return f"Component {component_number}"
