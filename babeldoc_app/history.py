"""Persistent task history, result files and history callbacks."""

import html
import json
import os
import shutil
import threading

import gradio as gr

from .settings import CONFIG_DIR

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


def _status_mark(status: str) -> str:
    """给历史状态加彩色 emoji 标记（Dataframe 不支持按单元格上色）"""
    if "完成" in status:
        return f"✅ {status}"
    if "失败" in status:
        return f"❌ {status}"
    if "停止" in status:
        return f"⏹️ {status}"
    return status


def _is_downloadable_result_pdf(path: str | None) -> bool:
    """仅保留用户可下载的最终译文，排除 BabelDOC 调试解压 PDF。"""
    if not path or not os.path.isfile(path):
        return False
    normalized = path.lower()
    return normalized.endswith(".pdf") and not normalized.endswith(".decompressed.pdf")


def _history_choices(records: list[dict]) -> list[tuple[str, str]]:
    """生成 Dropdown 的 (显示名, task_id) 选项列表"""
    choices = []
    for r in records:
        model = r.get("model", "")
        label = (
            f"{r.get('filename', '?')} | {r.get('time', '')} | {model or r.get('lang', '')} | "
            f"{_status_mark(r.get('status', ''))}"
        )
        choices.append((label, r.get("task_id")))
    return choices


def _history_table(records: list[dict]) -> list[list[str]]:
    """生成 Dataframe 展示用的表格数据"""
    return [
        [
            r.get("filename", ""),
            r.get("time", ""),
            r.get("lang", ""),
            r.get("model", ""),
            r.get("settings", ""),
            r.get("duration", ""),
            _status_mark(r.get("status", "")),
        ]
        for r in records
    ]


def _get_history_record(task_id: str | None) -> dict | None:
    if not task_id:
        return None
    return next((r for r in _load_history() if r.get("task_id") == task_id), None)


def _history_detail_html(record: dict | None) -> str:
    """显示当前选中任务的概要，避免用户在下拉项中反复辨认信息。"""
    if not record:
        return (
            '<div class="history-detail history-detail-empty">'
            "从上方表格点击一条任务，查看文件可用性并执行下载或删除操作。"
            "</div>"
        )
    original_ready = bool(
        record.get("original_file") and os.path.isfile(record["original_file"])
    )
    result_count = len(
        [
            f
            for f in (record.get("result_files") or [])
            if _is_downloadable_result_pdf(f)
        ]
    )
    if not result_count and _is_downloadable_result_pdf(record.get("result_file")):
        result_count = 1
    fields = [
        ("文件", record.get("filename", "—")),
        ("状态", _status_mark(record.get("status", "—"))),
        ("时间", record.get("time", "—")),
        ("语言", record.get("lang", "—")),
        ("模型", record.get("model", "—")),
        ("设置", record.get("settings", "—")),
        ("耗时", record.get("duration", "—")),
        (
            "文件",
            f"原文{'可用' if original_ready else '缺失'} · 译文 {result_count} 个可用",
        ),
    ]
    items = "".join(
        f"<div><span>{html.escape(label)}</span><strong>{html.escape(str(value))}</strong></div>"
        for label, value in fields
    )
    return f'<div class="history-detail">{items}</div>'


def show_history_files(task_id: str):
    """选中历史任务后，自动在下载区展示原文与全部译文文件（不触发浏览器下载）。"""
    record = _get_history_record(task_id)
    try:
        original = download_history_file(task_id, "original")
    except gr.Error:
        original = None
    try:
        results = download_history_file(task_id, "result")
    except gr.Error:
        results = None
    if isinstance(results, str):
        results = [results]
    return (
        original,
        results,
        _history_detail_html(record),
        gr.update(value="🗑️ 删除任务", interactive=bool(task_id)),
        None,
    )


def select_history_row(table_data: list[list[str]], evt: gr.SelectData):
    """表格行点击直接选中任务。

    以事件携带的行内容匹配记录，避免筛选或排序后使用视觉行号取错任务。
    """
    row_value = evt.row_value
    if not row_value:
        row_index = evt.index[0] if isinstance(evt.index, tuple) else evt.index
        row_value = (
            table_data[row_index]
            if isinstance(row_index, int) and 0 <= row_index < len(table_data)
            else None
        )
    records = _load_history()
    if not row_value:
        return (
            gr.update(),
            None,
            None,
            _history_detail_html(None),
            gr.update(value="🗑️ 删除任务", interactive=False),
            None,
        )
    filename, record_time = str(row_value[0]), str(row_value[1])
    model = str(row_value[3]) if len(row_value) > 3 else ""
    record = next(
        (
            r
            for r in records
            if r.get("filename", "") == filename
            and r.get("time", "") == record_time
            and r.get("model", "") == model
        ),
        None,
    )
    if not record:
        return (
            gr.update(),
            None,
            None,
            _history_detail_html(None),
            gr.update(value="🗑️ 删除任务", interactive=False),
            None,
        )
    task_id = record.get("task_id")
    original, results, detail, delete_btn_update, delete_state = show_history_files(
        task_id
    )
    return (
        gr.update(value=task_id),
        original,
        results,
        detail,
        delete_btn_update,
        delete_state,
    )


def refresh_history(selected_task_id: str | None = None):
    """刷新历史记录，并在任务仍存在时保留当前选择。"""
    records = _load_history()
    valid_ids = {r.get("task_id") for r in records}
    selected_task_id = selected_task_id if selected_task_id in valid_ids else None
    return (
        _history_table(records),
        gr.update(choices=_history_choices(records), value=selected_task_id),
        _history_detail_html(_get_history_record(selected_task_id)),
        gr.update(value="🗑️ 删除任务", interactive=bool(selected_task_id)),
        None,
    )


def download_history_file(task_id: str, kind: str):
    """根据选中的 task_id 返回原文或译文文件。

    kind=result 时返回全部输出文件（dual + mono 等）列表，缺失的自动过滤。
    """
    if not task_id:
        raise gr.Error("请先在「选择历史任务」下拉框中选择一个任务")
    records = _load_history()
    for r in records:
        if r.get("task_id") == task_id:
            if kind == "original":
                path = r.get("original_file")
                if path and os.path.exists(path):
                    return path
                raise gr.Error("原文文件不存在或已被清理")
            files = [
                f
                for f in (r.get("result_files") or [])
                if _is_downloadable_result_pdf(f)
            ]
            if not files:
                path = r.get("result_file")
                if _is_downloadable_result_pdf(path):
                    return path
                raise gr.Error("文件不存在或已被清理")
            return files
    raise gr.Error("未找到该任务的记录")


def delete_history_selected(task_id: str):
    """删除选中的历史记录，并刷新表格；未选中时不改变界面。"""
    if not task_id:
        return (
            gr.update(),
            gr.update(),
            gr.update(),
            gr.update(),
            gr.update(),
        )
    _delete_history_record(task_id)
    records = _load_history()
    return (
        _history_table(records),
        gr.update(choices=_history_choices(records), value=None),
        None,
        None,
        _history_detail_html(None),
    )


def click_history_delete(task_id: str | None, armed_task_id: str | None):
    """删除按钮两段式确认：第一次进入待确认状态，第二次执行删除。"""
    reset_button = gr.update(value="🗑️ 删除任务", interactive=False)
    keep_ui = (gr.update(), gr.update(), gr.update(), gr.update(), gr.update())
    if not task_id:
        return reset_button, None, *keep_ui
    if armed_task_id != task_id:
        return (
            gr.update(value="⚠️ 再次点击确认删除", interactive=True),
            task_id,
            *keep_ui,
        )
    table, select, original, results, detail = delete_history_selected(task_id)
    return reset_button, None, table, select, original, results, detail
