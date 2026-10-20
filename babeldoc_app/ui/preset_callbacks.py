"""Ui preset callbacks."""

import uuid

import gradio as gr

from ..model_api import (
    REASONING_EFFORT_LEVELS,
    REASONING_EFFORT_TEST_VERSION,
    _is_glm53_model,
)
from ..presets import (
    _last_model_test_report,
    _preset_choices,
    _preset_summary,
    get_preset_by_id,
    load_config,
    save_config,
)


def _thinking_switch_update(p):
    """根据预设的测试结论生成思考模式开关的更新"""
    if p and _is_glm53_model(p.get("model")):
        return gr.update(visible=False, interactive=False, value="开启")
    if p and p.get("thinking_supported"):
        val = "关闭" if p.get("thinking_disabled") else "开启"
        return gr.update(
            visible=True, interactive=True, value=val, info="关闭后翻译更快更省"
        )
    if p and p.get("thinking_supported") is False:
        return gr.update(
            visible=True, interactive=False, value="开启", info="该模型不支持关闭思考"
        )
    return gr.update(
        visible=True,
        interactive=False,
        value="开启",
        info="先在预设管理中运行「🧪 模型测试」",
    )


def _reasoning_effort_update(p):
    if not p or not _is_glm53_model(p.get("model")):
        return gr.update(visible=False, interactive=False, value=None)
    if (
        p.get("reasoning_effort_supported")
        and p.get("reasoning_effort_test_version") == REASONING_EFFORT_TEST_VERSION
    ):
        level = p.get("reasoning_effort", "max")
        info = (
            "三档请求成功；中位数依次增加"
            if p.get("reasoning_effort_ordered")
            else "三档请求成功；思考量未按档位递增，效果未确认"
        )
        return gr.update(visible=True, interactive=True, value=level, info=info)
    return gr.update(
        visible=True,
        interactive=False,
        value=None,
        info="先在预设管理中重新运行「🧪 模型测试」",
    )


def _persist_thinking_choice(presets, active_id, val):
    """把思考模式开关的选择写入当前生效预设并保存"""
    p = get_preset_by_id(presets, active_id)
    if p:
        p["thinking_disabled"] = val == "关闭"
        save_config(presets, active_id)
    return presets


def _persist_reasoning_effort(presets, active_id, val):
    p = get_preset_by_id(presets, active_id)
    if (
        p
        and p.get("reasoning_effort_supported")
        and p.get("reasoning_effort_test_version") == REASONING_EFFORT_TEST_VERSION
        and val in REASONING_EFFORT_LEVELS
    ):
        p["reasoning_effort"] = val
        save_config(presets, active_id)
    return presets


def _apply_preset_ui(presets, preset_id):
    """把指定预设应用到主面板（下拉值、隐藏状态、摘要、思考开关）"""
    p = get_preset_by_id(presets, preset_id)
    if not p:
        return (
            gr.update(choices=_preset_choices(presets), value=None),
            "",
            "",
            "",
            _preset_summary(None),
            _thinking_switch_update(None),
            _reasoning_effort_update(None),
        )
    return (
        gr.update(choices=_preset_choices(presets), value=preset_id),
        p.get("api_key", ""),
        p.get("base_url", ""),
        p.get("model", ""),
        _preset_summary(p),
        _thinking_switch_update(p),
        _reasoning_effort_update(p),
    )


def _select_preset(presets, preset_id):
    if get_preset_by_id(presets, preset_id):
        save_config(presets, preset_id)
        return (preset_id, *_apply_preset_ui(presets, preset_id)[1:])
    return (None, *_apply_preset_ui(presets, None)[1:])


def open_preset_modal(presets):
    return (
        gr.update(visible=True),
        gr.update(choices=_preset_choices(presets), value=None),
        "",
        "",
        "",
        "",
        "",
        "",
    )


def load_preset_to_editor(presets, preset_id):
    p = get_preset_by_id(presets, preset_id)
    if not p:
        return "", "", "", "", "", ""
    return (
        p.get("name", ""),
        p.get("api_key", ""),
        p.get("base_url", ""),
        p.get("model", ""),
        "",
        _last_model_test_report(p),
    )


def handle_save_preset(presets, active_id, edit_id, name, api_key, base_url, model):
    name = (name or "").strip()
    if not name:
        return presets, active_id, "⚠️ 请填写预设名称", gr.update(), gr.update()
    presets = list(presets)
    target = get_preset_by_id(presets, edit_id) if edit_id else None
    if target:
        changed = any(
            (target.get(key) or "").strip() != (value or "").strip()
            for key, value in (
                ("api_key", api_key),
                ("base_url", base_url),
                ("model", model),
            )
        )
        target.update(
            name=name,
            api_key=api_key or "",
            base_url=(base_url or "").strip(),
            model=(model or "").strip(),
        )
        if changed:
            target.pop("last_model_test", None)
            target.pop("thinking_supported", None)
            target.pop("thinking_disabled", None)
            target.pop("reasoning_effort_supported", None)
            target.pop("reasoning_effort_test_version", None)
            target.pop("reasoning_effort_ordered", None)
            target.pop("reasoning_effort", None)
        new_id = target["id"]
        msg = "✅ 预设已更新" + ("，模型配置已变更，请重新测试" if changed else "")
    else:
        new_id = uuid.uuid4().hex[:8]
        presets.append(
            {
                "id": new_id,
                "name": name,
                "api_key": api_key or "",
                "base_url": (base_url or "").strip(),
                "model": (model or "").strip(),
            }
        )
        msg = "✅ 新预设已保存"
    save_config(presets, active_id)
    return (
        presets,
        active_id,
        msg,
        gr.update(choices=_preset_choices(presets), value=new_id),
        _last_model_test_report(get_preset_by_id(presets, new_id)),
    )


def handle_delete_preset(presets, active_id, edit_id):
    if not edit_id or not get_preset_by_id(presets, edit_id):
        return presets, active_id, gr.update(), "⚠️ 请先在列表中选择要删除的预设"
    presets = [p for p in presets if p["id"] != edit_id]
    if active_id == edit_id:
        active_id = None
    save_config(presets, active_id)
    return (
        presets,
        active_id,
        gr.update(choices=_preset_choices(presets), value=None),
        "✅ 预设已删除",
    )


def handle_apply_preset(presets, active_id, edit_id):
    target_id = edit_id or active_id
    p = get_preset_by_id(presets, target_id)
    if not p:
        return (
            presets,
            active_id,
            gr.update(visible=False),
            gr.update(),
            "",
            "",
            "",
            _preset_summary(None),
            _thinking_switch_update(None),
            _reasoning_effort_update(None),
        )
    if active_id != target_id:
        active_id = target_id
        save_config(presets, active_id)
    return (
        presets,
        active_id,
        gr.update(visible=False),
        gr.update(choices=_preset_choices(presets), value=target_id),
        p.get("api_key", ""),
        p.get("base_url", ""),
        p.get("model", ""),
        _preset_summary(p),
        _thinking_switch_update(p),
        _reasoning_effort_update(p),
    )


def load_config_ui():
    cfg = load_config()
    presets = cfg["presets"]
    active_id = cfg["active_id"]
    p = get_preset_by_id(presets, active_id)
    if not p:
        active_id = None
    return (
        presets,
        active_id,
        gr.update(choices=_preset_choices(presets), value=active_id),
        p.get("api_key", "") if p else "",
        p.get("base_url", "") if p else "",
        p.get("model", "") if p else "",
        _preset_summary(p),
        _thinking_switch_update(p),
        _reasoning_effort_update(p),
    )
