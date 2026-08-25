import os
import re
import json
import base64
import subprocess
import threading
import tempfile
import shutil
import time
import glob
from datetime import datetime
from pathlib import Path
import gradio as gr

# 默认 DeepSeek 配置
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"

# 配置文件路径（放在项目目录下，避免 macOS 沙箱权限问题）
CONFIG_DIR = Path(__file__).parent
CONFIG_FILE = CONFIG_DIR / ".babeldoc_config.json"


def _obscure(s: str) -> str:
    """简单编码，避免明文存储 API Key"""
    return base64.b64encode(s.encode()).decode()


def _reveal(s: str) -> str:
    """解码存储的 API Key"""
    try:
        return base64.b64decode(s.encode()).decode()
    except Exception:
        return ""


def load_config():
    """从本地文件加载配置"""
    if not CONFIG_FILE.exists():
        return {}
    try:
        data = json.loads(CONFIG_FILE.read_text())
        if data.get("api_key"):
            data["api_key"] = _reveal(data["api_key"])
        return data
    except Exception:
        return {}


def save_config(api_key, base_url, model):
    """保存配置到本地文件"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "api_key": _obscure(api_key) if api_key else "",
        "base_url": base_url,
        "model": model,
    }
    CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


# ---- 历史记录 ---- #
HISTORY_DIR = CONFIG_DIR / "outputs"
HISTORY_FILE = CONFIG_DIR / ".babeldoc_history.json"
_history_lock = threading.Lock()


def _load_history() -> list[dict]:
    """加载历史任务记录列表（按时间倒序）"""
    if not HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text())
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []


def _save_history(records: list[dict]) -> None:
    HISTORY_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2))


def _add_history_record(record: dict) -> None:
    """新增一条历史记录（追加到最前面）"""
    with _history_lock:
        records = _load_history()
        records.insert(0, record)
        _save_history(records)


def _delete_history_record(task_id: str) -> None:
    """删除一条历史记录，并同步删除其任务目录下的文件"""
    with _history_lock:
        records = _load_history()
        remaining = []
        for r in records:
            if r.get("task_id") == task_id:
                task_dir = HISTORY_DIR / task_id
                if task_dir.exists():
                    try:
                        shutil.rmtree(task_dir)
                    except Exception:
                        pass
            else:
                remaining.append(r)
        _save_history(remaining)


def _history_choices(records: list[dict]) -> list[tuple[str, str]]:
    """生成 Dropdown 的 (显示名, task_id) 选项列表"""
    choices = []
    for r in records:
        label = f"{r.get('filename', '?')} | {r.get('time', '')} | {r.get('lang', '')} | {r.get('status', '')}"
        choices.append((label, r.get("task_id")))
    return choices


def _history_table(records: list[dict]) -> list[list[str]]:
    """生成 Dataframe 展示用的表格数据"""
    return [
        [
            r.get("filename", ""),
            r.get("time", ""),
            r.get("lang", ""),
            r.get("duration", ""),
            r.get("status", ""),
        ]
        for r in records
    ]


def refresh_history():
    """刷新历史记录表格与选择框"""
    records = _load_history()
    return _history_table(records), gr.update(choices=_history_choices(records), value=None)


def download_history_file(task_id: str, kind: str):
    """根据选中的 task_id 返回原文或译文文件路径"""
    if not task_id:
        return None
    records = _load_history()
    for r in records:
        if r.get("task_id") == task_id:
            path = r.get("original_file") if kind == "original" else r.get("result_file")
            if path and os.path.exists(path):
                return path
            return None
    return None


def delete_history_selected(task_id: str):
    """删除选中的历史记录，并刷新表格"""
    if task_id:
        _delete_history_record(task_id)
    records = _load_history()
    return _history_table(records), gr.update(choices=_history_choices(records), value=None), None, None


# ---- 停止机制 ---- #
_stop_event = threading.Event()
_running_process: subprocess.Popen | None = None

# ---- 后台任务全局状态 ----
# 翻译在独立线程中运行，状态写入这个全局字典，
# 这样即使用户刷新页面（Gradio 请求的生成器被取消），
# 后台任务也不受影响，刷新后重新查看即可接上最新状态。
_TASK: dict = {
    "running": False,          # 是否有任务在跑
    "status_lines": [],        # 状态日志（HTML 片段列表）
    "completed_stages": [],    # 已完成阶段
    "current_stage": None,     # 当前阶段
    "stage_start": 0.0,
    "overall_start": 0.0,
    "active_serial": 0,
    "result_file": None,       # 完成后的结果文件路径
    "output_dir": None,        # 本次任务的临时输出目录
    "task_id": None,           # 本次任务的历史记录 ID
    "finished": False,         # 任务是否已结束（成功/失败/停止）
    "extra_html": "",          # 结束时追加的提示 HTML
}
_task_lock = threading.Lock()


def request_stop():
    """请求停止翻译（由 UI 按钮调用）"""
    _stop_event.set()
    proc = _running_process
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
        except Exception:
            pass


def _reset_stop():
    """重置停止状态"""
    _stop_event.clear()
    global _running_process
    _running_process = None


# ---- 日志与进度 ---- #
import sys as _sys

STAGE_WEIGHTS: list[tuple[str, float, str]] = [
    ("DetectScannedFile", 2.45, "扫描检测"),
    ("Parse Page Layout", 14.03, "页面布局解析"),
    ("Parse Table", 1.0, "表格解析"),
    ("Parse Paragraphs", 6.26, "段落解析"),
    ("Parse Formulas and Styles", 1.66, "公式与样式解析"),
    ("Automatic Term Extraction", 30.0, "术语提取"),
    ("Translate Paragraphs", 46.96, "段落翻译"),
    ("Typesetting", 4.71, "排版"),
    ("Add Fonts", 0.61, "字体嵌入"),
    ("Generate drawing instructions", 1.96, "生成绘图指令"),
]
_TOTAL_WEIGHT = sum(w for _, w, _ in STAGE_WEIGHTS)
_STAGE_INDEX: dict[str, int] = {name: i for i, (name, _, _) in enumerate(STAGE_WEIGHTS)}


def _parse_log(raw: str) -> tuple[str, str, str] | None:
    """解析 babeldoc 日志行，返回 (timestamp, level, message) 或 None"""
    m = re.match(
        r"(\[\d{2}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}\])"
        r"\s+(WARNING|ERROR|INFO)\s+"
        r"(?:WARNING|ERROR|INFO):babeldoc\..*?:"
        r"\s*(.+)",
        raw,
    )
    if m:
        return m.groups()  # (ts, level, msg)
    return None


def _detect_stage_from_msg(msg: str) -> str | None:
    """根据日志消息检测当前阶段名称"""
    patterns = [
        ("DetectScannedFile", r"DetectScannedFile|扫描件检测"),
        ("Parse Page Layout", r"Parse Page Layout|页面布局|Clustered into|drawing boxes|Annotated images"),
        ("Parse Table", r"Parse Table|表格解析"),
        ("Parse Paragraphs", r"Parse Paragraphs|段落解析"),
        ("Parse Formulas and Styles", r"Parse Formulas and Styles|公式.*样式|样式.*公式"),
        ("Automatic Term Extraction", r"Automatic Term Extraction|terms? extract|术语提取"),
        ("Translate Paragraphs", r"Translate Paragraphs|paragraphs? translat|il_translator|段落翻译|LLM translat"),
        ("Typesetting", r"Typesetting|排版"),
        ("Add Fonts", r"Add Fonts|Font (mapper|subsetting)|字体|fontmap"),
        ("Generate drawing instructions", r"Generate drawing|绘图指令|PDF save|PDF.*subsetting"),
    ]
    for stage_name, pattern in patterns:
        if re.search(pattern, msg, re.IGNORECASE):
            return stage_name
    return None


def _detect_stage_from_raw(raw: str) -> str | None:
    """从原始（未解析）日志行检测阶段 — 利用模块路径中的阶段信息"""
    patterns = [
        ("DetectScannedFile", r"detect_scanned_file"),
        ("Parse Page Layout", r"layout_parser"),
        ("Parse Table", r"table_parser"),
        ("Parse Paragraphs", r"paragraph_finder"),
        ("Parse Formulas and Styles", r"styles_and_formulas|remove_descent"),
        ("Automatic Term Extraction", r"automatic_term_extractor"),
        ("Translate Paragraphs", r"il_translator|translate_paragraph"),
        ("Typesetting", r"typesetting"),
        ("Add Fonts", r"fontmap"),
        ("Generate drawing instructions", r"pdf_creater|backend"),
    ]
    for stage_name, pattern in patterns:
        if re.search(pattern, raw, re.IGNORECASE):
            return stage_name
    return None


# ---- 进度条（阶段 + JS 计时器 + spinner）---- #
def _build_progress_html(
    completed_stages: list[str],
    current_stage: str | None,
    start_time: float,
    active_serial: int = 0,
) -> str:
    """构建进度条 HTML，含 CSS spinner、JS 计时器、alive 心跳"""
    if not current_stage and not completed_stages:
        return ""

    bars: list[str] = []
    for name, weight, label in STAGE_WEIGHTS:
        pct = weight / _TOTAL_WEIGHT * 100
        if name in completed_stages:
            cls = "pg-done"
        elif name == current_stage:
            cls = "pg-current"
        else:
            cls = "pg-pending"
        bars.append(
            f'<div class="{cls}" style="flex:{pct:.2f}"'
            f' title="{label}"></div>'
        )

    done_weight = sum(w for name, w, _ in STAGE_WEIGHTS if name in completed_stages)
    progress = done_weight / _TOTAL_WEIGHT * 100

    current_label = ""
    for name, _, label in STAGE_WEIGHTS:
        if name == current_stage:
            current_label = label
            break

    # 活跃脉冲点：有 current_stage 时显示
    active_dot = (
        '<span class="alive-dot"></span> '
        if current_stage
        else ""
    )

    # JS 计时器（自清理，避免孤儿 interval）
    timer_html = (
        f'<span class="elapsed" id="elapsed-{active_serial}"></span>'
        f'<script>(function(){{'
        f'var start={start_time}*1000,sid="elapsed-{active_serial}";'
        f'if(window._babeldocTimers){{'
        f'window._babeldocTimers.forEach(clearInterval);'
        f'}}window._babeldocTimers=[];'
        f'var el=document.getElementById(sid);'
        f'if(!el)return;'
        f'var tid=setInterval(function(){{'
        f'var e=document.getElementById(sid);'
        f'if(!e){{clearInterval(tid);return;}}'
        f'var s=Math.floor((Date.now()-start)/1000);'
        f'var m=Math.floor(s/60);s=s%60;'
        f'e.textContent="(已用 "+(m>0?m+"m":"")+s+"s)";'
        f'}},1000);'
        f'window._babeldocTimers.push(tid);'
        f'}})();</script>'
    )

    return (
        '<div class="progress-area">'
        f'<span class="progress-text">'
        f'{active_dot}'
        f'<span class="spinner"></span> '
        f'<b style="color:#4FC3F7">{current_label}</b> '
        f'{timer_html}'
        f'<span style="float:right;color:#4CAF50;font-weight:bold">{progress:.0f}%</span>'
        f"</span>"
        '<div class="progress-bar">'
        + "".join(bars)
        + "</div>"
        + "</div>"
    )


def _task_add_status(html: str) -> None:
    """向全局任务状态追加一条日志（加锁保证线程安全）"""
    ts = f'<span class="log-time">{datetime.now().strftime("%H:%M:%S")}</span> '
    if html.startswith("<div"):
        html = re.sub(r"(<div[^>]*>)", r"\1" + ts, html, count=1)
    else:
        html = ts + html
    with _task_lock:
        _TASK["status_lines"].append(html)


def _task_snapshot_html(extra: str = "") -> str:
    """根据全局任务状态生成当前展示 HTML"""
    with _task_lock:
        completed_stages = list(_TASK["completed_stages"])
        current_stage = _TASK["current_stage"]
        stage_start = _TASK["stage_start"]
        active_serial = _TASK["active_serial"]
        status_lines = list(_TASK["status_lines"])
    return (
        _build_progress_html(completed_stages, current_stage, stage_start, active_serial)
        + "".join(status_lines)
        + extra
    )


def _run_translation_worker(pdf_file, api_key, base_url, model, lang_in, lang_out, output_mode, speed):
    """后台线程：运行 babeldoc 子进程并持续更新全局任务状态。
    该函数不依赖任何 Gradio 请求上下文，因此浏览器刷新页面不会影响它的执行。
    """
    global _running_process
    _error_warn_count: dict[str, int] = {}

    task_id = datetime.now().strftime("%Y%m%d%H%M%S%f")
    task_dir = HISTORY_DIR / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    original_file = str(task_dir / f"original_{os.path.basename(pdf_file)}")
    try:
        shutil.copy2(pdf_file, original_file)
    except Exception:
        original_file = None

    def _handle_log_line(parsed: tuple[str, str, str], raw_stage: str | None) -> None:
        """处理一条解析后的日志：WARNING/ERROR→终端, INFO→web UI"""
        ts, level, msg = parsed
        stage = raw_stage or _detect_stage_from_msg(msg)

        if level in ("WARNING", "ERROR"):
            tag = "⚠️ " if level == "WARNING" else "❌ "
            print(f"{tag}{ts} {msg}", file=_sys.stderr)
            key = msg[:60]
            _error_warn_count[key] = _error_warn_count.get(key, 0) + 1
            return

        # ---- INFO 级别 ----
        if stage:
            with _task_lock:
                completed_stages = _TASK["completed_stages"]
                current_stage = _TASK["current_stage"]
                stage_start = _TASK["stage_start"]
            if stage not in completed_stages and stage != current_stage:
                if current_stage and current_stage not in completed_stages:
                    elapsed = time.time() - stage_start
                    em, es = divmod(int(elapsed), 60)
                    duration = f"({em}m{es}s)" if em > 0 else f"({es}s)"
                    for name, _, label in STAGE_WEIGHTS:
                        if name == current_stage:
                            _task_add_status(
                                '<div class="log-line stage-done">'
                                f"&#10003; {label} 完成 "
                                f'<span class="stage-duration">{duration}</span></div>'
                            )
                            break
                    with _task_lock:
                        _TASK["completed_stages"].append(current_stage)
                new_stage_start = time.time()
                with _task_lock:
                    _TASK["stage_start"] = new_stage_start
                    _TASK["active_serial"] += 1
                    _TASK["current_stage"] = stage
                for name, _, label in STAGE_WEIGHTS:
                    if name == stage:
                        _task_add_status(
                            '<div class="log-line stage-start">'
                            f'<span class="spinner"></span> 正在{label}...</div>'
                        )
                        break

        _maybe_show_progress_info(msg)

    def _maybe_show_progress_info(msg: str) -> None:
        """精选部分 INFO 消息显示到 web UI"""
        show_patterns = [
            (r"start to translate", "&#128640; 开始翻译文档..."),
            (r"start merge results", "&#128300; 合并翻译结果..."),
            (r"finish merge results", "&#10003; 结果合并完成"),
            (r"Translation completed", "&#10003; 翻译段落处理完毕"),
            (r"Peak memory usage", None),  # None = 直接用 msg
            (r"Processing (.+)", None),
            (r"split points determined", None),
            (r"Only one part", "&#128196; 单文件模式，直接翻译"),
        ]
        for pattern, replacement in show_patterns:
            m = re.search(pattern, msg, re.IGNORECASE)
            if m:
                text = replacement if replacement else msg
                _task_add_status(f'<div class="log-line log-info">{text}</div>')
                return

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

    cmd = [
        "babeldoc",
        "--files", pdf_file,
        "--openai",
        "--openai-model", model,
        "--openai-base-url", base_url.rstrip("/") + "/",
        "--openai-api-key", api_key,
        "--lang-in", lang_in,
        "--lang-out", lang_out,
        "--output", output_dir,
        "--report-interval", "1",
        "--qps", str(sp["qps"]),
        "--pool-max-workers", str(sp["pool"]),
    ]
    if sp["no_glossary"]:
        cmd.append("--no-auto-extract-glossary")
    if output_mode == "仅译文 (单语)":
        cmd.append("--no-dual")
    elif output_mode == "仅双语对照":
        cmd.append("--no-mono")

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
        f'速度: {sp["label"]} (QPS={sp["qps"]}, 线程={sp["pool"]}'
        f'{", 跳过术语提取" if sp["no_glossary"] else ""})</div>'
    )
    _task_add_status('<div class="log-separator"></div>')
    _task_add_status(
        '<div class="log-line log-info"><b>&#128640; 翻译启动，请稍候...</b></div>'
    )

    def _finish(extra: str, result_file: str | None = None, status: str = "完成") -> None:
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
                "duration": duration,
                "status": status,
                "original_file": original_file,
                "result_file": result_file,
            }
        )

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        _running_process = process

        log_buffer = ""
        for line in process.stdout:
            if _stop_event.is_set():
                try:
                    process.terminate()
                except Exception:
                    pass
                break

            raw = line.rstrip()
            if not raw:
                continue

            if raw.startswith(" ") or raw.startswith("\t") or not raw.startswith("["):
                log_buffer += " " + raw.strip()
            else:
                if log_buffer:
                    raw_stage = _detect_stage_from_raw(log_buffer)
                    parsed = _parse_log(log_buffer)
                    if parsed:
                        _handle_log_line(parsed, raw_stage)
                    else:
                        print(log_buffer, file=_sys.stderr)
                log_buffer = raw

        if log_buffer:
            raw_stage = _detect_stage_from_raw(log_buffer)
            parsed = _parse_log(log_buffer)
            if parsed:
                _handle_log_line(parsed, raw_stage)

        if _stop_event.is_set():
            _finish(
                '<div class="log-line log-warning" style="font-weight:bold">'
                "&#9209; 翻译已停止</div>",
                status="已停止",
            )
            return

        process.wait()

        if _stop_event.is_set():
            _finish(
                '<div class="log-line log-warning" style="font-weight:bold">'
                "&#9209; 翻译已停止</div>",
                status="已停止",
            )
            return

        if process.returncode != 0:
            _finish(
                '<div class="log-line log-error" style="font-weight:bold">'
                f"&#10060; 翻译失败 (exit code: {process.returncode})</div>",
                status="失败",
            )
            return

        # 标记所有阶段完成
        with _task_lock:
            current_stage = _TASK["current_stage"]
            completed_stages = _TASK["completed_stages"]
            stage_start = _TASK["stage_start"]
            overall_start = _TASK["overall_start"]
        if current_stage and current_stage not in completed_stages:
            elapsed = time.time() - stage_start
            em, es = divmod(int(elapsed), 60)
            duration = f"({em}m{es}s)" if em > 0 else f"({es}s)"
            for name, _, label in STAGE_WEIGHTS:
                if name == current_stage:
                    _task_add_status(
                        '<div class="log-line stage-done">'
                        f"&#10003; {label} 完成 "
                        f'<span class="stage-duration">{duration}</span></div>'
                    )
                    break
        with _task_lock:
            _TASK["current_stage"] = None
            _TASK["completed_stages"] = [name for name, _, _ in STAGE_WEIGHTS]

        output_files = []
        for ext in ["*.pdf", "*.PDF"]:
            output_files.extend(glob.glob(os.path.join(output_dir, ext)))
        if not output_files:
            for root, dirs, files in os.walk(output_dir):
                for f in files:
                    if f.lower().endswith(".pdf"):
                        output_files.append(os.path.join(root, f))
        if original_file:
            output_files = [f for f in output_files if os.path.abspath(f) != os.path.abspath(original_file)]

        if output_files:
            total_elapsed = time.time() - overall_start
            tm, ts = divmod(int(total_elapsed), 60)
            total_duration = f"{tm}m{ts}s" if tm > 0 else f"{ts}s"
            extra = (
                '<div class="log-line" style="color:#4CAF50;font-weight:bold">'
                f"&#10004; 翻译完成！(总用时 {total_duration})</div>"
                '<div class="log-line log-info" style="margin-top:4px">输出文件:</div>'
                + "".join(
                    '<div class="log-line log-info" style="padding-left:12px;font-size:12px">'
                    f"&#128196; {os.path.basename(f)}</div>"
                    for f in output_files
                )
            )
            result_file = None
            for f in output_files:
                if "dual" in f.lower() or "bilingual" in f.lower():
                    result_file = f
                    break
            if not result_file:
                result_file = output_files[0]
            _finish(extra, result_file)
        else:
            _finish(
                '<div class="log-line log-warning" style="font-weight:bold">'
                "&#9888; 未找到输出 PDF 文件，请检查日志。</div>",
                status="失败",
            )

    except FileNotFoundError:
        _finish(
            '<div class="log-line log-error" style="font-weight:bold">'
            "&#10060; 未找到 babeldoc 命令，请确保已正确安装 BabelDOC</div>"
            '<div class="log-line log-plain" style="font-size:12px">'
            "安装命令: pip install babeldoc</div>",
            status="失败",
        )
    except Exception as e:
        _finish(
            '<div class="log-line log-error" style="font-weight:bold">'
            f"&#10060; 错误: {e}</div>",
            status="失败",
        )


def translate_pdf(
    pdf_file,
    api_key,
    base_url,
    model,
    lang_in,
    lang_out,
    output_mode,
    speed,
):
    """启动翻译任务并轮询展示进度。

    实际翻译在后台线程 `_run_translation_worker` 中运行，状态保存在全局
    `_TASK` 字典里。刷新浏览器页面会取消这里的轮询循环，但后台线程不受影响，
    翻译会继续进行；刷新后可通过页面自动或手动重新接上最新进度（见 `resume_progress`）。
    """
    if not pdf_file:
        yield None, '<div class="log-line log-error" style="font-weight:bold">⚠️ 请先上传 PDF 文件</div>', None
        return
    if not api_key:
        yield None, '<div class="log-line log-error" style="font-weight:bold">⚠️ 请输入 DeepSeek API Key</div>', None
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
            output_dir=None,
            task_id=None,
            finished=False,
            extra_html="",
        )

    worker = threading.Thread(
        target=_run_translation_worker,
        args=(pdf_file, api_key, base_url, model, lang_in, lang_out, output_mode, speed),
        daemon=True,
    )
    worker.start()

    yield from resume_progress()


def resume_progress():
    """轮询全局任务状态并 yield 给 UI，直到任务结束。
    可安全被取消（如页面刷新导致的生成器取消）——不会影响后台翻译线程。
    """
    last_len = -1
    while True:
        with _task_lock:
            running = _TASK["running"]
            finished = _TASK["finished"]
            extra_html = _TASK["extra_html"]
            result_file = _TASK["result_file"]
            output_dir = _TASK["output_dir"]
            cur_len = len(_TASK["status_lines"])

        if finished:
            yield result_file, _task_snapshot_html(extra_html), output_dir
            return

        if cur_len != last_len:
            last_len = cur_len
            yield None, _task_snapshot_html(), output_dir

        if not running:
            return

        time.sleep(0.5)


def cleanup_temp(temp_dir):
    """清理临时文件"""
    if temp_dir and os.path.exists(temp_dir):
        try:
            shutil.rmtree(temp_dir)
        except Exception:
            pass


# 创建 Gradio 界面
with gr.Blocks(
    title="BabelDOC 论文翻译 - DeepSeek",
) as demo:
    # 状态变量
    temp_output_dir = gr.State(None)

    # 主题切换（默认跟随系统）
    with gr.Row(elem_classes="theme-toggle-row"):
        theme_toggle_btn = gr.Button("🖥️ 跟随系统", size="sm", scale=0)

    # 标题
    with gr.Row(elem_classes="app-header"):
        gr.Markdown(
            """
            # 📄 BabelDOC 论文翻译
            基于 **DeepSeek** 模型的 PDF 科研论文翻译工具，保留原文排版与公式
            """
        )

    with gr.Tabs():
        # ---------------- Tab 1：翻译工作台 ----------------
        with gr.Tab("🚀 翻译"):
            # 顶部步骤条
            gr.HTML(
                """
                <div class="step-bar">
                    <div class="step-item"><span class="step-num">1</span>上传文件</div>
                    <div class="step-sep"></div>
                    <div class="step-item"><span class="step-num">2</span>配置 API</div>
                    <div class="step-sep"></div>
                    <div class="step-item"><span class="step-num">3</span>语言与速度</div>
                    <div class="step-sep"></div>
                    <div class="step-item"><span class="step-num">4</span>开始翻译</div>
                </div>
                """
            )

            with gr.Column(elem_classes="workflow-col"):
                with gr.Group(elem_classes="step-card"):
                    gr.Markdown("#### ① 上传文件")
                    pdf_input = gr.File(
                        label="上传 PDF 文件",
                        file_types=[".pdf"],
                        file_count="single",
                    )

                with gr.Group(elem_classes="step-card"):
                    gr.Markdown("#### ② DeepSeek 配置")
                    api_key = gr.Textbox(
                        label="DeepSeek API Key",
                        placeholder="sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                        type="password",
                    )
                    with gr.Row():
                        base_url = gr.Textbox(
                            label="API Base URL",
                            value=DEFAULT_DEEPSEEK_BASE_URL,
                            placeholder="https://api.deepseek.com/v1",
                        )
                        model = gr.Textbox(
                            label="模型名称",
                            value=DEFAULT_DEEPSEEK_MODEL,
                            placeholder="deepseek-chat",
                        )
                    with gr.Row():
                        save_config_btn = gr.Button(
                            "💾 保存 API 配置", variant="secondary", size="sm"
                        )
                        config_status = gr.Markdown("", visible=True)

                with gr.Group(elem_classes="step-card"):
                    gr.Markdown("#### ③ 语言与速度")
                    with gr.Row():
                        lang_in = gr.Dropdown(
                            label="源语言",
                            choices=[
                                ("英语", "en"),
                                ("中文", "zh"),
                                ("日语", "ja"),
                                ("法语", "fr"),
                                ("德语", "de"),
                                ("俄语", "ru"),
                                ("西班牙语", "es"),
                                ("韩语", "ko"),
                            ],
                            value="en",
                        )
                        lang_out = gr.Dropdown(
                            label="目标语言",
                            choices=[
                                ("中文", "zh"),
                                ("英语", "en"),
                                ("日语", "ja"),
                                ("法语", "fr"),
                                ("德语", "de"),
                                ("俄语", "ru"),
                                ("西班牙语", "es"),
                                ("韩语", "ko"),
                            ],
                            value="zh",
                        )
                    with gr.Row():
                        output_mode = gr.Radio(
                            label="输出模式",
                            choices=[
                                ("双语对照 + 译文", "both"),
                                ("仅双语对照", "dual_only"),
                                ("仅译文 (单语)", "mono_only"),
                            ],
                            value="both",
                        )
                        speed = gr.Dropdown(
                            label="翻译速度",
                            choices=[
                                ("标准 — QPS=4 线程=4（质量优先）", "标准"),
                                ("快速 — QPS=10 线程=8（推荐）", "快速"),
                                ("极速 — QPS=20 线程=12 跳过术语提取", "极速"),
                            ],
                            value="快速",
                        )

                with gr.Row(elem_classes="action-row"):
                    translate_btn = gr.Button(
                        "🚀 开始翻译", variant="primary", size="lg", scale=3
                    )
                    resume_btn = gr.Button("🔄 恢复进度", variant="secondary", size="lg", scale=1)
                    stop_btn = gr.Button("⏹ 停止", variant="stop", size="lg", scale=1)

                with gr.Group(elem_classes="step-card"):
                    gr.Markdown("#### ④ 翻译日志与进度")
                    log_output = gr.HTML(
                        value="",
                        elem_classes="log-panel",
                    )
                    with gr.Row():
                        result_download = gr.File(
                            label="📥 下载翻译结果",
                            file_count="single",
                        )
                        clear_btn = gr.Button("🗑️ 清空", variant="secondary", scale=0)

        # ---------------- Tab 2：历史记录 ----------------
        with gr.Tab("🗂️ 历史记录"):
            with gr.Group(elem_classes="step-card"):
                gr.Markdown("#### 历史翻译任务")
                history_table = gr.Dataframe(
                    headers=["文件名", "时间", "语言", "耗时", "状态"],
                    datatype=["str", "str", "str", "str", "str"],
                    interactive=False,
                    wrap=True,
                )
                with gr.Row():
                    history_select = gr.Dropdown(
                        label="选择历史任务",
                        choices=[],
                        value=None,
                        scale=3,
                    )
                    history_refresh_btn = gr.Button("🔄 刷新", scale=1)
                with gr.Row():
                    history_download_original_btn = gr.Button("📥 下载原文", scale=1)
                    history_download_result_btn = gr.Button("📥 下载译文", scale=1)
                    history_delete_btn = gr.Button("🗑️ 删除", variant="stop", scale=1)
                with gr.Row():
                    history_original_file = gr.File(label="原始文档", scale=1)
                    history_result_file = gr.File(label="翻译后文档", scale=1)

    # 事件绑定
    # 注意：cancels 需要指向真正承载长耗时任务（translate_pdf/resume_progress）的
    # 事件对象本身，因此按钮 loading 态的切换放在 .then() 链的前后，
    # 而 translate_event/resume_event 变量始终绑定在核心任务事件上。
    translate_btn.click(
        fn=lambda: gr.update(value="⏳ 翻译中...", interactive=False),
        inputs=[],
        outputs=[translate_btn],
    )
    translate_event = translate_btn.click(
        fn=translate_pdf,
        inputs=[
            pdf_input,
            api_key,
            base_url,
            model,
            lang_in,
            lang_out,
            output_mode,
            speed,
        ],
        outputs=[result_download, log_output, temp_output_dir],
        api_name="translate",
    )
    translate_event.then(
        fn=lambda k, u, m: (
            save_config(k, u, m),
            "✅ 配置已自动保存",
        )[1],
        inputs=[api_key, base_url, model],
        outputs=[config_status],
    )
    translate_event.then(
        fn=lambda: gr.update(value="🚀 开始翻译", interactive=True),
        inputs=[],
        outputs=[translate_btn],
    )

    # 恢复进度：重新接上后台正在运行（或已结束）的任务状态
    # 用于翻译过程中刷新页面后，手动点击接回最新进度
    resume_btn.click(
        fn=lambda: gr.update(value="⏳ 翻译中...", interactive=False),
        inputs=[],
        outputs=[translate_btn],
    )
    resume_event = resume_btn.click(
        fn=resume_progress,
        inputs=[],
        outputs=[result_download, log_output, temp_output_dir],
    )
    resume_event.then(
        fn=lambda: gr.update(value="🚀 开始翻译", interactive=True),
        inputs=[],
        outputs=[translate_btn],
    )

    # 停止按钮：杀死子进程 + 取消 Gradio 事件（补充取消恢复进度的轮询）
    stop_btn.click(
        fn=lambda: (request_stop(), "⏹ 已请求停止")[1],
        inputs=[],
        outputs=[config_status],
        cancels=[translate_event, resume_event],
    ).then(
        fn=lambda: gr.update(value="🚀 开始翻译", interactive=True),
        inputs=[],
        outputs=[translate_btn],
    )

    def handle_save_config(api_key, base_url, model):
        save_config(api_key, base_url, model)
        return "✅ API 配置已保存到本地，下次启动自动加载"

    save_config_btn.click(
        fn=handle_save_config,
        inputs=[api_key, base_url, model],
        outputs=[config_status],
    )

    def clear_all(temp_dir):
        cleanup_temp(temp_dir)
        return None, None, None, ""

    clear_btn.click(
        fn=clear_all,
        inputs=[temp_output_dir],
        outputs=[pdf_input, result_download, temp_output_dir, log_output],
    )

    # ---- 历史记录事件 ----
    history_refresh_btn.click(
        fn=refresh_history,
        inputs=[],
        outputs=[history_table, history_select],
    )

    # 翻译/恢复进度结束后，顺带刷新历史记录列表
    translate_event.then(
        fn=refresh_history,
        inputs=[],
        outputs=[history_table, history_select],
    )
    resume_event.then(
        fn=refresh_history,
        inputs=[],
        outputs=[history_table, history_select],
    )

    history_download_original_btn.click(
        fn=lambda task_id: download_history_file(task_id, "original"),
        inputs=[history_select],
        outputs=[history_original_file],
    )
    history_download_result_btn.click(
        fn=lambda task_id: download_history_file(task_id, "result"),
        inputs=[history_select],
        outputs=[history_result_file],
    )
    history_delete_btn.click(
        fn=delete_history_selected,
        inputs=[history_select],
        outputs=[history_table, history_select, history_original_file, history_result_file],
    )

    # 启动时加载配置
    def load_config_ui():
        cfg = load_config()
        return (
            cfg.get("api_key", ""),
            cfg.get("base_url", DEFAULT_DEEPSEEK_BASE_URL),
            cfg.get("model", DEFAULT_DEEPSEEK_MODEL),
        )

    demo.load(
        fn=load_config_ui,
        inputs=[],
        outputs=[api_key, base_url, model],
    )

    demo.load(
        fn=refresh_history,
        inputs=[],
        outputs=[history_table, history_select],
    )

    # 主题初始化：读取本地存储的偏好（默认跟随系统）
    # Gradio 自身的深色样式以 <body> 是否带 .dark 类为准，
    # 因此这里复用同一套机制，保证组件文字/背景色都能正确联动。
    demo.load(
        fn=None,
        inputs=[],
        outputs=[],
        js="""
        () => {
            const labels = {system: '🖥️ 跟随系统', light: '☀️ 亮色', dark: '🌙 暗色'};
            const saved = localStorage.getItem('babeldoc-theme') || 'system';
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            const shouldBeDark = saved === 'dark' || (saved === 'system' && prefersDark);
            document.documentElement.classList.toggle('dark', shouldBeDark);
            document.body.classList.toggle('dark', shouldBeDark);
            const btn = document.querySelector('.theme-toggle-row button');
            if (btn) btn.textContent = labels[saved];
        }
        """,
    )

    # 主题切换按钮：跟随系统 → 亮色 → 暗色 → 循环
    theme_toggle_btn.click(
        fn=None,
        inputs=[],
        outputs=[],
        js="""
        () => {
            const order = ['system', 'light', 'dark'];
            const labels = {system: '🖥️ 跟随系统', light: '☀️ 亮色', dark: '🌙 暗色'};
            const current = localStorage.getItem('babeldoc-theme') || 'system';
            const next = order[(order.indexOf(current) + 1) % order.length];
            localStorage.setItem('babeldoc-theme', next);
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            const shouldBeDark = next === 'dark' || (next === 'system' && prefersDark);
            document.documentElement.classList.toggle('dark', shouldBeDark);
            document.body.classList.toggle('dark', shouldBeDark);
            const btn = document.querySelector('.theme-toggle-row button');
            if (btn) btn.textContent = labels[next];
        }
        """,
    )

    # 关闭后清理临时文件
    demo.unload(cleanup_temp)

    # 示例
    gr.Markdown(
        """
        ---
        ### 💡 使用说明
        1. **安装 BabelDOC**: `pip install babeldoc`
        2. **获取 API Key**: 在 [DeepSeek 平台](https://platform.deepseek.com/) 注册获取
        3. **上传 PDF**: 选择需要翻译的英文论文
        4. **配置模型**: 默认使用 `deepseek-chat`，可按需修改
        5. **开始翻译**: 点击按钮等待完成，结果可直接下载
        """
    )


if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=7865,
        show_error=True,
        theme=gr.themes.Soft(),
        css="""
        /* ===== 主题变量：亮色（默认） ===== */
        :root {
            --log-bg: #1a1a2e;
            --log-border: #333;
            --log-fg: #d4d4d8;
            --log-muted: #888;
            --brand: #6C5CE7;
            --brand-light: #A29BFE;
            --card-bg: #ffffff;
            --card-border: #ECECF4;
            --card-shadow: 0 2px 10px rgba(30, 30, 60, 0.06);
            --body-bg: #f7f7fb;
            --text-main: #333;
            --text-muted: #888;
        }

        /* ===== 主题变量：暗色 =====
           html/body 同时加 .dark，既让自定义变量在 html 上生效（用于铺满两侧背景），
           也复用 Gradio 内置组件依赖的 body.dark 深色样式。 */
        html.dark, body.dark {
            --log-bg: #101018;
            --log-border: #34343f;
            --log-fg: #d4d4d8;
            --log-muted: #9a9aa8;
            --brand: #A29BFE;
            --brand-light: #6C5CE7;
            --card-bg: #23232f;
            --card-border: #34343f;
            --card-shadow: 0 2px 10px rgba(0, 0, 0, 0.35);
            --body-bg: #16161e;
            --text-main: #e4e4ec;
            --text-muted: #9a9aa8;
        }

        html, body { background: var(--body-bg) !important; }
        .gradio-container { background: var(--body-bg) !important; max-width: 880px !important; margin: 0 auto !important; }

        .app-header { text-align: center; padding: 8px 0 4px; }
        .app-header h1 { font-size: 1.8rem; margin-bottom: 0; }
        .app-header p { margin-top: 4px; color: var(--text-muted); }
        footer { display: none !important; }

        /* ===== 主题切换按钮 ===== */
        .theme-toggle-row { justify-content: flex-end !important; margin-bottom: 4px; }
        .theme-toggle-row button {
            border-radius: 999px !important;
            font-size: 12px !important;
            padding: 4px 12px !important;
        }

        /* ===== 步骤条 ===== */
        .step-bar {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 4px;
            margin: 4px 0 18px;
            padding: 12px 8px;
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            box-shadow: var(--card-shadow);
        }
        .step-item {
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 13px;
            color: var(--text-main);
            font-weight: 500;
        }
        .step-num {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 20px; height: 20px;
            border-radius: 50%;
            background: var(--brand);
            color: #fff;
            font-size: 12px;
            font-weight: 600;
        }
        .step-sep {
            width: 28px;
            height: 1px;
            background: var(--card-border);
        }

        /* ===== 卡片区块 ===== */
        .step-card {
            border-radius: 14px !important;
            border: 1px solid var(--card-border) !important;
            box-shadow: var(--card-shadow) !important;
            padding: 16px !important;
            margin-bottom: 14px !important;
            background: var(--card-bg) !important;
        }
        .step-card h4, .step-card .prose h4 {
            margin-top: 0 !important;
            margin-bottom: 12px !important;
            font-size: 15px !important;
            color: var(--text-main) !important;
        }
        .workflow-col { gap: 4px !important; }

        .action-row { margin: 4px 0 14px !important; }
        .action-row button { border-radius: 10px !important; }

        /* ===== 日志面板 ===== */
        .log-panel {
            font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace !important;
            font-size: 12px !important;
            line-height: 1.5 !important;
            height: 520px !important;
            max-height: 520px;
            overflow-y: auto !important;
            background: var(--log-bg) !important;
            border: 1px solid var(--log-border) !important;
            border-radius: 8px !important;
            padding: 10px 12px !important;
            color: var(--log-fg);
            flex-shrink: 0;
        }

        .log-line {
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            margin: 0;
            line-height: 1.6;
        }
        .log-line b { font-weight: 600; }

        .log-time {
            color: var(--log-muted);
            font-size: 11px;
            font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
        }

        .log-error  { color: #F44336; }
        .log-warning { color: #FFB74D; }
        .log-info   { color: #E0E0E0; }
        .log-plain  { color: #999; }

        .log-separator {
            height: 0;
            border-bottom: 1px solid #333;
            margin: 4px 0;
        }

        /* 阶段状态行 */
        .stage-done  { color: #4CAF50; }
        .stage-start { color: #4FC3F7; }
        .stage-duration { color: #888; font-size: 11px; }

        /* ===== 动画 ===== */
        /* CSS Spinner */
        .spinner {
            display: inline-block;
            width: 12px; height: 12px;
            border: 2px solid #4FC3F7;
            border-top-color: transparent;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            vertical-align: middle;
            margin-right: 2px;
        }
        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        /* 活跃指示点 */
        .alive-dot {
            display: inline-block;
            width: 8px; height: 8px;
            background: #4CAF50;
            border-radius: 50%;
            animation: pulse-dot 1s ease-in-out infinite;
            vertical-align: middle;
            margin-right: 4px;
        }
        @keyframes pulse-dot {
            0%, 100% { opacity: 1; transform: scale(1); }
            50%      { opacity: 0.4; transform: scale(0.7); }
        }

        /* 已用时间 */
        .elapsed {
            color: #888;
            font-size: 11px;
            font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
        }

        /* ===== 进度区域 ===== */
        .progress-area {
            margin-bottom: 8px;
            padding-bottom: 8px;
            border-bottom: 1px solid #333;
        }
        .progress-text {
            font-size: 12px;
            display: block;
            margin-bottom: 4px;
        }
        .progress-bar {
            width: 100%;
            height: 16px;
            background: #222;
            border-radius: 8px;
            overflow: hidden;
            display: flex;
            border: 1px solid #444;
        }
        .progress-bar > div {
            height: 100%;
            border-right: 2px solid #1a1a2e;
            transition: background 0.3s;
        }

        /* 进度条分段颜色 */
        .pg-done    { background: #4CAF50; }
        .pg-current { background: #4FC3F7; animation: pulse-current 1.2s ease-in-out infinite; }
        .pg-pending { background: #3a3a4a; }

        @keyframes pulse-current {
            0%, 100% { opacity: 1; }
            50%      { opacity: 0.6; }
        }

        .progress-bar > div[title] { cursor: help; }
        """,
    )
