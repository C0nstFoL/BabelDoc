"""Regression checks for stale native deployment environments."""

from importlib.metadata import PackageNotFoundError
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from babeldoc_app import runtime, server


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        requirements = Path(tmp.name) / "requirements.txt"
        requirements.write_text(
            "# Deployment pins\n-c constraints.txt\ngradio==6.30.0\n"
            "bitstring==4.3.1 # Required API\n",
            encoding="utf-8",
        )
        patcher = patch.object(runtime, "REQUIREMENTS_FILE", requirements)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_pinned_environment_passes(self):
        versions = {"gradio": "6.30.0", "bitstring": "4.3.1"}
        with patch.object(runtime, "version", side_effect=versions.__getitem__):
            runtime.require_runtime()

    def test_gradio_444_reports_installed_required_and_repair_command(self):
        versions = {"gradio": "4.44.1", "bitstring": "4.3.1"}
        with patch.object(runtime, "version", side_effect=versions.__getitem__):
            with self.assertRaises(SystemExit) as error:
                runtime.require_runtime()
        message = str(error.exception)
        self.assertIn("gradio: installed 4.44.1, required 6.30.0", message)
        self.assertIn("-m pip install --upgrade -r", message)
        self.assertIn("start.bat restart", message)

    def test_missing_dependency_has_actionable_error(self):
        with patch.object(runtime, "version", side_effect=PackageNotFoundError):
            with self.assertRaisesRegex(SystemExit, "gradio: installed not installed"):
                runtime.require_runtime()

    def test_native_and_asgi_startup_reject_old_gradio_before_ui_import(self):
        versions = {"gradio": "4.44.1", "bitstring": "4.3.1"}
        with (
            patch.object(runtime, "version", side_effect=versions.__getitem__),
            patch.object(server.settings, "AUTH_ENABLED", False),
        ):
            for start in (server.main, server.create_app):
                with self.subTest(start=start.__name__):
                    with self.assertRaisesRegex(SystemExit, "gradio: installed 4.44.1"):
                        start()


if __name__ == "__main__":
    unittest.main()
