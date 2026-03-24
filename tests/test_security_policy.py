import unittest

from tasks.security_policy import (
    apply_security_profile_defaults,
    is_security_assessment_query,
    require_security_authorization,
)


class SecurityPolicyTests(unittest.TestCase):
    def test_security_query_detection(self):
        self.assertTrue(is_security_assessment_query("run a vulnerability scan on my app"))
        self.assertFalse(is_security_assessment_query("summarize this company report"))

    def test_profile_defaults_apply(self):
        state = {"security_scan_profile": "extensive"}
        apply_security_profile_defaults(state)
        self.assertEqual(state["security_scan_profile"], "extensive")
        self.assertGreaterEqual(int(state["scanner_top_ports"]), 5000)
        self.assertGreaterEqual(int(state["zap_max_minutes"]), 35)

    def test_authorization_is_enforced(self):
        with self.assertRaises(PermissionError):
            require_security_authorization({}, "https://example.com")

        state = {
            "security_authorized": True,
            "security_authorization_note": "SEC-123 approval",
        }
        require_security_authorization(state, "https://example.com")


if __name__ == "__main__":
    unittest.main()
