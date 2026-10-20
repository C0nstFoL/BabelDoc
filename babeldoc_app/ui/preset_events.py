"""Ui preset events."""

import gradio as gr

from ..model_api import (
    test_model_capabilities,
    test_preset_connection,
)
from ..presets import (
    _preset_choices,
    _preset_summary,
    get_preset_by_id,
)
from .components import Components
from .preset_callbacks import (
    _apply_preset_ui,
    _persist_reasoning_effort,
    _persist_thinking_choice,
    _reasoning_effort_update,
    _select_preset,
    _thinking_switch_update,
    handle_apply_preset,
    handle_delete_preset,
    handle_save_preset,
    load_preset_to_editor,
    open_preset_modal,
)


def bind_preset_events(ui: Components):
    # ---- LLM 预设管理事件 ----

    # 主面板下拉框：切换预设立即生效，并同步持久化当前预设 ID。

    ui.preset_select.input(
        fn=_select_preset,
        inputs=[ui.presets_state, ui.preset_select],
        outputs=[
            ui.active_id_state,
            ui.active_api_key,
            ui.active_base_url,
            ui.active_model,
            ui.preset_summary,
            ui.thinking_switch,
            ui.reasoning_effort_switch,
        ],
    )

    # 测试当前预设的 API 连通性：先立即给出提示并禁用按钮，结束后恢复
    ui.test_conn_btn.click(
        fn=lambda: (gr.update(interactive=False), "🔄 正在测试连接，请稍候..."),
        inputs=[],
        outputs=[ui.test_conn_btn, ui.config_status],
    )
    test_conn_event = ui.test_conn_btn.click(
        fn=test_preset_connection,
        inputs=[ui.active_api_key, ui.active_base_url, ui.active_model],
        outputs=[ui.config_status],
    )
    test_conn_event.then(
        fn=lambda: gr.update(interactive=True),
        inputs=[],
        outputs=[ui.test_conn_btn],
    )

    # 思考模式开关变化：持久化到当前生效预设，刷新页面后仍保留
    ui.thinking_switch.change(
        fn=lambda presets, active_id, val: _persist_thinking_choice(
            presets, active_id, val
        ),
        inputs=[ui.presets_state, ui.active_id_state, ui.thinking_switch],
        outputs=[ui.presets_state],
    )
    ui.reasoning_effort_switch.change(
        fn=_persist_reasoning_effort,
        inputs=[ui.presets_state, ui.active_id_state, ui.reasoning_effort_switch],
        outputs=[ui.presets_state],
    )

    # 模型能力测试（弹窗内）：测试结论写入所选预设并持久化
    ui.model_test_btn.click(
        fn=lambda: "🧪 正在测试模型（连通性 / 性能 / 推理设置），请稍候...",
        inputs=[],
        outputs=[ui.model_test_status],
    ).then(
        fn=test_model_capabilities,
        inputs=[
            ui.presets_state,
            ui.preset_radio,
            ui.active_id_state,
            ui.preset_api_key,
            ui.preset_base_url,
            ui.preset_model,
        ],
        outputs=[ui.model_test_status, ui.presets_state],
    ).then(
        fn=lambda presets, active_id, edit_id: (
            gr.update(choices=_preset_choices(presets), value=edit_id),
            gr.update(choices=_preset_choices(presets), value=active_id),
            _preset_summary(get_preset_by_id(presets, active_id)),
            _thinking_switch_update(get_preset_by_id(presets, active_id)),
            _reasoning_effort_update(get_preset_by_id(presets, active_id)),
        ),
        inputs=[ui.presets_state, ui.active_id_state, ui.preset_radio],
        outputs=[
            ui.preset_radio,
            ui.preset_select,
            ui.preset_summary,
            ui.thinking_switch,
            ui.reasoning_effort_switch,
        ],
    )

    # 打开弹窗：以“新建预设”的空表单开始

    ui.manage_preset_btn.click(
        fn=open_preset_modal,
        inputs=[ui.presets_state],
        outputs=[
            ui.preset_modal,
            ui.preset_radio,
            ui.preset_name,
            ui.preset_api_key,
            ui.preset_base_url,
            ui.preset_model,
            ui.preset_edit_status,
            ui.model_test_status,
        ],
    )

    ui.close_preset_modal_btn.click(
        fn=lambda: gr.update(visible=False),
        inputs=[],
        outputs=[ui.preset_modal],
    )

    # 弹窗内选中某个预设：载入编辑表单

    ui.preset_radio.input(
        fn=load_preset_to_editor,
        inputs=[ui.presets_state, ui.preset_radio],
        outputs=[
            ui.preset_name,
            ui.preset_api_key,
            ui.preset_base_url,
            ui.preset_model,
            ui.preset_edit_status,
            ui.model_test_status,
        ],
    )

    # 新建预设：清空编辑表单并取消 radio 选中
    ui.new_preset_btn.click(
        fn=lambda: (
            gr.update(value=None),
            "",
            "",
            "",
            "",
            "🆕 请填写新预设信息后点击「保存」",
            "",
        ),
        inputs=[],
        outputs=[
            ui.preset_radio,
            ui.preset_name,
            ui.preset_api_key,
            ui.preset_base_url,
            ui.preset_model,
            ui.preset_edit_status,
            ui.model_test_status,
        ],
    )

    # 保存预设：radio 选中了预设则更新，否则新建

    ui.save_preset_btn.click(
        fn=handle_save_preset,
        inputs=[
            ui.presets_state,
            ui.active_id_state,
            ui.preset_radio,
            ui.preset_name,
            ui.preset_api_key,
            ui.preset_base_url,
            ui.preset_model,
        ],
        outputs=[
            ui.presets_state,
            ui.active_id_state,
            ui.preset_edit_status,
            ui.preset_radio,
            ui.model_test_status,
        ],
    ).then(
        fn=_apply_preset_ui,
        inputs=[ui.presets_state, ui.active_id_state],
        outputs=[
            ui.preset_select,
            ui.active_api_key,
            ui.active_base_url,
            ui.active_model,
            ui.preset_summary,
            ui.thinking_switch,
            ui.reasoning_effort_switch,
        ],
    )

    # 删除当前 radio 选中的预设

    ui.delete_preset_btn.click(
        fn=handle_delete_preset,
        inputs=[ui.presets_state, ui.active_id_state, ui.preset_radio],
        outputs=[
            ui.presets_state,
            ui.active_id_state,
            ui.preset_radio,
            ui.preset_edit_status,
        ],
    ).then(
        fn=lambda: ("", "", "", "", ""),
        inputs=[],
        outputs=[
            ui.preset_name,
            ui.preset_api_key,
            ui.preset_base_url,
            ui.preset_model,
            ui.model_test_status,
        ],
    ).then(
        fn=_apply_preset_ui,
        inputs=[ui.presets_state, ui.active_id_state],
        outputs=[
            ui.preset_select,
            ui.active_api_key,
            ui.active_base_url,
            ui.active_model,
            ui.preset_summary,
            ui.thinking_switch,
            ui.reasoning_effort_switch,
        ],
    )

    # 应用并关闭：将 radio 选中的预设设为当前生效预设

    ui.apply_preset_btn.click(
        fn=handle_apply_preset,
        inputs=[ui.presets_state, ui.active_id_state, ui.preset_radio],
        outputs=[
            ui.presets_state,
            ui.active_id_state,
            ui.preset_modal,
            ui.preset_select,
            ui.active_api_key,
            ui.active_base_url,
            ui.active_model,
            ui.preset_summary,
            ui.thinking_switch,
            ui.reasoning_effort_switch,
        ],
    )
