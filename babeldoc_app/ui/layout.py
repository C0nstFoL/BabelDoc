"""Ui layout."""

import gradio as gr

from ..history import _history_detail_html
from ..preflight import file_info_panel
from ..presets import _preset_summary
from .browser_events import CUSTOM_CSS
from .components import Components


def _panel_head(icon: str, num: str, title: str, sub: str) -> str:
    return (
        f'<div class="panel-head">'
        f'<span class="panel-ico">{icon}</span>'
        f'<div><div class="panel-title"><span class="panel-num">{num}</span>{title}</div>'
        f'<div class="panel-sub">{sub}</div></div>'
        f"</div>"
    )


def build_layout():
    """Construct components inside an active Blocks context."""
    # HTML 注入样式，兼容直接启动和 FastAPI 挂载两种方式。
    gr.HTML("<style>" + CUSTOM_CSS + "</style>")

    # 顶部 Hero 横幅（品牌 + 主题切换）
    with gr.Row(elem_classes="hero"):
        gr.HTML(
            """
            <div class="hero-inner">
                <div class="hero-brand">
                    <span class="hero-logo">📄</span>
                    <div>
                        <h1>BabelDOC 论文翻译</h1>
                        <p>基于 LLM 的 PDF 科研论文翻译 · 保留原文排版与公式 · 多预设秒切</p>
                    </div>
                </div>
            </div>
            """
        )
        theme_toggle_btn = gr.Button("🖥️ 跟随系统", size="sm", scale=0)

    # 状态变量
    temp_output_dir = gr.State(None)
    # LLM 预设列表与当前生效预设 id
    presets_state = gr.State([])
    active_id_state = gr.State(None)

    # 面板标题（HTML 注入）

    with gr.Tabs():
        # ---------------- Tab 1：翻译工作台 ----------------
        with gr.Tab("🚀 翻译"):
            # 顶部步骤条
            gr.HTML(
                """
                <div class="step-bar">
                    <div class="step-item"><span class="step-num">1</span>上传文件</div>
                    <div class="step-sep"></div>
                    <div class="step-item"><span class="step-num">2</span>模型配置</div>
                    <div class="step-sep"></div>
                    <div class="step-item"><span class="step-num">3</span>语言与速度</div>
                    <div class="step-sep"></div>
                    <div class="step-item"><span class="step-num">4</span>开始翻译</div>
                </div>
                """
            )

            with gr.Column(elem_classes="workflow-col"):
                # 桌面端横版：左列（上传 + 操作按钮）与右列（LLM 配置 + 语言与速度），
                # 窄屏自动堆叠为单列
                with gr.Row(elem_classes="desktop-split"):
                    with gr.Column(elem_classes="col-left"):
                        with gr.Group(elem_classes="step-card upload-card"):
                            gr.HTML(
                                _panel_head(
                                    "📥", "1", "上传文件", "拖拽或点击上传 PDF 文献"
                                )
                            )
                            pdf_input = gr.File(
                                label="上传 PDF 文件",
                                file_types=[".pdf"],
                                file_count="single",
                            )

                        # 操作按钮置于左列底部（上传后即可开始翻译）
                        with gr.Row(elem_classes="action-row"):
                            translate_btn = gr.Button(
                                "🚀 开始翻译", variant="primary", size="lg", scale=3
                            )
                            resume_btn = gr.Button(
                                "🔄 恢复进度", variant="secondary", size="lg", scale=1
                            )
                            stop_btn = gr.Button(
                                "⏹ 停止", variant="stop", size="lg", scale=1
                            )

                        with gr.Group(elem_classes="step-card file-info-card"):
                            gr.HTML(
                                _panel_head(
                                    "📄", "", "文件信息", "上传后自动显示文件属性"
                                )
                            )
                            file_info = gr.HTML(file_info_panel(None))

                    with gr.Column(elem_classes="col-right"):
                        with gr.Group(elem_classes="step-card llm-card"):
                            gr.HTML(
                                _panel_head(
                                    "🧠", "2", "LLM 模型配置", "选择或管理 API 预设"
                                )
                            )
                            with gr.Row():
                                preset_select = gr.Dropdown(
                                    label="选择预设",
                                    choices=[],
                                    value=None,
                                    scale=2,
                                )
                                manage_preset_btn = gr.Button(
                                    "⚙️ 管理预设", variant="secondary", scale=1
                                )
                                test_conn_btn = gr.Button(
                                    "🔌 测试连接", variant="secondary", scale=1
                                )
                            preset_summary = gr.Markdown(
                                _preset_summary(None),
                                elem_classes=["preset-summary", "llm-summary"],
                            )
                            # 思考模式开关：默认灰色，模型测试确认支持后才解锁
                            thinking_switch = gr.Radio(
                                choices=["开启", "关闭"],
                                value="开启",
                                label="思考模式",
                                interactive=False,
                                info="先在预设管理中运行「🧪 模型测试」",
                            )
                            reasoning_effort_switch = gr.Radio(
                                choices=[
                                    ("轻量", "low"),
                                    ("增强", "high"),
                                    ("深度", "max"),
                                ],
                                value=None,
                                label="推理深度",
                                interactive=False,
                                visible=False,
                                info="先在预设管理中运行「🧪 模型测试」",
                            )
                            config_status = gr.Markdown("")
                            # 隐藏状态：当前生效的 api_key / base_url / model，供翻译任务使用
                            active_api_key = gr.State("")
                            active_base_url = gr.State("")
                            active_model = gr.State("")

                        with gr.Group(elem_classes="step-card"):
                            gr.HTML(
                                _panel_head(
                                    "🌐", "3", "语言与速度", "翻译方向与输出偏好"
                                )
                            )
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

                with gr.Group(elem_classes="step-card"):
                    gr.HTML(
                        _panel_head("📡", "4", "翻译日志与进度", "实时进度与终端日志")
                    )
                    log_output = gr.HTML(
                        value="",
                        elem_classes="log-panel",
                    )
                    with gr.Row():
                        result_download = gr.File(
                            label="📥 下载翻译结果（含双语/单语全部输出）",
                            file_count="multiple",
                        )
                        clear_btn = gr.Button("🗑️ 清空", variant="secondary", scale=0)

        # ---------------- Tab 2：历史记录 ----------------
        with gr.Tab("🗂️ 历史记录"):
            with gr.Group(elem_classes="step-card"):
                gr.Markdown("#### 历史翻译任务")
                history_table = gr.Dataframe(
                    headers=["文件名", "时间", "语言", "模型", "设置", "耗时", "状态"],
                    datatype=["str", "str", "str", "str", "str", "str", "str"],
                    # Gradio 6 只有 interactive=True 才会向后端派发 select 事件；
                    # 通过 static_columns 锁定全部列，保留行选择但不允许修改历史数据。
                    interactive=True,
                    static_columns=[0, 1, 2, 3, 4, 5, 6],
                    type="array",
                    wrap=True,
                    row_count=8,
                    max_height=460,
                    show_search="filter",
                    pinned_columns=1,
                    column_widths=[240, 158, 110, 180, 185, 72, 90],
                    elem_classes="history-table",
                )
                with gr.Row():
                    history_select = gr.Dropdown(
                        label="已选任务（也可从下拉列表搜索）",
                        choices=[],
                        value=None,
                        scale=3,
                    )
                    history_refresh_btn = gr.Button("🔄 刷新", scale=1)
                history_detail = gr.HTML(
                    value=_history_detail_html(None),
                )
                history_delete_state = gr.State(None)
                with gr.Row():
                    history_delete_btn = gr.Button(
                        "🗑️ 删除任务",
                        variant="stop",
                        scale=1,
                        interactive=False,
                    )
                with gr.Row():
                    history_original_file = gr.File(label="原始文档", scale=1)
                    history_result_file = gr.File(
                        label="翻译后文档（含双语/单语全部输出）",
                        scale=1,
                        file_count="multiple",
                    )

    # ---------------- LLM 预设管理弹窗 ----------------
    with gr.Row(visible=False, elem_classes="preset-modal-overlay") as preset_modal:
        with gr.Column(elem_classes="preset-modal-card"):
            gr.Markdown("#### ⚙️ 管理 LLM 预设")
            preset_radio = gr.Radio(
                label="已保存的预设",
                choices=[],
                value=None,
            )
            with gr.Row():
                new_preset_btn = gr.Button("➕ 新建预设", size="sm", scale=1)
                delete_preset_btn = gr.Button(
                    "🗑️ 删除所选", variant="stop", size="sm", scale=1
                )
            gr.Markdown("---")
            preset_name = gr.Textbox(
                label="预设名称",
                placeholder="例如：DeepSeek 主账号",
            )
            preset_api_key = gr.Textbox(
                label="API Key",
                placeholder="sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                type="password",
            )
            preset_base_url = gr.Textbox(
                label="API Base URL",
                placeholder="https://api.deepseek.com/v1",
            )
            preset_model = gr.Textbox(
                label="模型名称",
                placeholder="deepseek-chat",
            )
            model_test_btn = gr.Button(
                "🧪 模型测试（可行性 / 性能 / 推理设置）", variant="secondary"
            )
            model_test_status = gr.Markdown("")
            preset_edit_status = gr.Markdown("")
            with gr.Row():
                save_preset_btn = gr.Button("💾 保存", variant="primary", scale=1)
                apply_preset_btn = gr.Button(
                    "✅ 应用并关闭", variant="primary", scale=1
                )
                close_preset_modal_btn = gr.Button("✖️ 关闭", scale=1)

    return Components(
        active_api_key=active_api_key,
        active_base_url=active_base_url,
        active_id_state=active_id_state,
        active_model=active_model,
        apply_preset_btn=apply_preset_btn,
        clear_btn=clear_btn,
        close_preset_modal_btn=close_preset_modal_btn,
        config_status=config_status,
        delete_preset_btn=delete_preset_btn,
        file_info=file_info,
        history_delete_btn=history_delete_btn,
        history_delete_state=history_delete_state,
        history_detail=history_detail,
        history_original_file=history_original_file,
        history_refresh_btn=history_refresh_btn,
        history_result_file=history_result_file,
        history_select=history_select,
        history_table=history_table,
        lang_in=lang_in,
        lang_out=lang_out,
        log_output=log_output,
        manage_preset_btn=manage_preset_btn,
        model_test_btn=model_test_btn,
        model_test_status=model_test_status,
        new_preset_btn=new_preset_btn,
        output_mode=output_mode,
        pdf_input=pdf_input,
        preset_api_key=preset_api_key,
        preset_base_url=preset_base_url,
        preset_edit_status=preset_edit_status,
        preset_modal=preset_modal,
        preset_model=preset_model,
        preset_name=preset_name,
        preset_radio=preset_radio,
        preset_select=preset_select,
        preset_summary=preset_summary,
        presets_state=presets_state,
        reasoning_effort_switch=reasoning_effort_switch,
        result_download=result_download,
        resume_btn=resume_btn,
        save_preset_btn=save_preset_btn,
        speed=speed,
        stop_btn=stop_btn,
        temp_output_dir=temp_output_dir,
        test_conn_btn=test_conn_btn,
        theme_toggle_btn=theme_toggle_btn,
        thinking_switch=thinking_switch,
        translate_btn=translate_btn,
    )
