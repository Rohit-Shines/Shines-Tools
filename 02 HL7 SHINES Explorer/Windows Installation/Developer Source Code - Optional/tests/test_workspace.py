import unittest

from hl7_shines.parser import HL7Parser
from hl7_shines.samples import featured_samples
from hl7_shines.workspace import Workspace


class WorkspaceTests(unittest.TestCase):
    def test_workspace_preserves_selection_and_search_text(self):
        messages = [HL7Parser.parse_message(sample.raw) for sample in featured_samples()[:2]]
        workspace = Workspace("Starter", messages=messages, selected_index=1)
        self.assertEqual(workspace.selected_message.control_id, "MSG000002")
        self.assertIn("msg000002", workspace.searchable_text())

    def test_clone_gets_independent_identity(self):
        workspace = Workspace("A")
        clone = workspace.clone()
        self.assertNotEqual(workspace.id, clone.id)
        self.assertEqual(clone.title, "A Copy")


if __name__ == "__main__":
    unittest.main()
