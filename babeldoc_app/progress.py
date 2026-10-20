"""Native progress events and task log rendering."""

import html
import re
import time
from datetime import datetime

from .state import (
    _TASK,
    _task_lock,
)

STAGE_WEIGHTS: list[tuple[str, float, str]] = [
    ("Parse PDF and Create Intermediate Representation", 14.12, "创建文档中间表示"),
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
    ("Subset font", 0.92, "字体子集化"),
    ("Save PDF", 6.34, "保存 PDF"),
]
_TOTAL_WEIGHT = sum(w for _, w, _ in STAGE_WEIGHTS)
_STAGE_INDEX: dict[str, int] = {name: i for i, (name, _, _) in enumerate(STAGE_WEIGHTS)}
_ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-_][0-?]*[ -/]*[@-~]|\[[0-?]*[ -/]*[@-~])")


def _canonical_stage(stage: str | None) -> str | None:
    """将 BabelDOC 进度事件中的阶段名称映射为界面使用的标准名称。"""
    if not stage:
        return None
    for name, _, _ in STAGE_WEIGHTS:
        if stage == name or stage.startswith(name + " "):
            return name
    return None


def _record_native_progress(raw: str) -> bool:
    """提取 --debug 输出的 BabelDOC 进度事件，优先使用其精确 overall_progress。"""
    clean = _ANSI_ESCAPE_RE.sub("", raw)
    overall_match = re.search(
        r"['\"]overall_progress['\"]\s*:\s*([0-9]+(?:\.[0-9]+)?)", clean
    )
    if not overall_match:
        return False

    progress = min(100.0, max(0.0, float(overall_match.group(1))))
    event_match = re.search(r"['\"]type['\"]\s*:\s*['\"]([^'\"]+)", clean)
    stage_match = re.search(r"['\"]stage['\"]\s*:\s*['\"]([^'\"]+)", clean)
    current_match = re.search(r"['\"]stage_current['\"]\s*:\s*(\d+)", clean)
    total_match = re.search(r"['\"]stage_total['\"]\s*:\s*(\d+)", clean)
    stage = _canonical_stage(stage_match.group(1) if stage_match else None)
    event_type = event_match.group(1) if event_match else "progress_update"

    with _task_lock:
        _TASK["progress_is_native"] = True
        # 同一文档分片的旧事件可能迟到，进度绝不允许倒退。
        _TASK["progress_percent"] = max(_TASK["progress_percent"], progress)
        if stage:
            _TASK["current_stage"] = stage
            if current_match:
                _TASK["stage_current"] = int(current_match.group(1))
            if total_match:
                _TASK["stage_total"] = int(total_match.group(1))
            if event_type == "progress_end" and stage not in _TASK["completed_stages"]:
                _TASK["completed_stages"].append(stage)
    return True


def _record_native_progress_event(event: dict) -> None:
    """直接消费 async_translate 的原生事件，无需开启 BabelDOC 调试模式。"""
    event_type = event.get("type", "")
    if event_type not in {"progress_start", "progress_update", "progress_end"}:
        return
    stage = _canonical_stage(event.get("stage"))
    progress = event.get("overall_progress", 0.0)
    try:
        progress = min(100.0, max(0.0, float(progress)))
    except (TypeError, ValueError):
        progress = 0.0

    previous_stage = None
    stage_start = 0.0
    with _task_lock:
        _TASK["last_activity"] = time.time()
        previous_stage = _TASK["current_stage"]
        stage_start = _TASK["stage_start"]
        _TASK["progress_is_native"] = True
        _TASK["progress_percent"] = max(_TASK["progress_percent"], progress)
        if stage:
            _TASK["current_stage"] = stage
            _TASK["stage_current"] = event.get("stage_current")
            _TASK["stage_total"] = event.get("stage_total")
            if event_type == "progress_end" and stage not in _TASK["completed_stages"]:
                _TASK["completed_stages"].append(stage)
            if stage != previous_stage:
                _TASK["stage_start"] = time.time()

    if stage and stage != previous_stage:
        label = next(
            (label for name, _, label in STAGE_WEIGHTS if name == stage), stage
        )
        _task_add_status(
            f'<div class="log-line stage-start" data-progress-stage="{html.escape(stage, quote=True)}">'
            f'<span class="spinner"></span> 正在{label}...</div>'
        )
    if stage and event_type == "progress_end":
        _complete_stage_status(stage, max(0.0, time.time() - stage_start))


def _fallback_progress(completed_stages: list[str], current_stage: str | None) -> float:
    """原生进度事件不可用时的保守阶段估算，避免将未完成阶段显示为已完成。"""
    done = sum(weight for name, weight, _ in STAGE_WEIGHTS if name in completed_stages)
    current_weight = next(
        (weight for name, weight, _ in STAGE_WEIGHTS if name == current_stage), 0
    )
    return min(99.0, (done + current_weight * 0.02) / _TOTAL_WEIGHT * 100)


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
        (
            "Parse PDF and Create Intermediate Representation",
            r"Parse PDF and Create Intermediate Representation|创建.*中间表示|intermediate representation",
        ),
        ("DetectScannedFile", r"DetectScannedFile|扫描件检测"),
        (
            "Parse Page Layout",
            r"Parse Page Layout|页面布局|Clustered into|drawing boxes|Annotated images",
        ),
        ("Parse Table", r"Parse Table|表格解析"),
        ("Parse Paragraphs", r"Parse Paragraphs|段落解析"),
        (
            "Parse Formulas and Styles",
            r"Parse Formulas and Styles|公式.*样式|样式.*公式",
        ),
        (
            "Automatic Term Extraction",
            r"Automatic Term Extraction|terms? extract|术语提取",
        ),
        (
            "Translate Paragraphs",
            r"Translate Paragraphs|paragraphs? translat|il_translator|段落翻译|LLM translat",
        ),
        ("Typesetting", r"Typesetting|排版"),
        ("Add Fonts", r"Add Fonts|Font (mapper|subsetting)|字体|fontmap"),
        (
            "Generate drawing instructions",
            r"Generate drawing|绘图指令|PDF save|PDF.*subsetting",
        ),
        ("Subset font", r"Subset font|字体子集"),
        ("Save PDF", r"Save PDF|保存 PDF"),
    ]
    for stage_name, pattern in patterns:
        if re.search(pattern, msg, re.IGNORECASE):
            return stage_name
    return None


def _detect_stage_from_raw(raw: str) -> str | None:
    """从原始（未解析）日志行检测阶段 — 利用模块路径中的阶段信息"""
    patterns = [
        (
            "Parse PDF and Create Intermediate Representation",
            r"create_intermediate|pdf.*intermediate",
        ),
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
        ("Subset font", r"subset_font"),
        ("Save PDF", r"save_pdf"),
    ]
    for stage_name, pattern in patterns:
        if re.search(pattern, raw, re.IGNORECASE):
            return stage_name
    return None


# ---- 进度条（阶段 + 服务端计时器 + spinner）---- #
def _build_progress_html(
    completed_stages: list[str],
    current_stage: str | None,
    start_time: float,
    active_serial: int = 0,
    progress_percent: float = 0.0,
    progress_is_native: bool = False,
    stage_current: int | None = None,
    stage_total: int | None = None,
) -> str:
    """构建完整宽度的进度条；原生 overall_progress 可用时直接显示精确值。"""
    if not current_stage and not completed_stages:
        return ""

    stage_badges: list[str] = []
    for name, weight, label in STAGE_WEIGHTS:
        if name in completed_stages:
            cls = "done"
        elif name == current_stage:
            cls = "current"
        else:
            cls = "pending"
        stage_badges.append(f'<span class="progress-stage {cls}">{label}</span>')

    if len(set(completed_stages)) == len(STAGE_WEIGHTS):
        progress = 100.0
    else:
        progress = min(
            100.0,
            max(
                0.0,
                progress_percent
                if progress_is_native
                else _fallback_progress(completed_stages, current_stage),
            ),
        )

    current_label = ""
    for name, _, label in STAGE_WEIGHTS:
        if name == current_stage:
            current_label = label
            break

    # 活跃脉冲点：有 current_stage 时显示
    active_dot = '<span class="alive-dot"></span> ' if current_stage else ""

    # Gradio 通过 innerHTML 更新 gr.HTML，不会执行其中的 script 标签。
    # 计时值由 resume_progress 的服务端心跳每秒重新渲染。
    elapsed = max(0, int(time.time() - start_time))
    minutes, seconds = divmod(elapsed, 60)
    elapsed_text = f"{minutes}m{seconds}s" if minutes else f"{seconds}s"
    timer_html = f'<span class="elapsed">本阶段 {elapsed_text}</span>'
    item_progress = (
        f" · {stage_current}/{stage_total} 项"
        if stage_current is not None and stage_total is not None and stage_total > 0
        else ""
    )
    source_text = (
        "实际任务进度" if progress_is_native else "阶段进度（等待原生进度事件）"
    )

    return (
        '<div class="progress-area">'
        '<div class="progress-head">'
        f'<span class="progress-text">'
        f"{active_dot}"
        f'<span class="spinner"></span> '
        f"<b>{current_label or '正在初始化'}</b>{item_progress} "
        f"{timer_html}"
        f'</span><span class="progress-value">{progress:.1f}%</span></div>'
        f'<div class="progress-track"><div class="progress-fill" style="width:{progress:.3f}%"></div></div>'
        f'<div class="progress-source">{source_text}</div>'
        f'<div class="progress-stages">{"".join(stage_badges)}</div>' + "</div>"
    )


def _task_add_status(html: str) -> None:
    """向全局任务状态追加一条日志（加锁保证线程安全）"""
    ts = f'<span class="log-time">{datetime.now().strftime("%H:%M:%S")}</span> '
    # 分隔线不能承载文字；向其中注入时间会导致高度为 0 的元素发生视觉错位。
    if "log-separator" in html:
        pass
    elif html.startswith("<div"):
        html = re.sub(r"(<div[^>]*>)", r"\1" + ts, html, count=1)
    else:
        html = ts + html
    with _task_lock:
        _TASK["status_lines"].append(html)


def _complete_stage_status(stage: str, elapsed_seconds: float) -> None:
    """将该阶段原先的加载日志原位替换为完成状态，避免遗留转圈动画。"""
    label = next((label for name, _, label in STAGE_WEIGHTS if name == stage), stage)
    marker = f'data-progress-stage="{html.escape(stage, quote=True)}"'
    minutes, seconds = divmod(int(elapsed_seconds), 60)
    duration = f"{minutes}m{seconds}s" if minutes else f"{seconds}s"
    replacement_done = False
    with _task_lock:
        for index in range(len(_TASK["status_lines"]) - 1, -1, -1):
            line = _TASK["status_lines"][index]
            if marker not in line:
                continue
            timestamp = re.search(r'<span class="log-time">.*?</span>\s*', line)
            prefix = timestamp.group(0) if timestamp else ""
            _TASK["status_lines"][index] = (
                f'<div class="log-line stage-done" {marker}>'
                f"{prefix}&#10003; {label} 完成 "
                f'<span class="stage-duration">({duration})</span></div>'
            )
            replacement_done = True
            break
    if not replacement_done:
        _task_add_status(
            '<div class="log-line stage-done">'
            f'&#10003; {label} 完成 <span class="stage-duration">({duration})</span></div>'
        )


def _task_snapshot_html(extra: str = "") -> str:
    """根据全局任务状态生成当前展示 HTML"""
    with _task_lock:
        completed_stages = list(_TASK["completed_stages"])
        current_stage = _TASK["current_stage"]
        stage_start = _TASK["stage_start"]
        active_serial = _TASK["active_serial"]
        progress_percent = _TASK["progress_percent"]
        progress_is_native = _TASK["progress_is_native"]
        stage_current = _TASK["stage_current"]
        stage_total = _TASK["stage_total"]
        status_lines = list(_TASK["status_lines"])
        last_activity = _TASK["last_activity"]
        warning_count = _TASK["warning_count"]
        last_warning = _TASK["last_warning"]
    live_status = ""
    if current_stage and last_activity:
        live_time = '<span class="log-time log-time-live">实时</span> '
        idle_seconds = max(0, int(time.time() - last_activity))
        live_status = (
            '<div class="log-line log-info" style="font-size:12px">'
            f"{live_time}&#128994; 子进程运行中 · 最近输出 {idle_seconds}s 前"
        )
        if warning_count:
            live_status += f" · 已发生 {warning_count} 次警告/降级重试"
        live_status += "</div>"
        if last_warning:
            live_status += (
                '<div class="log-line log-warning" style="font-size:12px">'
                f"{live_time}最近警告: " + html.escape(last_warning[:240]) + "</div>"
            )
    return (
        _build_progress_html(
            completed_stages,
            current_stage,
            stage_start,
            active_serial,
            progress_percent,
            progress_is_native,
            stage_current,
            stage_total,
        )
        + "".join(status_lines)
        + live_status
        + extra
    )
