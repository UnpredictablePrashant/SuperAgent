import unittest

from scripts import verify


class VerifyScriptTests(unittest.TestCase):
    def test_resolve_phases_accepts_release_non_socket(self):
        phases = verify._resolve_phases(["release-non-socket"])
        self.assertEqual(phases, ["release-non-socket"])


if __name__ == "__main__":
    unittest.main()
