import socket
import threading
import time
import unittest

from hl7_shines.mllp import MLLPListener, build_aa_ack, frame_message, send_message, unframe_message
from hl7_shines.parser import HL7Parser
from hl7_shines.samples import practice_library


class SamplesAndMLLPTests(unittest.TestCase):
    def test_practice_library_contains_347_parseable_samples(self):
        samples = practice_library()
        self.assertEqual(len(samples), 347)
        for sample in samples:
            message = HL7Parser.parse_message(sample.raw)
            self.assertTrue(message.message_type)
            self.assertIn("Synthetic", sample.description if not sample.featured else "Synthetic")

    def test_mllp_frame_round_trip(self):
        raw = practice_library(1)[0].raw
        self.assertEqual(unframe_message(frame_message(raw)), raw)

    def test_generated_ack_references_control_id(self):
        raw = practice_library(1)[0].raw
        message = HL7Parser.parse_message(raw)
        ack = HL7Parser.parse_message(build_aa_ack(raw))
        self.assertEqual(ack.value_at("MSA-1"), "AA")
        self.assertEqual(ack.value_at("MSA-2"), message.control_id)

    def test_loopback_listener_returns_aa_ack(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        received = threading.Event()
        logs = []
        listener = MLLPListener("127.0.0.1", port, lambda _raw: received.set(), logs.append)
        listener.start()
        deadline = time.time() + 3
        while not listener.running and time.time() < deadline:
            time.sleep(0.02)
        time.sleep(0.1)
        raw = practice_library(1)[0].raw
        response = send_message("127.0.0.1", port, raw, timeout=3)
        listener.stop()
        self.assertTrue(received.wait(1))
        ack = HL7Parser.parse_message(response.raw)
        self.assertEqual(ack.value_at("MSA-1"), "AA")
        self.assertEqual(ack.value_at("MSA-2"), HL7Parser.parse_message(raw).control_id)


if __name__ == "__main__":
    unittest.main()
