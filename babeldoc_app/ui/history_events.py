"""Ui history events."""

from ..history import (
    click_history_delete,
    refresh_history,
    select_history_row,
    show_history_files,
)
from .components import Components


def bind_history_events(ui: Components, translate_event, resume_event):
    # ---- 历史记录事件 ----
    ui.history_refresh_btn.click(
        fn=refresh_history,
        inputs=[ui.history_select],
        outputs=[
            ui.history_table,
            ui.history_select,
            ui.history_detail,
            ui.history_delete_btn,
            ui.history_delete_state,
        ],
    )

    # 翻译/恢复进度结束后，顺带刷新历史记录列表
    translate_event.then(
        fn=refresh_history,
        inputs=[ui.history_select],
        outputs=[
            ui.history_table,
            ui.history_select,
            ui.history_detail,
            ui.history_delete_btn,
            ui.history_delete_state,
        ],
    )
    resume_event.then(
        fn=refresh_history,
        inputs=[ui.history_select],
        outputs=[
            ui.history_table,
            ui.history_select,
            ui.history_detail,
            ui.history_delete_btn,
            ui.history_delete_state,
        ],
    )

    ui.history_table.select(
        fn=select_history_row,
        inputs=[ui.history_table],
        outputs=[
            ui.history_select,
            ui.history_original_file,
            ui.history_result_file,
            ui.history_detail,
            ui.history_delete_btn,
            ui.history_delete_state,
        ],
        queue=False,
        show_progress="hidden",
    )

    ui.history_select.change(
        fn=show_history_files,
        inputs=[ui.history_select],
        outputs=[
            ui.history_original_file,
            ui.history_result_file,
            ui.history_detail,
            ui.history_delete_btn,
            ui.history_delete_state,
        ],
    )

    ui.history_delete_btn.click(
        fn=click_history_delete,
        inputs=[ui.history_select, ui.history_delete_state],
        outputs=[
            ui.history_delete_btn,
            ui.history_delete_state,
            ui.history_table,
            ui.history_select,
            ui.history_original_file,
            ui.history_result_file,
            ui.history_detail,
        ],
    )
