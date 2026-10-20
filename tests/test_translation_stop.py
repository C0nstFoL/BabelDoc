"""Run with: python -m unittest discover -s tests -v (application dependencies required)."""

import asyncio
import io
import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")

from babeldoc_app import engine, state, tasks


class TranslationProcessTests(unittest.TestCase):
    def setUp(self):
        state._reset_stop()
        state._TASK.update(running=True, finished=False, overall_start=time.time())
        self.popen = subprocess.Popen

    def tearDown(self):
        state._TASK["running"] = False
        state._reset_stop()

    def launch(self, script):
        def start(_args, **kwargs):
            return self.popen([engine._sys.executable, "-u", "-c", script], **kwargs)

        return patch.object(engine.subprocess, "Popen", side_effect=start)

    def test_blocked_worker_and_ocr_descendant_are_killed(self):
        ready = threading.Event()
        with tempfile.TemporaryDirectory() as tmp:
            pid_path = Path(tmp) / "descendant.pid"
            script = f"""
import json, signal, subprocess, sys, time
json.load(sys.stdin)
signal.signal(signal.SIGTERM, signal.SIG_IGN)
p = subprocess.Popen([sys.executable, '-c', 'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)'])
open({str(pid_path)!r}, 'w').write(str(p.pid))
time.sleep(0.2)
print('BABELDOC_EVENT:' + json.dumps({{'type': 'status', 'message': 'ready'}}), flush=True)
time.sleep(60)
"""
            cancelled = []

            def run():
                try:
                    engine._run_isolated_translation({"api_key": "test-secret"})
                except asyncio.CancelledError:
                    cancelled.append(True)

            with (
                self.launch(script),
                patch.object(
                    engine, "_task_add_status", side_effect=lambda _: ready.set()
                ),
            ):
                worker = threading.Thread(target=run)
                worker.start()
                self.assertTrue(ready.wait(5))
                pid = state._running_process.pid
                started = time.monotonic()
                state.request_stop()
                self.assertLess(time.monotonic() - started, 0.1)
                worker.join(2)
                self.assertFalse(worker.is_alive())
                self.assertLess(time.monotonic() - started, 1.5)
                self.assertEqual(cancelled, [True])
                self.assertIsNone(state._running_process)
                self.assertFalse(Path(f"/proc/{pid}").exists())
                child_stat = Path(f"/proc/{pid_path.read_text()}/stat")
                # A reparented zombie may await PID 1; it must not execute anymore.
                if child_stat.exists():
                    self.assertEqual(child_stat.read_text().split()[2], "Z")
                print(
                    f"blocked translation + OCR group stopped in {time.monotonic() - started:.3f}s"
                )

    def test_success_preserves_native_progress_and_result_paths(self):
        script = """
import json, sys
json.load(sys.stdin)
for event in [
    {'type': 'progress_update', 'stage': 'Translate Paragraphs', 'overall_progress': 42},
    {'type': 'result', 'dual_pdf_path': '/tmp/dual.pdf', 'mono_pdf_path': '/tmp/mono.pdf'}
]:
    print('BABELDOC_EVENT:' + json.dumps(event), flush=True)
"""
        with (
            self.launch(script),
            patch.object(engine, "_record_native_progress_event") as progress,
        ):
            result = engine._run_isolated_translation({})
        self.assertEqual(result.dual_pdf_path, "/tmp/dual.pdf")
        self.assertEqual(result.mono_pdf_path, "/tmp/mono.pdf")
        self.assertEqual(progress.call_args.args[0]["overall_progress"], 42)
        self.assertIsNone(state._running_process)

    def test_native_finish_result_is_not_serialized_as_progress(self):
        from types import SimpleNamespace

        result = SimpleNamespace(dual_pdf_path="/tmp/dual.pdf", mono_pdf_path=None)

        async def translate(_config):
            yield {"type": "progress_update", "overall_progress": 50}
            yield {"type": "finish", "translate_result": result}

        progress = []
        with (
            patch("babeldoc.docvision.doclayout.DocLayoutModel.load_onnx"),
            patch("babeldoc.format.pdf.high_level.async_translate", translate),
            patch("babeldoc.format.pdf.translation_config.TranslationConfig"),
            patch("babeldoc.translator.translator.set_translate_rate_limiter"),
            patch.object(engine, "_create_translation_translator"),
        ):
            actual = asyncio.run(
                engine._translate_with_native_events(
                    "/tmp/input.pdf",
                    "key",
                    "http://localhost",
                    "test",
                    "en",
                    "zh",
                    "/tmp",
                    4,
                    4,
                    "both",
                    False,
                    None,
                    event_callback=progress.append,
                )
            )
        self.assertIs(actual, result)
        self.assertEqual(
            progress, [{"type": "progress_update", "overall_progress": 50}]
        )

    def test_child_protocol_includes_ocr_progress_and_result(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()
            options = {"pdf_file": "/tmp/scan.pdf", "output_dir": tmp, "lang_in": "en"}
            fake_translate = AsyncMock(
                return_value=SimpleNamespace(
                    dual_pdf_path=Path(tmp) / "dual.pdf", mono_pdf_path=None
                )
            )
            with (
                patch.object(engine._sys, "stdin", io.StringIO(json.dumps(options))),
                patch.object(engine._sys, "stdout", output),
                patch.object(engine, "_pdf_needs_ocr", return_value=True),
                patch.object(engine, "_ocr_preprocess", return_value=True),
                patch.object(engine, "_translate_with_native_events", fake_translate),
            ):
                engine._translation_child_main()
            events = [
                json.loads(line[len(engine._EVENT_PREFIX) :])
                for line in output.getvalue().splitlines()
            ]
            self.assertEqual(
                [e["type"] for e in events], ["status", "status", "result"]
            )
            self.assertEqual(
                fake_translate.call_args.kwargs["pdf_file"],
                str(Path(tmp) / "ocr" / "scan.pdf"),
            )
            self.assertIsNone(events[-1]["mono_pdf_path"])

    def test_worker_failure_is_reported(self):
        script = """
import json, sys
json.load(sys.stdin)
print('BABELDOC_EVENT:' + json.dumps({'type': 'error', 'error': 'test failure'}), flush=True)
sys.exit(1)
"""
        with self.launch(script), self.assertRaisesRegex(RuntimeError, "test failure"):
            engine._run_isolated_translation({})
        self.assertIsNone(state._running_process)

    def test_stop_before_process_registration_and_restart(self):
        original_popen = self.popen

        def start_then_stop(args, **kwargs):
            proc = original_popen(
                [engine._sys.executable, "-c", "import time; time.sleep(60)"], **kwargs
            )
            state.request_stop()
            return proc

        with patch.object(engine.subprocess, "Popen", side_effect=start_then_stop):
            with self.assertRaises(asyncio.CancelledError):
                engine._run_isolated_translation({})
        self.assertIsNone(state._running_process)
        state._reset_stop()
        self.test_success_preserves_native_progress_and_result_paths()

    def test_stopped_task_is_saved_and_releases_running_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "input.pdf"
            pdf.write_bytes(b"%PDF-test")
            with (
                patch.object(tasks, "HISTORY_DIR", Path(tmp)),
                patch.object(
                    tasks,
                    "_run_isolated_translation",
                    side_effect=asyncio.CancelledError,
                ),
                patch.object(tasks, "_add_history_record") as history,
            ):
                tasks._run_translation_worker(
                    str(pdf),
                    "key",
                    "http://localhost",
                    "test",
                    "en",
                    "zh",
                    "both",
                    "标准",
                )
            self.assertFalse(state._TASK["running"])
            self.assertTrue(state._TASK["finished"])
            self.assertEqual(history.call_args.args[0]["status"], "已停止")
            self.assertTrue(Path(history.call_args.args[0]["original_file"]).exists())


if __name__ == "__main__":
    unittest.main()
