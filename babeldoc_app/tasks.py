"""Background task lifecycle and browser progress polling."""

import asyncio
import html
import os
import shutil
import threading
import time
from datetime import datetime

from .engine import _run_isolated_translation
from .history import (
    HISTORY_DIR,
    _add_history_record,
    _is_downloadable_result_pdf,
)
from .model_api import (
    REASONING_EFFORT_LEVELS,
    _is_glm53_model,
)
from .progress import (
    STAGE_WEIGHTS,
    _task_add_status,
    _task_snapshot_html,
)
from .state import (
    _TASK,
    _reset_stop,
    _stop_event,
    _task_lock,
)


def _run_translation_worker(
    pdf_file,
    api_key,
    base_url,
    model,
    lang_in,
    lang_out,
    output_mode,
    speed,
    disable_thinking=False,
    reasoning_effort=None,
):
    """后台线程：监督独立翻译进程并持续更新全局任务状态。
    该函数不依赖任何 Gradio 请求上下文，因此浏览器刷新页面不会影响它的执行。
    """
    task_id = datetime.now().strftime("%Y%m%d%H%M%S%f")
    task_dir = HISTORY_DIR / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    original_file = str(task_dir / f"original_{os.path.basename(pdf_file)}")
    try:
        shutil.copy2(pdf_file, original_file)
    except Exception:
        original_file = None

    # 速度等级 → 参数映射
    speed_map = {
        "标准": {"qps": 4, "pool": 4, "no_glossary": False, "label": "标准"},
        "快速": {"qps": 10, "pool": 8, "no_glossary": False, "label": "快速"},
        "极速": {"qps": 20, "pool": 12, "no_glossary": True, "label": "极速"},
    }
    sp = speed_map.get(speed, speed_map["标准"])

    output_dir = str(task_dir)
    with _task_lock:
        _TASK["output_dir"] = output_dir
        _TASK["task_id"] = task_id

    _task_add_status(
        '<div class="log-line log-info"><b>&#128196; 文件:</b> '
        f"{os.path.basename(pdf_file)}</div>"
    )
    _task_add_status(
        '<div class="log-line log-info"><b>&#127758; 模型:</b> '
        f"{model} ({base_url})</div>"
    )
    _task_add_status(
        '<div class="log-line log-info"><b>&#128272;</b> '
        f"{lang_in} &#8594; {lang_out}</div>"
    )
    _task_add_status(
        '<div class="log-line log-info"><b>&#9889;</b> '
        f"速度: {sp['label']} (QPS={sp['qps']}, 线程={sp['pool']}"
        f"{', 跳过术语提取' if sp['no_glossary'] else ''})</div>"
    )
    _task_add_status('<div class="log-separator"></div>')
    _task_add_status(
        '<div class="log-line log-info"><b>&#128640; 翻译启动，请稍候...</b></div>'
    )

    def _finish(
        extra: str,
        result_file: str | None = None,
        status: str = "完成",
        output_files: list | None = None,
    ) -> None:
        with _task_lock:
            _TASK["extra_html"] = extra
            _TASK["result_file"] = result_file
            _TASK["running"] = False
            _TASK["finished"] = True
            overall_start = _TASK["overall_start"]
        total_elapsed = time.time() - overall_start
        tm, ts = divmod(int(total_elapsed), 60)
        duration = f"{tm}m{ts}s" if tm > 0 else f"{ts}s"
        _add_history_record(
            {
                "task_id": task_id,
                "filename": os.path.basename(pdf_file),
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "lang": f"{lang_in} → {lang_out}",
                "model": model,
                "settings": (
                    f"{sp['label']} · "
                    + (
                        f"推理深度 {reasoning_effort}"
                        if reasoning_effort
                        else ("关闭思考" if disable_thinking else "开启思考")
                    )
                    + " · "
                    + (
                        "双语"
                        if output_mode == "both"
                        else ("双语对照" if output_mode == "dual_only" else "单语")
                    )
                ),
                "duration": duration,
                "status": status,
                "original_file": original_file,
                "result_file": result_file,
                "result_files": output_files or [],
            }
        )

    # 直接消费 BabelDOC API 的进度事件。此前的 CLI 方案需 --debug 才能读到
    # overall_progress，进而会把调试框绘制到最终 PDF；API 方案不需要该开关。
    try:
        result = _run_isolated_translation(
            dict(
                pdf_file=pdf_file,
                api_key=api_key,
                base_url=base_url,
                model=model,
                lang_in=lang_in,
                lang_out=lang_out,
                output_dir=output_dir,
                qps=sp["qps"],
                pool_workers=sp["pool"],
                output_mode=output_mode,
                disable_thinking=disable_thinking,
                reasoning_effort=reasoning_effort,
            )
        )
        if _stop_event.is_set():
            _finish(
                '<div class="log-line log-warning" style="font-weight:bold">&#9209; 翻译已停止</div>',
                status="已停止",
            )
            return

        output_files = []
        for path in (
            getattr(result, "dual_pdf_path", None),
            getattr(result, "mono_pdf_path", None),
        ):
            if path and _is_downloadable_result_pdf(str(path)):
                output_files.append(str(path))
        output_files = list(dict.fromkeys(output_files))
        if not output_files:
            raise RuntimeError("未找到输出 PDF 文件")

        with _task_lock:
            _TASK["current_stage"] = None
            _TASK["completed_stages"] = [name for name, _, _ in STAGE_WEIGHTS]
            _TASK["progress_percent"] = 100.0
            _TASK["result_files"] = output_files
            overall_start = _TASK["overall_start"]
        total_elapsed = time.time() - overall_start
        tm, ts = divmod(int(total_elapsed), 60)
        total_duration = f"{tm}m{ts}s" if tm > 0 else f"{ts}s"
        result_file = next(
            (
                f
                for f in output_files
                if "dual" in f.lower() or "bilingual" in f.lower()
            ),
            output_files[0],
        )
        extra = (
            '<div class="log-line log-success">&#10004; 翻译完成！'
            f"(总用时 {total_duration})</div>"
            '<div class="log-line log-info" style="margin-top:4px">输出文件:</div>'
            + "".join(
                '<div class="log-line log-info" style="padding-left:12px;font-size:12px">'
                f"&#128196; {os.path.basename(f)}</div>"
                for f in output_files
            )
        )
        _finish(extra, result_file, output_files=output_files)
        return
    except asyncio.CancelledError:
        _finish(
            '<div class="log-line log-warning" style="font-weight:bold">&#9209; 翻译已停止</div>',
            status="已停止",
        )
        return
    except Exception as e:
        _finish(
            '<div class="log-line log-error" style="font-weight:bold">'
            f"&#10060; 错误: {html.escape(str(e))}</div>",
            status="失败",
        )
        return


def translate_pdf(
    pdf_file,
    api_key,
    base_url,
    model,
    lang_in,
    lang_out,
    output_mode,
    speed,
    disable_thinking=False,
    reasoning_effort=None,
):
    """启动翻译任务并轮询展示进度。

    实际翻译在后台线程 `_run_translation_worker` 中运行，状态保存在全局
    `_TASK` 字典里。刷新浏览器页面会取消这里的轮询循环，但后台线程不受影响，
    翻译会继续进行；刷新后可通过页面自动或手动重新接上最新进度（见 `resume_progress`）。
    """
    disable_thinking = disable_thinking == "关闭" and not _is_glm53_model(model)
    reasoning_effort = (
        reasoning_effort
        if _is_glm53_model(model) and reasoning_effort in REASONING_EFFORT_LEVELS
        else None
    )
    if not pdf_file:
        yield (
            None,
            '<div class="log-line log-error" style="font-weight:bold">⚠️ 请先上传 PDF 文件</div>',
            None,
        )
        return
    if not api_key:
        yield (
            None,
            '<div class="log-line log-error" style="font-weight:bold">⚠️ 请先选择或创建 LLM 预设（需包含 API Key）</div>',
            None,
        )
        return

    if _TASK["running"]:
        # 已有任务在跑，直接接上显示
        yield from resume_progress()
        return

    _reset_stop()
    with _task_lock:
        _TASK.update(
            running=True,
            status_lines=[],
            completed_stages=[],
            current_stage=None,
            stage_start=time.time(),
            overall_start=time.time(),
            active_serial=0,
            result_file=None,
            result_files=None,
            output_dir=None,
            task_id=None,
            finished=False,
            extra_html="",
            last_activity=time.time(),
            warning_count=0,
            last_warning="",
            progress_percent=0.0,
            progress_is_native=False,
            stage_current=None,
            stage_total=None,
        )

    worker = threading.Thread(
        target=_run_translation_worker,
        args=(
            pdf_file,
            api_key,
            base_url,
            model,
            lang_in,
            lang_out,
            output_mode,
            speed,
            disable_thinking,
            reasoning_effort,
        ),
        daemon=True,
    )
    worker.start()

    yield from resume_progress()


def resume_progress():
    """轮询全局任务状态并 yield 给 UI，直到任务结束。
    可安全被取消（如页面刷新导致的生成器取消）——不会影响后台翻译线程。
    """
    last_len = -1
    next_heartbeat = 0.0
    while True:
        with _task_lock:
            running = _TASK["running"]
            finished = _TASK["finished"]
            extra_html = _TASK["extra_html"]
            stored_result_files = _TASK.get("result_files") or (
                [_TASK["result_file"]] if _TASK.get("result_file") else None
            )
            result_files = [
                path
                for path in (stored_result_files or [])
                if _is_downloadable_result_pdf(path)
            ]
            # 文件可能被外部清理；不把已失效路径交给 gr.File 后处理。
            if stored_result_files and len(result_files) != len(stored_result_files):
                _TASK["result_files"] = result_files or None
                _TASK["result_file"] = result_files[0] if result_files else None
            output_dir = _TASK["output_dir"]
            cur_len = len(_TASK["status_lines"])

        if finished:
            yield result_files or None, _task_snapshot_html(extra_html), output_dir
            return

        now = time.monotonic()
        if cur_len != last_len or now >= next_heartbeat:
            last_len = cur_len
            next_heartbeat = now + 1.0
            yield None, _task_snapshot_html(), output_dir

        if not running:
            return

        time.sleep(0.5)
