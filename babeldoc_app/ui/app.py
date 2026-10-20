"""Ui app."""

import gradio as gr

from ..history import refresh_history
from .browser_events import bind_browser_events
from .history_events import bind_history_events
from .layout import build_layout
from .preset_callbacks import load_config_ui
from .preset_events import bind_preset_events
from .translation_events import bind_translation_events


def build_ui():
    """Build the interface on demand; importing application modules has no UI side effects."""
    with gr.Blocks(title="BabelDOC 论文翻译 - LLM", theme=gr.themes.Soft()) as demo:
        ui = build_layout()
        translate_event, resume_event = bind_translation_events(ui)
        bind_preset_events(ui)
        bind_history_events(ui, translate_event, resume_event)
        demo.load(
            fn=load_config_ui,
            inputs=[],
            outputs=[
                ui.presets_state,
                ui.active_id_state,
                ui.preset_select,
                ui.active_api_key,
                ui.active_base_url,
                ui.active_model,
                ui.preset_summary,
                ui.thinking_switch,
                ui.reasoning_effort_switch,
            ],
        )
        demo.load(
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
        bind_browser_events(demo, ui)
        # 示例
        gr.Markdown(
            """
            ---
            ### 💡 使用说明
            1. **配置模型**：首次使用点击「⚙️ 管理预设」，填写 API Key、Base URL 和模型名称；之后可在主面板快速切换预设。
            2. **上传论文**：在「🚀 翻译」页上传 PDF，确认页面中的文字层、翻译参数、预计时长和 Token 用量。
            3. **开始翻译**：设置源/目标语言、输出模式和翻译速度后开始任务；页面会显示阶段进度和日志。
            4. **中断恢复**：刷新页面不会终止后台任务；重新打开后可点击「🔄 恢复进度」继续查看状态。
            5. **获取结果**：翻译完成后在当前页下载，或在「🗂️ 历史记录」选择任务后载入/下载原文和译文。
            6. **管理历史**：历史页支持筛选、刷新和删除；删除按钮需点击两次确认，操作会同时移除记录和输出文件。
            """
        )
    return demo
