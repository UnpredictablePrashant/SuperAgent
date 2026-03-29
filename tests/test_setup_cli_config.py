import io
import json
import os
import unittest
from contextlib import redirect_stdout

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

from kendr.cli import main
from tasks.setup_config_store import get_setup_component_snapshot, save_component_values


class SetupCliConfigTests(unittest.TestCase):
    def test_set_show_unset_component_key(self):
        component = "openai"
        key = "OPENAI_MODEL"
        before = get_setup_component_snapshot(component).get("raw_values", {}).get(key, "")

        set_buf = io.StringIO()
        with redirect_stdout(set_buf):
            exit_code = main(["setup", "set", component, key, "gpt-setup-test"])
        self.assertEqual(exit_code, 0)

        show_buf = io.StringIO()
        with redirect_stdout(show_buf):
            exit_code = main(["setup", "show", component, "--json"])
        self.assertEqual(exit_code, 0)
        payload = json.loads(show_buf.getvalue())
        self.assertEqual(payload["raw_values"].get(key), "gpt-setup-test")

        export_buf = io.StringIO()
        with redirect_stdout(export_buf):
            exit_code = main(["setup", "export-env", "--include-secrets"])
        self.assertEqual(exit_code, 0)
        self.assertIn("OPENAI_MODEL=gpt-setup-test", export_buf.getvalue())

        unset_buf = io.StringIO()
        with redirect_stdout(unset_buf):
            exit_code = main(["setup", "unset", component, key])
        self.assertEqual(exit_code, 0)

        if before:
            save_component_values(component, {key: before})

    def test_enable_disable_component(self):
        component = "serpapi"
        before_enabled = get_setup_component_snapshot(component).get("enabled", True)

        disable_buf = io.StringIO()
        with redirect_stdout(disable_buf):
            exit_code = main(["setup", "disable", component])
        self.assertEqual(exit_code, 0)

        show_buf = io.StringIO()
        with redirect_stdout(show_buf):
            exit_code = main(["setup", "show", component, "--json"])
        self.assertEqual(exit_code, 0)
        payload = json.loads(show_buf.getvalue())
        self.assertFalse(payload.get("enabled", True))

        target_action = "enable" if before_enabled else "disable"
        with redirect_stdout(io.StringIO()):
            exit_code = main(["setup", target_action, component])
        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
