import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class CliEntrypointSmokeTests(unittest.TestCase):
    def test_module_entrypoint_help(self):
        env = os.environ.copy()
        env.setdefault("OPENAI_API_KEY", "test-openai-key")
        env["PYTHONPATH"] = str(ROOT) if not env.get("PYTHONPATH") else f"{ROOT}{os.pathsep}{env['PYTHONPATH']}"

        result = subprocess.run(
            [sys.executable, "-m", "superagent.cli", "--help"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("usage: superagent", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()
