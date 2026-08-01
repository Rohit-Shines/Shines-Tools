import unittest

from hl7_shines.analytics import HL7Analytics
from hl7_shines.parser import HL7Parser
from hl7_shines.samples import featured_samples
from hl7_shines.validator import HL7Validator


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.messages = [HL7Parser.parse_message(sample.raw) for sample in featured_samples()[:3]]

    def test_field_query_search(self):
        self.assertTrue(HL7Analytics.matches(self.messages[0], "PID-3.1:MRN840271"))
        self.assertFalse(HL7Analytics.matches(self.messages[2], "MSH-9.1:ORU"))
        self.assertTrue(HL7Analytics.matches(self.messages[1], "hemoglobin"))

    def test_statistics_count_coverage_and_values(self):
        stats = HL7Analytics.statistics(self.messages)
        message_type = next(stat for stat in stats if stat.path == "MSH-9")
        self.assertEqual(message_type.present_count, 3)
        self.assertEqual(message_type.message_count, 3)
        self.assertEqual(len(message_type.unique_values), 3)
        self.assertEqual(message_type.fill_rate, 1)

    def test_diff_identifies_changed_fields(self):
        left = self.messages[0]
        right = HL7Parser.parse_message(left.raw.replace("SANTOS^RONALDO", "SANTOS^JORDAN"))
        diff = HL7Analytics.diff(left, right)
        self.assertTrue(any(entry.path == "PID[1]-5" and entry.kind == "changed" for entry in diff))
        self.assertTrue(any(entry.path == "MSH[1]-10" and entry.kind == "unchanged" for entry in diff))

    def test_validator_finds_bad_numeric_observation(self):
        raw = "MSH|^~\\&|LAB|HOSP|EHR|HOSP|20260729120000||ORU^R01|CTRL1|P|2.5.1\rOBX|1|NM|123^TEST||NOT_A_NUMBER||||||F"
        message = HL7Parser.parse_message(raw)
        issues = HL7Validator.validate(message)
        self.assertTrue(any(issue.path == "OBX[1]-5" and issue.severity == "error" for issue in issues))

    def test_collection_validator_finds_duplicate_control_ids(self):
        raw = featured_samples()[0].raw
        messages = HL7Parser.parse_stream(raw + "\r" + raw)
        issues = HL7Validator.validate_collection(messages)
        self.assertTrue(all(any(issue.path == "MSH-10" for issue in issues[message.id]) for message in messages))


if __name__ == "__main__":
    unittest.main()
