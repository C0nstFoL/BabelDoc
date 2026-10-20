"""Shared task state, locking and cancellation signals."""

import os
import signal
import subprocess
import threading

# ---- 停止机制 ---- #
_stop_event = threading.Event()
_running_process: subprocess.Popen | None = None

# ---- 后台任务全局状态 ----
# 翻译在独立线程中运行，状态写入这个全局字典，
# 这样即使用户刷新页面（Gradio 请求的生成器被取消），
# 后台任务也不受影响，刷新后重新查看即可接上最新状态。
_TASK: dict = {
    "running": False,  # 是否有任务在跑
    "status_lines": [],  # 状态日志（HTML 片段列表）
    "completed_stages": [],  # 已完成阶段
    "current_stage": None,  # 当前阶段
    "stage_start": 0.0,
    "overall_start": 0.0,
    "active_serial": 0,
    "result_file": None,  # 完成后的主结果文件路径（优先 dual）
    "result_files": None,  # 完成后的全部输出文件列表（dual + mono 等）
    "output_dir": None,  # 本次任务的临时输出目录
    "task_id": None,  # 本次任务的历史记录 ID
    "finished": False,  # 任务是否已结束（成功/失败/停止）
    "extra_html": "",  # 结束时追加的提示 HTML
    "last_activity": 0.0,  # 最近一次收到 BabelDOC 输出的时间
    "warning_count": 0,  # BabelDOC 警告/降级重试次数
    "last_warning": "",  # 最近一条警告，供长任务诊断
    "progress_percent": 0.0,  # BabelDOC 原生 overall_progress；不可用时退回阶段进度
    "progress_is_native": False,
    "stage_current": None,  # 当前原生阶段已处理的项目数
    "stage_total": None,  # 当前原生阶段项目总数
}
_task_lock = threading.Lock()


def _signal_translation_process(proc, sig):
    """所有翻译/OCR 子进程共享独立进程组，避免留下阻塞线程或 OCR 孤儿。"""
    try:
        os.killpg(proc.pid, sig)
    except ProcessLookupError:
        pass


def request_stop():
    """仅发送停止信号，不在 UI 回调中等待进程退出。"""
    with _task_lock:
        if not _TASK["running"]:
            return
        _stop_event.set()
        _TASK["extra_html"] = (
            '<div class="log-line log-warning">⏹ 正在停止翻译...</div>'
        )
        proc = _running_process
    if proc is not None:
        _signal_translation_process(proc, signal.SIGTERM)


def _reset_stop():
    """仅在旧任务完全退出后重置停止状态。"""
    _stop_event.clear()
    global _running_process
    _running_process = None
