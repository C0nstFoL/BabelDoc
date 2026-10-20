"""Integration checks for module boundaries and existing application workflows."""

import copy
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")

from starlette.testclient import TestClient

from babeldoc_app import (
    engine,
    history,
    presets,
    progress,
    server,
    settings,
    state,
    tasks,
)
from babeldoc_app.ui import preset_callbacks
from babeldoc_app.ui.app import build_ui
from babeldoc_app.ui.translation_events import clear_all


class ModuleBoundaryTests(unittest.TestCase):
    def test_entry_and_execution_imports_do_not_construct_web_ui(self):
        code = """
import sys
import babeldoc_translator
from babeldoc_app import engine, server
assert 'gradio' not in sys.modules
assert 'authlib' not in sys.modules
assert not any(name.startswith('babeldoc_app.ui') for name in sys.modules)
"""
        subprocess.run([sys.executable, "-c", code], check=True, timeout=15)

    def test_data_paths_remain_in_project_root(self):
        root = Path(__file__).resolve().parent.parent
        self.assertEqual(settings.CONFIG_DIR, root)
        self.assertEqual(presets.CONFIG_FILE, root / ".babeldoc_config.json")
        self.assertEqual(history.HISTORY_FILE, root / ".babeldoc_history.json")
        self.assertEqual(history.HISTORY_DIR, root / "outputs")

    def test_real_worker_entry_reports_protocol_errors(self):
        state._reset_stop()
        try:
            with self.assertRaisesRegex(RuntimeError, "pdf_file"):
                engine._run_isolated_translation({})
            self.assertIsNone(state._running_process)
        finally:
            state._reset_stop()


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.previous_state = copy.deepcopy(state._TASK)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config_dir = patch.object(presets, "CONFIG_DIR", self.root)
        self.config_file = patch.object(
            presets, "CONFIG_FILE", self.root / "config.json"
        )
        self.history_file = patch.object(
            history, "HISTORY_FILE", self.root / "history.json"
        )
        self.history_dir = patch.object(history, "HISTORY_DIR", self.root)
        for patcher in (
            self.config_dir,
            self.config_file,
            self.history_file,
            self.history_dir,
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.restore_state)

    def restore_state(self):
        state._TASK.clear()
        state._TASK.update(self.previous_state)
        state._reset_stop()

    def test_presets_survive_save_switch_reload_and_model_edit(self):
        saved, active_id, _, update, _ = preset_callbacks.handle_save_preset(
            [], None, None, "Test model", "test-key", "http://localhost/v1", "glm-5.3"
        )
        preset_id = update["value"]
        preset_callbacks._select_preset(saved, preset_id)
        loaded = preset_callbacks.load_config_ui()
        self.assertEqual(loaded[1], preset_id)
        self.assertEqual(loaded[3:6], ("test-key", "http://localhost/v1", "glm-5.3"))
        self.assertNotIn("test-key", presets.CONFIG_FILE.read_text())
        saved[0].update(
            last_model_test={
                "report": "success",
                "tested_at": "test",
                "performance": "test",
            },
            reasoning_effort_supported=True,
            reasoning_effort_test_version=3,
            reasoning_effort="low",
        )
        preset_callbacks.handle_save_preset(
            saved,
            preset_id,
            preset_id,
            "Test model",
            "test-key",
            "http://localhost/v1",
            "new-model",
        )
        actual = presets.load_config()["presets"][0]
        self.assertNotIn("last_model_test", actual)
        self.assertNotIn("reasoning_effort", actual)

    def test_history_download_selection_and_two_click_delete(self):
        task_dir = self.root / "task"
        task_dir.mkdir()
        original = task_dir / "original.pdf"
        result = task_dir / "dual.pdf"
        debug = task_dir / "dual.decompressed.pdf"
        for path in (original, result, debug):
            path.write_bytes(b"%PDF-test")
        record = {
            "task_id": "task",
            "filename": "input.pdf",
            "time": "test time",
            "model": "test model",
            "status": "完成",
            "original_file": str(original),
            "result_files": [str(result), str(debug)],
        }
        history._add_history_record(record)
        self.assertEqual(history.download_history_file("task", "result"), [str(result)])
        self.assertEqual(history.show_history_files("task")[0], str(original))
        self.assertEqual(history.refresh_history("task")[1]["value"], "task")
        # Gradio supplies row_value after sorting/filtering; select that actual record.
        import gradio as gr

        event = gr.SelectData(
            None,
            {
                "index": (0, 0),
                "value": "input.pdf",
                "row_value": history._history_table([record])[0],
            },
        )
        selected = history.select_history_row([], event)
        self.assertEqual(selected[0]["value"], "task")
        self.assertEqual(selected[2], [str(result)])
        first = history.click_history_delete("task", None)
        self.assertEqual(first[1], "task")
        self.assertTrue(result.exists())
        history.click_history_delete("task", first[1])
        self.assertEqual(history._load_history(), [])
        self.assertFalse(task_dir.exists())

    def test_progress_clear_and_resume_share_the_same_task(self):
        pdf = self.root / "dual.pdf"
        pdf.write_bytes(b"%PDF-test")
        state._TASK.update(
            running=True,
            finished=False,
            status_lines=[],
            completed_stages=[],
            current_stage=None,
            stage_start=time.time(),
            overall_start=time.time(),
        )
        progress._record_native_progress_event(
            {
                "type": "progress_update",
                "stage": "Translate Paragraphs",
                "overall_progress": 42,
                "current": 2,
                "total": 5,
            }
        )
        self.assertEqual(state._TASK["progress_percent"], 42)
        self.assertIn("42", progress._task_snapshot_html())
        state._TASK.update(
            running=False,
            finished=True,
            result_files=[str(pdf)],
            output_dir=str(self.root),
        )
        clear_all(str(self.root))
        self.assertTrue(pdf.exists())
        files, _, output = next(tasks.resume_progress())
        self.assertEqual(files, [str(pdf)])
        self.assertEqual(output, str(self.root))
        pdf.unlink()
        self.assertIsNone(next(tasks.resume_progress())[0])

    def test_ui_registers_translation_history_and_queue_free_stop(self):
        demo = build_ui()
        config = demo.get_config_file()
        translate = next(
            item
            for item in config["dependencies"]
            if item.get("api_name") == "translate"
        )
        self.assertEqual(len(translate["inputs"]), 10)
        self.assertEqual(len(translate["outputs"]), 3)
        components = {item["id"]: item for item in config["components"]}
        stop = next(
            item
            for item in config["dependencies"]
            if any(
                components.get(target[0], {}).get("props", {}).get("value") == "⏹ 停止"
                for target in item["targets"]
            )
        )
        self.assertFalse(stop["queue"])
        self.assertTrue(
            any(
                "使用说明" in str(item["props"].get("value", ""))
                for item in components.values()
            )
        )
        self.assertTrue(
            any(
                "history-row-selected" in str(item.get("js", ""))
                for item in config["dependencies"]
            )
        )


class AuthenticationTests(unittest.TestCase):
    def test_disabled_auth_serves_ui(self):
        with patch.object(settings, "AUTH_ENABLED", False):
            with TestClient(server.create_app()) as client:
                response = client.get("/", follow_redirects=False)
                self.assertEqual(response.status_code, 200)
                config = client.get("/config").json()
                self.assertTrue(
                    any(
                        item.get("api_name") == "translate"
                        for item in config["dependencies"]
                    )
                )

    def test_oidc_callback_session_and_logout(self):
        from babeldoc_app import auth

        with (
            patch.object(settings, "AUTH_ENABLED", True),
            patch.object(settings, "OIDC_ISSUER", "https://identity.invalid"),
            patch.object(settings, "OIDC_CLIENT_ID", "test-client"),
            patch.object(settings, "OIDC_CLIENT_SECRET", "test-secret"),
            patch.object(settings, "APP_BASE_URL", "http://testserver"),
            patch.object(
                auth.oauth.oidc,
                "authorize_access_token",
                AsyncMock(
                    return_value={"userinfo": {"sub": "test-user", "name": "Test"}}
                ),
            ),
            patch.object(
                auth.oauth.oidc, "load_server_metadata", AsyncMock(return_value={})
            ),
        ):
            with TestClient(server.create_app()) as client:
                response = client.get("/", follow_redirects=False)
                self.assertEqual(response.status_code, 307)
                self.assertEqual(response.headers["location"], "/auth/login")
                response = client.get("/auth/callback", follow_redirects=False)
                self.assertEqual(response.status_code, 307)
                self.assertEqual(client.get("/").status_code, 200)
                self.assertEqual(client.get("/config").status_code, 200)
                client.get("/auth/logout", follow_redirects=False)
                self.assertEqual(
                    client.get("/", follow_redirects=False).status_code, 307
                )

    def test_incomplete_auth_settings_fail_before_ui_construction(self):
        with (
            patch.object(settings, "AUTH_ENABLED", True),
            patch.object(settings, "OIDC_ISSUER", ""),
        ):
            with self.assertRaisesRegex(SystemExit, "OIDC_ISSUER"):
                server.create_app()


if __name__ == "__main__":
    unittest.main()
