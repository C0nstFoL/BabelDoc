"""BabelDOC and OCR execution in an isolated child process."""

import asyncio
import html
import json
import os
import queue
import signal
import subprocess
import sys as _sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from . import state
from .progress import (
    _record_native_progress_event,
    _task_add_status,
)
from .settings import CONFIG_DIR
from .state import (
    _signal_translation_process,
    _stop_event,
    _task_lock,
)


def _create_translation_translator(
    lang_in, lang_out, model, base_url, api_key, disable_thinking, reasoning_effort
):
    """构造翻译器，并把已验证的推理深度写入实际请求体。"""
    from babeldoc.translator.translator import OpenAITranslator

    translator = OpenAITranslator(
        lang_in=lang_in,
        lang_out=lang_out,
        model=model,
        base_url=base_url.rstrip("/") + "/",
        api_key=api_key,
        thinking="disabled"
        if disable_thinking
        else ("enabled" if reasoning_effort else None),
    )
    if reasoning_effort:
        # BabelDOC 的 reasoning 参数会发送 {"reasoning": {"effort": ...}}；
        # GLM 需要的是顶层 reasoning_effort。
        translator.extra_body["reasoning_effort"] = reasoning_effort
        translator.add_cache_impact_parameters("reasoning_effort", reasoning_effort)
    return translator


async def _translate_with_native_events(
    pdf_file: str,
    api_key: str,
    base_url: str,
    model: str,
    lang_in: str,
    lang_out: str,
    output_dir: str,
    qps: int,
    pool_workers: int,
    output_mode: str,
    disable_thinking: bool,
    reasoning_effort: str | None,
    event_callback=None,
):
    """通过 BabelDOC Python API 翻译，并直接接收精确进度事件。

    这里必须保持 debug=False：BabelDOC 的 debug 会向最终 PDF 注入布局框与标记。
    """
    from babeldoc.docvision.doclayout import DocLayoutModel
    from babeldoc.format.pdf.high_level import async_translate
    from babeldoc.format.pdf.translation_config import TranslationConfig
    from babeldoc.translator.translator import set_translate_rate_limiter

    translator = _create_translation_translator(
        lang_in,
        lang_out,
        model,
        base_url,
        api_key,
        disable_thinking,
        reasoning_effort,
    )
    set_translate_rate_limiter(qps)
    doc_layout_model = DocLayoutModel.load_onnx()
    config = TranslationConfig(
        translator=translator,
        term_extraction_translator=translator,
        input_file=pdf_file,
        lang_in=lang_in,
        lang_out=lang_out,
        doc_layout_model=doc_layout_model,
        output_dir=output_dir,
        debug=False,
        no_dual=output_mode == "mono_only",
        no_mono=output_mode == "dual_only",
        qps=qps,
        pool_max_workers=pool_workers,
        report_interval=1,
        use_rich_pbar=False,
        auto_enable_ocr_workaround=True,
    )
    getattr(doc_layout_model, "init_font_mapper", lambda _config: None)(config)
    async for event in async_translate(config):
        if event.get("type") in {"progress_start", "progress_update", "progress_end"}:
            (event_callback or _record_native_progress_event)(event)
        if event.get("type") == "error":
            raise RuntimeError(event.get("error", "BabelDOC 翻译失败"))
        if event.get("type") == "finish":
            return event["translate_result"]
    raise RuntimeError("BabelDOC 未返回翻译结果")


_EVENT_PREFIX = "BABELDOC_EVENT:"
_STOP_GRACE_SECONDS = 0.5


def _translation_child_main():
    """子进程通过 stdin 接收配置（含密钥），stdout 只输出进度协议。"""
    protocol_output = _sys.stdout
    _sys.stdout = _sys.stderr

    def emit(event):
        protocol_output.write(
            _EVENT_PREFIX + json.dumps(event, ensure_ascii=False) + "\n"
        )
        protocol_output.flush()

    try:
        options = json.load(_sys.stdin)
        pdf_file = options["pdf_file"]
        if _pdf_needs_ocr(pdf_file):
            emit(
                {
                    "type": "status",
                    "message": "🔍 检测到扫描版 PDF，正在 OCR 识别文字（tesseract）...",
                }
            )
            ocr_dir = Path(options["output_dir"]) / "ocr"
            ocr_dir.mkdir(parents=True, exist_ok=True)
            ocr_input = str(ocr_dir / os.path.basename(pdf_file))
            if _ocr_preprocess(pdf_file, options["lang_in"], ocr_input):
                options["pdf_file"] = ocr_input
                emit({"type": "status", "message": "✓ OCR 预处理完成"})
            else:
                emit(
                    {
                        "type": "status",
                        "message": "⚠ OCR 预处理失败，将直接尝试翻译原文件",
                    }
                )
        result = asyncio.run(
            _translate_with_native_events(**options, event_callback=emit)
        )
        emit(
            {
                "type": "result",
                "dual_pdf_path": str(result.dual_pdf_path)
                if result.dual_pdf_path
                else None,
                "mono_pdf_path": str(result.mono_pdf_path)
                if result.mono_pdf_path
                else None,
            }
        )
    except Exception as exc:
        emit({"type": "error", "error": str(exc)})
        raise SystemExit(1)


def _run_isolated_translation(options):
    """监督进程，停止超过半秒仍未退出时强制结束整个进程组。"""
    if _stop_event.is_set():
        raise asyncio.CancelledError()
    proc = subprocess.Popen(
        [
            _sys.executable,
            str(CONFIG_DIR / "babeldoc_translator.py"),
            "--translation-worker",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    with _task_lock:
        state._running_process = proc
    events = queue.Queue()

    def read_events():
        try:
            for line in proc.stdout:
                if line.startswith(_EVENT_PREFIX):
                    events.put(json.loads(line[len(_EVENT_PREFIX) :]))
        except Exception as exc:
            events.put({"type": "error", "error": str(exc)})
        finally:
            events.put(None)

    reader = threading.Thread(target=read_events, daemon=True)
    reader.start()
    result = None
    error = None
    stop_started = None
    stream_closed = False
    try:
        # 密钥不进入命令行参数、临时文件或日志。
        try:
            json.dump(options, proc.stdin)
            proc.stdin.close()
        except BrokenPipeError:
            if not _stop_event.is_set():
                raise
        while True:
            if _stop_event.is_set():
                if stop_started is None:
                    stop_started = time.monotonic()
                    _signal_translation_process(proc, signal.SIGTERM)
                if (
                    proc.poll() is not None
                    or time.monotonic() - stop_started >= _STOP_GRACE_SECONDS
                ):
                    _signal_translation_process(proc, signal.SIGKILL)
                    proc.wait()
                    raise asyncio.CancelledError()
            try:
                event = events.get(timeout=0.1)
            except queue.Empty:
                if proc.poll() is not None and stream_closed:
                    break
                continue
            if event is None:
                stream_closed = True
                if proc.poll() is not None:
                    break
                continue
            if event["type"] == "result":
                result = SimpleNamespace(**event)
            elif event["type"] == "error":
                error = event.get("error", "BabelDOC 翻译失败")
            elif event["type"] == "status":
                _task_add_status(
                    '<div class="log-line log-info">'
                    + html.escape(event["message"])
                    + "</div>"
                )
            else:
                _record_native_progress_event(event)
        if _stop_event.is_set():
            raise asyncio.CancelledError()
        if proc.returncode != 0 or result is None:
            raise RuntimeError(
                error or f"翻译进程异常退出 (exit code: {proc.returncode})"
            )
        return result
    finally:
        # 同时回收 OCR、BabelDOC 派生的子进程；确认退出后才允许启动新任务。
        _signal_translation_process(proc, signal.SIGKILL)
        proc.wait()
        if not proc.stdin.closed:
            proc.stdin.close()
        reader.join(timeout=1)
        proc.stdout.close()
        with _task_lock:
            if state._running_process is proc:
                state._running_process = None


# ---- 扫描版 PDF OCR 预处理 ---- #


def _pdf_needs_ocr(pdf_path: str) -> bool:
    """检测 PDF 是否为纯扫描件（超过 80% 的页面几乎没有有效文本层）。

    注意：扫描件常带每页重复的水印文字，需先过滤跨页重复的行，
    否则会被水印误判为有文字层。
    """
    try:
        try:
            import pymupdf
        except ImportError:
            import fitz as pymupdf

        with pymupdf.open(pdf_path) as doc:
            pages_text = [page.get_text().strip() for page in doc]
        if not pages_text:
            return False

        # 出现在 >=60% 页面上的行视为水印/页眉页脚
        n = len(pages_text)
        line_counter: dict[str, int] = {}
        for text in pages_text:
            for line in {ln.strip() for ln in text.splitlines() if ln.strip()}:
                line_counter[line] = line_counter.get(line, 0) + 1
        watermark_lines = {ln for ln, c in line_counter.items() if c >= max(2, n * 0.6)}

        def _real_text_len(text: str) -> int:
            return sum(
                len(ln)
                for ln in text.splitlines()
                if ln.strip() and ln.strip() not in watermark_lines
            )

        scanned = sum(1 for t in pages_text if _real_text_len(t) < 50)
        return scanned / n > 0.8
    except Exception:
        return False


def _ocr_preprocess(pdf_path: str, lang_in: str, out_path: str) -> bool:
    """用 ocrmypdf（tesseract）为扫描 PDF 添加可提取的文字层"""
    lang_map = {"en": "eng", "zh": "chi_sim"}
    tess_lang = lang_map.get((lang_in or "en").split("-")[0].lower(), "eng+chi_sim")
    try:
        # --force-ocr：扫描件常带仅含水印的假文字层，--skip-text 会因此跳过 OCR；
        # 强制对整页做 OCR 才能生成真正的正文文字层
        result = subprocess.run(
            [
                "ocrmypdf",
                "--force-ocr",
                "--output-type",
                "pdf",
                "--quiet",
                "-l",
                tess_lang,
                pdf_path,
                out_path,
            ],
            capture_output=True,
            timeout=600,
        )
        return result.returncode == 0 and os.path.exists(out_path)
    except Exception:
        return False
