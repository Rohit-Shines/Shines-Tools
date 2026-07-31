import unittest

from hl7_shines.parser import HL7ParseError, HL7Parser
from hl7_shines.samples import featured_samples


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.samples = featured_samples()

    def test_parses_standard_message_and_msh_field_numbers(self):
        message = HL7Parser.parse_message(self.samples[0].raw)
        self.assertEqual(message.message_type, "ADT^A01")
        self.assertEqual(message.value_at("MSH-9.1"), "ADT")
        self.assertEqual(message.value_at("MSH-9.2"), "A01")
        self.assertEqual(message.value_at("MSH-10"), "MSG000001")
        self.assertEqual(message.value_at("PID-5.1"), "SANTOS")
        self.assertEqual(message.value_at("PID-5.2"), "RONALDO")
        self.assertEqual(message.patient_name, "RONALDO SANTOS")

    def test_parses_stream_with_mllp_frames_and_mixed_line_endings(self):
        first = self.samples[0].raw.replace("\r", "\n")
        second = self.samples[1].raw
        framed = f"\x0b{first}\x1c\r\x0b{second}\x1c\r"
        messages = HL7Parser.parse_stream(framed)
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].value_at("MSH-10"), "MSG000001")
        self.assertEqual(messages[1].value_at("MSH-10"), "MSG000002")

    def test_honors_custom_delimiters(self):
        raw = "MSH*$%!?*SEND*FAC*RECV*FAC*20260729120000**ADT$A01$ADT_A01*42*P*2.5.1\rPID*1**123%%%MR**DOE$JANE"
        message = HL7Parser.parse_message(raw)
        self.assertEqual(message.delimiters.field, "*")
        self.assertEqual(message.delimiters.component, "$")
        self.assertEqual(message.value_at("MSH-9.2"), "A01")
        self.assertEqual(message.value_at("PID-5.2"), "JANE")

    def test_rejects_content_without_msh(self):
        with self.assertRaises(HL7ParseError):
            HL7Parser.parse_message("PID|1||123")
        with self.assertRaises(HL7ParseError):
            HL7Parser.parse_stream("")

    def test_parses_repetitions_components_and_subcomponents(self):
        raw = "MSH|^~\\&|A|B|C|D|20260729120000||ADT^A01|1|P|2.5.1\rPID|1||123^A&ONE~456^B&TWO"
        message = HL7Parser.parse_message(raw)
        self.assertEqual(message.value_at("PID-3[2].1"), "456")
        self.assertEqual(message.value_at("PID-3[2].2.2"), "TWO")

    def test_edits_component_and_rebuilds_er7(self):
        message = HL7Parser.parse_message(self.samples[0].raw)
        message.set_value_at("PID-5.2", "JORDAN")
        self.assertEqual(message.value_at("PID-5.2"), "JORDAN")
        self.assertIn("SANTOS^JORDAN", message.raw)


if __name__ == "__main__":
    unittest.main()
