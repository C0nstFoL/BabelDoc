"""Ui translation events."""

import gradio as gr

from ..preflight import file_info_panel
from ..state import (
    _TASK,
    _task_lock,
    request_stop,
)
from ..tasks import (
    resume_progress,
    translate_pdf,
)
from .components import Components


def clear_all(temp_dir):
    with _task_lock:
        # 「清空」仅作用于日志面板，结果目录与文件引用必须保留，以便恢复进度和下载。
        _TASK["status_lines"] = []
        _TASK["extra_html"] = ""
    return gr.update(), gr.update(), temp_dir, "", gr.update()


def bind_translation_events(ui: Components):
    # 事件绑定
    # 开始和恢复按钮在任务轮询结束后恢复可用；停止时保留轮询以显示最终状态。
    ui.translate_btn.click(
        fn=lambda: gr.update(value="⏳ 翻译中...", interactive=False),
        inputs=[],
        outputs=[ui.translate_btn],
    )
    translate_event = ui.translate_btn.click(
        fn=translate_pdf,
        inputs=[
            ui.pdf_input,
            ui.active_api_key,
            ui.active_base_url,
            ui.active_model,
            ui.lang_in,
            ui.lang_out,
            ui.output_mode,
            ui.speed,
            ui.thinking_switch,
            ui.reasoning_effort_switch,
        ],
        outputs=[ui.result_download, ui.log_output, ui.temp_output_dir],
        api_name="translate",
    )
    translate_event.then(
        fn=lambda: gr.update(value="🚀 开始翻译", interactive=True),
        inputs=[],
        outputs=[ui.translate_btn],
    )

    # 恢复进度：重新接上后台正在运行（或已结束）的任务状态
    # 用于翻译过程中刷新页面后，手动点击接回最新进度
    ui.resume_btn.click(
        fn=lambda: gr.update(value="⏳ 翻译中...", interactive=False),
        inputs=[],
        outputs=[ui.translate_btn],
    )
    resume_event = ui.resume_btn.click(
        fn=resume_progress,
        inputs=[],
        outputs=[ui.result_download, ui.log_output, ui.temp_output_dir],
    )
    resume_event.then(
        fn=lambda: gr.update(value="🚀 开始翻译", interactive=True),
        inputs=[],
        outputs=[ui.translate_btn],
    )

    # 停止回调绕过队列；保留进度轮询，直到后台确认进程已退出。
    ui.stop_btn.click(
        fn=lambda: (request_stop(), "⏹ 已请求停止")[1],
        inputs=[],
        outputs=[ui.config_status],
        queue=False,
    )

    file_info_inputs = [ui.pdf_input, ui.lang_in, ui.lang_out, ui.output_mode, ui.speed]
    ui.pdf_input.change(
        fn=file_info_panel,
        inputs=file_info_inputs,
        outputs=[ui.file_info],
    )
    for setting in (ui.lang_in, ui.lang_out, ui.output_mode, ui.speed):
        setting.change(
            fn=file_info_panel,
            inputs=file_info_inputs,
            outputs=[ui.file_info],
        )

    ui.clear_btn.click(
        fn=clear_all,
        inputs=[ui.temp_output_dir],
        outputs=[
            ui.pdf_input,
            ui.result_download,
            ui.temp_output_dir,
            ui.log_output,
            ui.file_info,
        ],
    )

    return translate_event, resume_event
