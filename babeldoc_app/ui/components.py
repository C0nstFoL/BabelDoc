"""Ui components."""

from dataclasses import dataclass

import gradio as gr


@dataclass
class Components:
    """Named components shared by layout construction and event registration."""

    active_api_key: gr.State
    active_base_url: gr.State
    active_id_state: gr.State
    active_model: gr.State
    apply_preset_btn: gr.Button
    clear_btn: gr.Button
    close_preset_modal_btn: gr.Button
    config_status: gr.Markdown
    delete_preset_btn: gr.Button
    file_info: gr.HTML
    history_delete_btn: gr.Button
    history_delete_state: gr.State
    history_detail: gr.HTML
    history_original_file: gr.File
    history_refresh_btn: gr.Button
    history_result_file: gr.File
    history_select: gr.Dropdown
    history_table: gr.Dataframe
    lang_in: gr.Dropdown
    lang_out: gr.Dropdown
    log_output: gr.HTML
    manage_preset_btn: gr.Button
    model_test_btn: gr.Button
    model_test_status: gr.Markdown
    new_preset_btn: gr.Button
    output_mode: gr.Radio
    pdf_input: gr.File
    preset_api_key: gr.Textbox
    preset_base_url: gr.Textbox
    preset_edit_status: gr.Markdown
    preset_modal: gr.Row
    preset_model: gr.Textbox
    preset_name: gr.Textbox
    preset_radio: gr.Radio
    preset_select: gr.Dropdown
    preset_summary: gr.Markdown
    presets_state: gr.State
    reasoning_effort_switch: gr.Radio
    result_download: gr.File
    resume_btn: gr.Button
    save_preset_btn: gr.Button
    speed: gr.Dropdown
    stop_btn: gr.Button
    temp_output_dir: gr.State
    test_conn_btn: gr.Button
    theme_toggle_btn: gr.Button
    thinking_switch: gr.Radio
    translate_btn: gr.Button
