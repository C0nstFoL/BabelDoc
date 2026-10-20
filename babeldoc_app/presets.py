"""Load, save and describe model presets."""

import base64
import json

from .settings import (
    CONFIG_DIR,
    CONFIG_FILE,
)


def _obscure(s: str) -> str:
    """简单编码，避免明文存储 API Key"""
    return base64.b64encode(s.encode()).decode()


def _reveal(s: str) -> str:
    """解码存储的 API Key"""
    try:
        return base64.b64decode(s.encode()).decode()
    except Exception:
        return ""


def load_config():
    """从本地文件加载所有 LLM 预设配置"""
    if not CONFIG_FILE.exists():
        return {"presets": [], "active_id": None}
    try:
        data = json.loads(CONFIG_FILE.read_text())
    except Exception:
        return {"presets": [], "active_id": None}
    presets = data.get("presets") or []
    for p in presets:
        if p.get("api_key"):
            p["api_key"] = _reveal(p["api_key"])
    return {"presets": presets, "active_id": data.get("active_id")}


def save_config(presets, active_id):
    """保存所有 LLM 预设配置到本地文件"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "presets": [
            {**p, "api_key": _obscure(p.get("api_key", "")) if p.get("api_key") else ""}
            for p in presets
        ],
        "active_id": active_id,
    }
    CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def get_preset_by_id(presets, preset_id):
    """按 id 查找预设，找不到返回 None"""
    for p in presets:
        if p["id"] == preset_id:
            return p
    return None


def _preset_choices(presets):
    """生成 gr.Dropdown / gr.Radio 的 (显示名, id) 选项列表"""
    choices = []
    for p in presets:
        perf = (p.get("last_model_test") or {}).get("performance")
        label = p["name"] + (f" · {perf}" if perf else "")
        choices.append((label, p["id"]))
    return choices


def _last_model_test_report(preset):
    """显示当前预设最近一次测试；旧预设没有记录时给出提示。"""
    test = (preset or {}).get("last_model_test") or {}
    if not test:
        return "ℹ️ 暂无已保存的模型测试结果"
    return f"{test['report']}\n\n*上次测试：{test['tested_at']}*"


def _preset_summary(preset):
    """生成主面板展示的预设摘要文本"""
    if not preset:
        return "⚠️ 尚未配置任何 LLM 预设，请点击「管理预设」创建"
    summary = f"当前使用：**{preset['name']}** · {preset.get('model', '')} · {preset.get('base_url', '')}"
    test = preset.get("last_model_test") or {}
    if test:
        summary += f"\n\n上次性能测试：{test.get('performance', '测试失败')} · {test['tested_at']}"
    return summary
