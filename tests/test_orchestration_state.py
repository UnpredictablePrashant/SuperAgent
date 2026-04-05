import unittest

from kendr.orchestration.state import state_awaiting_user_input


class OrchestrationStateTests(unittest.TestCase):
    def test_state_awaiting_user_input_detects_approval_scope_without_pending_kind(self):
        state = {
            "approval_pending_scope": "deep_research_confirmation",
            "pending_user_input_kind": "",
        }
        self.assertTrue(state_awaiting_user_input(state))

    def test_state_awaiting_user_input_detects_approval_request_payload(self):
        state = {
            "approval_request": {"scope": "long_document_plan", "summary": "Review and approve section plan."},
            "pending_user_input_kind": "",
        }
        self.assertTrue(state_awaiting_user_input(state))

    def test_state_awaiting_user_input_ignores_empty_normalized_approval_request(self):
        state = {
            "approval_request": {
                "scope": "",
                "title": "",
                "summary": "",
                "sections": [],
                "actions": {"accept_label": "Accept", "reject_label": "Reject", "suggest_label": "Suggestion"},
                "help_text": "",
                "artifact_paths": [],
                "metadata": {},
            },
            "pending_user_input_kind": "",
            "approval_pending_scope": "",
        }
        self.assertFalse(state_awaiting_user_input(state))


if __name__ == "__main__":
    unittest.main()
