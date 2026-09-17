import os
import re
import json
import html
import uuid
import base64
import subprocess
import threading
import tempfile
import shutil
import time
import glob
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
import gradio as gr
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse
from authlib.integrations.starlette_client import OAuth

# ---- OIDC 认证配置 ---- #
OIDC_ISSUER = os.environ.get("OIDC_ISSUER", "").strip()
OIDC_CLIENT_ID = os.environ.get("OIDC_CLIENT_ID", "")
OIDC_CLIENT_SECRET = os.environ.get("OIDC_CLIENT_SECRET", "")
AUTH_ENABLED = os.environ.get("AUTH_ENABLED", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
# 完整外部访问地址（用于拼接 OIDC 回调地址），例如 https://translate.folink.site
APP_BASE_URL = os.environ.get("APP_BASE_URL", "https://translate.folink.site")
# 用于加密登录会话 Cookie，生产环境务必通过环境变量设置固定值，
# 否则每次重启服务都会导致已登录用户全部掉线
SESSION_SECRET = os.environ.get("SESSION_SECRET", base64.b64encode(os.urandom(32)).decode())

# 配置文件路径（放在项目目录下，避免 macOS 沙箱权限问题）
CONFIG_DIR = Path(__file__).parent
CONFIG_FILE = CONFIG_DIR / ".babeldoc_config.json"


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
    return [(p["name"], p["id"]) for p in presets]


def _preset_summary(preset):
    """生成主面板展示的预设摘要文本"""
    if not preset:
        return "⚠️ 尚未配置任何 LLM 预设，请点击「管理预设」创建"
    return f"当前使用：**{preset['name']}** · {preset.get('model', '')} · {preset.get('base_url', '')}"


def _test_models_endpoint(api_key, base_url):
    """降级测试：GET {base_url}/models 验证服务可达性与 Key 有效性。

    返回 (成功?, 描述文本)。
    """
    url = base_url.rstrip("/") + "/models"
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {api_key}"}, method="GET"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return True, f"✅ 服务可达、Key 有效（GET /models 返回 HTTP {resp.status}）"
    except urllib.error.HTTPError as e:
        return False, f"❌ /models 也失败（HTTP {e.code}）"
    except Exception as e:
        return False, f"❌ /models 也失败（{type(e).__name__}: {e}）"


def test_preset_connection(api_key, base_url, model):
    """测试当前预设的 API 连通性：向 /chat/completions 发一个最小请求。

    返回 Markdown 状态文本（成功/失败原因），10 秒超时。
    部分中转站的模型（如 Claude）不支持 chat completions 协议，
    此时降级测试 /models 并提示该预设无法用于翻译。
    """
    if not base_url or not api_key:
        return "⚠️ 请先选择一个包含 API Key 和 Base URL 的预设"
    url = base_url.rstrip("/") + "/chat/completions"
    payload = json.dumps(
        {
            "model": model or "",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1,
            "stream": False,
        }
    ).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            elapsed = time.time() - t0
            return f"✅ 连接成功（HTTP {resp.status}，{elapsed:.2f}s）"
    except urllib.error.HTTPError as e:
        elapsed = time.time() - t0
        detail = ""
        try:
            detail = e.read().decode("utf-8", "ignore")[:200]
        except Exception:
            pass
        protocol_unsupported = "protocol_not_supported" in detail
        if protocol_unsupported:
            # 模型不支持 chat completions 协议（常见于仅支持 Anthropic 协议的模型），
            # 降级测试 /models 以确认服务与 Key 本身可用
            ok, fallback_msg = _test_models_endpoint(api_key, base_url)
            warn = (
                f"⚠️ 模型 **{model or '(未填写)'}** 不支持 chat completions 协议，"
                "BabelDOC 翻译依赖该协议，此预设**无法用于翻译**。\n\n"
            )
            if ok:
                return warn + fallback_msg + "\n\n```\n" + detail + "\n```"
            return warn + fallback_msg
        # 401/403 通常是 key 无效；404 通常是 base_url 或 model 不对
        hint = {
            401: "API Key 无效或未授权",
            403: "API Key 无权限",
            404: "Base URL 或模型名不正确",
        }.get(e.code, "")
        msg = f"❌ 连接失败（HTTP {e.code}，{elapsed:.2f}s）"
        if hint:
            msg += f"：{hint}"
        if detail:
            msg += f"\n\n```\n{detail}\n```"
        return msg
    except Exception as e:
        elapsed = time.time() - t0
        return f"❌ 连接失败（{type(e).__name__}: {e}，{elapsed:.2f}s）"


def _probe_chat(api_key, base_url, model, extra=None, prompt="hi", max_tokens=400, timeout=60):
    """向 chat completions 发送一次探测请求，返回 (响应dict, 耗时秒)。失败抛异常。"""
    payload = {
        "model": model or "",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "stream": False,
    }
    if extra:
        payload.update(extra)
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8", "ignore"))
    return data, time.time() - t0


def _msg_reasoning(message: dict) -> str:
    """提取响应中的思考内容（兼容 reasoning_content / reasoning 字段）"""
    if not message:
        return ""
    return message.get("reasoning_content") or message.get("reasoning") or ""


def test_model_capabilities(presets, edit_id, active_id, api_key, base_url, model):
    """模型能力测试：可行性 / 性能 / 是否可关闭思考模式。

    返回 (测试报告 Markdown, 更新后的 presets)。测试结论写入对应预设并持久化，
    供主界面「思考模式」开关判断是否可调。
    """
    if not api_key or not base_url:
        return "⚠️ 请先填写 API Key 与 Base URL 再测试", presets

    report = [f"### 🧪 模型测试报告：`{model or '(未填写)'}`"]

    # ---- 1) 可行性 ----
    try:
        data0, lat0 = _probe_chat(api_key, base_url, model, prompt="hi", max_tokens=5, timeout=30)
    except urllib.error.HTTPError as e:
        hint = {401: "API Key 无效", 403: "无权限", 404: "Base URL 或模型名不正确"}.get(e.code, "")
        return f"❌ **模型不可用**（HTTP {e.code}{'：' + hint if hint else ''}）", presets
    except Exception as e:
        return f"❌ **模型不可用**（{type(e).__name__}: {e}）", presets
    report.append(f"- **可行性**：✅ 可用于翻译（连通 {lat0:.2f}s）")

    # ---- 2) 性能（一段真实小翻译）----
    perf_prompt = (
        "Translate to Chinese. Output only the translation:\n"
        "The regular languages are closed under union, concatenation, and the Kleene star operation."
    )
    try:
        d1, lat1 = _probe_chat(api_key, base_url, model, prompt=perf_prompt, max_tokens=2000, timeout=180)
        ctok = (d1.get("usage") or {}).get("completion_tokens", 0)
        tps = ctok / lat1 if lat1 > 0 else 0
        report.append(f"- **性能**：✅ 延迟 {lat1:.2f}s · 输出 {ctok} tokens · 约 {tps:.0f} tok/s")
    except Exception as e:
        report.append(f"- **性能**：⚠️ 测试失败（{type(e).__name__}），不影响可用性")

    # ---- 3) 思考开关探测 ----
    default_thinks = len(_msg_reasoning((data0.get("choices") or [{}])[0].get("message"))) > 0
    variants = [
        ("thinking.type=disabled", {"thinking": {"type": "disabled"}}),
        ("enable_thinking=false", {"chat_template_kwargs": {"enable_thinking": False}}),
    ]
    supported = False
    detail = []
    for label, extra in variants:
        try:
            dv, _ = _probe_chat(api_key, base_url, model, extra=extra, prompt="hi", max_tokens=400, timeout=90)
            still_thinks = len(_msg_reasoning((dv.get("choices") or [{}])[0].get("message"))) > 0
            if still_thinks and default_thinks:
                detail.append(f"- `{label}`：⚠️ 请求被接受但思考未关闭")
            else:
                detail.append(f"- `{label}`：✅ 可关闭")
                supported = True
        except urllib.error.HTTPError as e:
            detail.append(f"- `{label}`：❌ HTTP {e.code}")
        except Exception as e:
            detail.append(f"- `{label}`：❌ {type(e).__name__}")

    if not default_thinks and not supported:
        report.append("- **思考模式**：ℹ️ 该模型默认不输出思考内容，无需关闭")
        supported = True  # 无思考可关，开关可放开（无副作用）
    elif supported:
        report.append("- **思考模式**：✅ 支持关闭，主界面开关已解锁")
    else:
        report.append("- **思考模式**：❌ 不支持关闭（强制思考模型，如 GLM-5.3 系）")
    report.extend(detail)
    report.append("\n> 结论已保存到该预设，主界面「思考模式」开关将按此解锁。")

    # ---- 4) 结论写入预设并持久化 ----
    if edit_id:
        for p in presets:
            if p.get("id") == edit_id:
                p["thinking_supported"] = supported
                break
        else:
            presets = presets
        save_config(presets, active_id)

    return "\n".join(report), presets


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


def show_history_files(task_id: str):
    """选中历史任务后，自动在下载区展示原文与全部译文文件（不触发浏览器下载）"""
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
    return original, results


def refresh_history():
    """刷新历史记录表格与选择框"""
    records = _load_history()
    return _history_table(records), gr.update(choices=_history_choices(records), value=None)


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
            files = [f for f in (r.get("result_files") or []) if f and os.path.exists(f)]
            if not files:
                path = r.get("result_file")
                if path and os.path.exists(path):
                    return path
                raise gr.Error("文件不存在或已被清理")
            return files
    raise gr.Error("未找到该任务的记录")


def delete_history_selected(task_id: str):
    """删除选中的历史记录，并刷新表格"""
    if not task_id:
        raise gr.Error("请先在「选择历史任务」下拉框中选择要删除的任务")
    _delete_history_record(task_id)
    records = _load_history()
    return _history_table(records), gr.update(choices=_history_choices(records), value=None), None, None


# ---- 停止机制 ---- #
_stop_event = threading.Event()
_running_process: subprocess.Popen | None = None

# ---- 后台任务全局状态 ----
# 翻译在独立线程中运行，状态写入这个全局字典，
# 这样即使用户刷新页面（Gradio 请求的生成器被取消），
# 后台任务也不受影响，刷新后重新查看即可接上最新状态。
_TASK: dict = {
    "running": False,          # 是否有任务在跑
    "status_lines": [],        # 状态日志（HTML 片段列表）
    "completed_stages": [],    # 已完成阶段
    "current_stage": None,     # 当前阶段
    "stage_start": 0.0,
    "overall_start": 0.0,
    "active_serial": 0,
    "result_file": None,       # 完成后的主结果文件路径（优先 dual）
    "result_files": None,      # 完成后的全部输出文件列表（dual + mono 等）
    "output_dir": None,        # 本次任务的临时输出目录
    "task_id": None,           # 本次任务的历史记录 ID
    "finished": False,         # 任务是否已结束（成功/失败/停止）
    "extra_html": "",          # 结束时追加的提示 HTML
    "last_activity": 0.0,      # 最近一次收到 BabelDOC 输出的时间
    "warning_count": 0,        # BabelDOC 警告/降级重试次数
    "last_warning": "",        # 最近一条警告，供长任务诊断
}
_task_lock = threading.Lock()


def request_stop():
    """请求停止翻译（由 UI 按钮调用）"""
    _stop_event.set()
    proc = _running_process
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
        except Exception:
            pass


def _reset_stop():
    """重置停止状态"""
    _stop_event.clear()
    global _running_process
    _running_process = None


# ---- 日志与进度 ---- #
import sys as _sys

STAGE_WEIGHTS: list[tuple[str, float, str]] = [
    ("DetectScannedFile", 2.45, "扫描检测"),
    ("Parse Page Layout", 14.03, "页面布局解析"),
    ("Parse Table", 1.0, "表格解析"),
    ("Parse Paragraphs", 6.26, "段落解析"),
    ("Parse Formulas and Styles", 1.66, "公式与样式解析"),
    ("Automatic Term Extraction", 30.0, "术语提取"),
    ("Translate Paragraphs", 46.96, "段落翻译"),
    ("Typesetting", 4.71, "排版"),
    ("Add Fonts", 0.61, "字体嵌入"),
    ("Generate drawing instructions", 1.96, "生成绘图指令"),
]
_TOTAL_WEIGHT = sum(w for _, w, _ in STAGE_WEIGHTS)
_STAGE_INDEX: dict[str, int] = {name: i for i, (name, _, _) in enumerate(STAGE_WEIGHTS)}


def _parse_log(raw: str) -> tuple[str, str, str] | None:
    """解析 babeldoc 日志行，返回 (timestamp, level, message) 或 None"""
    m = re.match(
        r"(\[\d{2}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}\])"
        r"\s+(WARNING|ERROR|INFO)\s+"
        r"(?:WARNING|ERROR|INFO):babeldoc\..*?:"
        r"\s*(.+)",
        raw,
    )
    if m:
        return m.groups()  # (ts, level, msg)
    return None


def _detect_stage_from_msg(msg: str) -> str | None:
    """根据日志消息检测当前阶段名称"""
    patterns = [
        ("DetectScannedFile", r"DetectScannedFile|扫描件检测"),
        ("Parse Page Layout", r"Parse Page Layout|页面布局|Clustered into|drawing boxes|Annotated images"),
        ("Parse Table", r"Parse Table|表格解析"),
        ("Parse Paragraphs", r"Parse Paragraphs|段落解析"),
        ("Parse Formulas and Styles", r"Parse Formulas and Styles|公式.*样式|样式.*公式"),
        ("Automatic Term Extraction", r"Automatic Term Extraction|terms? extract|术语提取"),
        ("Translate Paragraphs", r"Translate Paragraphs|paragraphs? translat|il_translator|段落翻译|LLM translat"),
        ("Typesetting", r"Typesetting|排版"),
        ("Add Fonts", r"Add Fonts|Font (mapper|subsetting)|字体|fontmap"),
        ("Generate drawing instructions", r"Generate drawing|绘图指令|PDF save|PDF.*subsetting"),
    ]
    for stage_name, pattern in patterns:
        if re.search(pattern, msg, re.IGNORECASE):
            return stage_name
    return None


def _detect_stage_from_raw(raw: str) -> str | None:
    """从原始（未解析）日志行检测阶段 — 利用模块路径中的阶段信息"""
    patterns = [
        ("DetectScannedFile", r"detect_scanned_file"),
        ("Parse Page Layout", r"layout_parser"),
        ("Parse Table", r"table_parser"),
        ("Parse Paragraphs", r"paragraph_finder"),
        ("Parse Formulas and Styles", r"styles_and_formulas|remove_descent"),
        ("Automatic Term Extraction", r"automatic_term_extractor"),
        ("Translate Paragraphs", r"il_translator|translate_paragraph"),
        ("Typesetting", r"typesetting"),
        ("Add Fonts", r"fontmap"),
        ("Generate drawing instructions", r"pdf_creater|backend"),
    ]
    for stage_name, pattern in patterns:
        if re.search(pattern, raw, re.IGNORECASE):
            return stage_name
    return None


# ---- 进度条（阶段 + 服务端计时器 + spinner）---- #
def _build_progress_html(
    completed_stages: list[str],
    current_stage: str | None,
    start_time: float,
    active_serial: int = 0,
) -> str:
    """构建进度条 HTML，含 CSS spinner、服务端计时器、alive 心跳。"""
    if not current_stage and not completed_stages:
        return ""

    bars: list[str] = []
    for name, weight, label in STAGE_WEIGHTS:
        pct = weight / _TOTAL_WEIGHT * 100
        if name in completed_stages:
            cls = "pg-done"
        elif name == current_stage:
            cls = "pg-current"
        else:
            cls = "pg-pending"
        bars.append(
            f'<div class="{cls}" style="flex:{pct:.2f}"'
            f' title="{label}"></div>'
        )

    done_weight = sum(w for name, w, _ in STAGE_WEIGHTS if name in completed_stages)
    progress = done_weight / _TOTAL_WEIGHT * 100

    current_label = ""
    for name, _, label in STAGE_WEIGHTS:
        if name == current_stage:
            current_label = label
            break

    # 活跃脉冲点：有 current_stage 时显示
    active_dot = (
        '<span class="alive-dot"></span> '
        if current_stage
        else ""
    )

    # Gradio 通过 innerHTML 更新 gr.HTML，不会执行其中的 script 标签。
    # 计时值由 resume_progress 的服务端心跳每秒重新渲染。
    elapsed = max(0, int(time.time() - start_time))
    minutes, seconds = divmod(elapsed, 60)
    elapsed_text = f"{minutes}m{seconds}s" if minutes else f"{seconds}s"
    timer_html = f'<span class="elapsed">(本阶段 {elapsed_text})</span>'

    return (
        '<div class="progress-area">'
        f'<span class="progress-text">'
        f'{active_dot}'
        f'<span class="spinner"></span> '
        f'<b style="color:#4FC3F7">{current_label}</b> '
        f'{timer_html}'
        f'<span style="float:right;color:#4CAF50;font-weight:bold">{progress:.0f}%</span>'
        f"</span>"
        '<div class="progress-bar">'
        + "".join(bars)
        + "</div>"
        + "</div>"
    )


def _task_add_status(html: str) -> None:
    """向全局任务状态追加一条日志（加锁保证线程安全）"""
    ts = f'<span class="log-time">{datetime.now().strftime("%H:%M:%S")}</span> '
    if html.startswith("<div"):
        html = re.sub(r"(<div[^>]*>)", r"\1" + ts, html, count=1)
    else:
        html = ts + html
    with _task_lock:
        _TASK["status_lines"].append(html)


def _task_snapshot_html(extra: str = "") -> str:
    """根据全局任务状态生成当前展示 HTML"""
    with _task_lock:
        completed_stages = list(_TASK["completed_stages"])
        current_stage = _TASK["current_stage"]
        stage_start = _TASK["stage_start"]
        active_serial = _TASK["active_serial"]
        status_lines = list(_TASK["status_lines"])
        last_activity = _TASK["last_activity"]
        warning_count = _TASK["warning_count"]
        last_warning = _TASK["last_warning"]
    live_status = ""
    if current_stage and last_activity:
        idle_seconds = max(0, int(time.time() - last_activity))
        live_status = (
            '<div class="log-line log-info" style="font-size:12px">'
            f"&#128994; 子进程运行中 · 最近输出 {idle_seconds}s 前"
        )
        if warning_count:
            live_status += f" · 已发生 {warning_count} 次警告/降级重试"
        live_status += "</div>"
        if last_warning:
            live_status += (
                '<div class="log-line log-warning" style="font-size:12px">'
                "最近警告: " + html.escape(last_warning[:240]) + "</div>"
            )
    return (
        _build_progress_html(completed_stages, current_stage, stage_start, active_serial)
        + "".join(status_lines)
        + live_status
        + extra
    )


# ---- 扫描版 PDF OCR 预处理 ---- #

def _pdf_needs_ocr(pdf_path: str) -> bool:
    """检测 PDF 是否为纯扫描件（超过 80% 的页面几乎没有有效文本层）。

    注意：扫描件常带每页重复的水印文字，需先过滤跨页重复的行，
    否则会被水印误判为有文字层。
    """
    try:
        try:
            import pymupdf
        except ImportError:
            import fitz as pymupdf

        with pymupdf.open(pdf_path) as doc:
            pages_text = [page.get_text().strip() for page in doc]
        if not pages_text:
            return False

        # 出现在 >=60% 页面上的行视为水印/页眉页脚
        n = len(pages_text)
        line_counter: dict[str, int] = {}
        for text in pages_text:
            for line in {ln.strip() for ln in text.splitlines() if ln.strip()}:
                line_counter[line] = line_counter.get(line, 0) + 1
        watermark_lines = {ln for ln, c in line_counter.items() if c >= max(2, n * 0.6)}

        def _real_text_len(text: str) -> int:
            return sum(
                len(ln) for ln in text.splitlines()
                if ln.strip() and ln.strip() not in watermark_lines
            )

        scanned = sum(1 for t in pages_text if _real_text_len(t) < 50)
        return scanned / n > 0.8
    except Exception:
        return False


def _ocr_preprocess(pdf_path: str, lang_in: str, out_path: str) -> bool:
    """用 ocrmypdf（tesseract）为扫描 PDF 添加可提取的文字层"""
    lang_map = {"en": "eng", "zh": "chi_sim"}
    tess_lang = lang_map.get((lang_in or "en").split("-")[0].lower(), "eng+chi_sim")
    try:
        # --force-ocr：扫描件常带仅含水印的假文字层，--skip-text 会因此跳过 OCR；
        # 强制对整页做 OCR 才能生成真正的正文文字层
        result = subprocess.run(
            ["ocrmypdf", "--force-ocr", "--output-type", "pdf", "--quiet",
             "-l", tess_lang, pdf_path, out_path],
            capture_output=True,
            timeout=600,
        )
        return result.returncode == 0 and os.path.exists(out_path)
    except Exception:
        return False


def _run_translation_worker(pdf_file, api_key, base_url, model, lang_in, lang_out, output_mode, speed, disable_thinking=False):
    """后台线程：运行 babeldoc 子进程并持续更新全局任务状态。
    该函数不依赖任何 Gradio 请求上下文，因此浏览器刷新页面不会影响它的执行。
    """
    global _running_process
    _error_warn_count: dict[str, int] = {}

    task_id = datetime.now().strftime("%Y%m%d%H%M%S%f")
    task_dir = HISTORY_DIR / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    original_file = str(task_dir / f"original_{os.path.basename(pdf_file)}")
    try:
        shutil.copy2(pdf_file, original_file)
    except Exception:
        original_file = None

    # 扫描版 PDF 预处理：纯图片页无文本层，babeldoc 会抛 ScannedPDFError 且无输出，
    # 先用 ocrmypdf/tesseract 添加 OCR 文字层再交给 babeldoc
    ocr_dir = task_dir / "ocr"
    ocr_input_file = None
    if _pdf_needs_ocr(pdf_file):
        if _stop_event.is_set():
            return
        _task_add_status(
            '<div class="log-line log-info">🔍 检测到扫描版 PDF，正在 OCR 识别文字（tesseract）...</div>'
        )
        ocr_dir.mkdir(parents=True, exist_ok=True)
        ocr_input_file = str(ocr_dir / os.path.basename(pdf_file))
        if _ocr_preprocess(pdf_file, lang_in, ocr_input_file):
            pdf_file = ocr_input_file
            _task_add_status(
                '<div class="log-line log-info">&#10003; OCR 预处理完成</div>'
            )
        else:
            ocr_input_file = None
            _task_add_status(
                '<div class="log-line log-warning">⚠ OCR 预处理失败，将直接尝试翻译原文件</div>'
            )
        if _stop_event.is_set():
            return

    def _handle_log_line(parsed: tuple[str, str, str], raw_stage: str | None) -> None:
        """处理一条解析后的日志：WARNING/ERROR→终端, INFO→web UI"""
        ts, level, msg = parsed
        stage = raw_stage or _detect_stage_from_msg(msg)

        if level in ("WARNING", "ERROR"):
            tag = "⚠️ " if level == "WARNING" else "❌ "
            print(f"{tag}{ts} {msg}", file=_sys.stderr)
            key = msg[:60]
            _error_warn_count[key] = _error_warn_count.get(key, 0) + 1
            with _task_lock:
                _TASK["warning_count"] += 1
                _TASK["last_warning"] = msg
            return

        # ---- INFO 级别 ----
        if stage:
            with _task_lock:
                completed_stages = _TASK["completed_stages"]
                current_stage = _TASK["current_stage"]
                stage_start = _TASK["stage_start"]
            if stage not in completed_stages and stage != current_stage:
                if current_stage and current_stage not in completed_stages:
                    elapsed = time.time() - stage_start
                    em, es = divmod(int(elapsed), 60)
                    duration = f"({em}m{es}s)" if em > 0 else f"({es}s)"
                    for name, _, label in STAGE_WEIGHTS:
                        if name == current_stage:
                            _task_add_status(
                                '<div class="log-line stage-done">'
                                f"&#10003; {label} 完成 "
                                f'<span class="stage-duration">{duration}</span></div>'
                            )
                            break
                    with _task_lock:
                        _TASK["completed_stages"].append(current_stage)
                new_stage_start = time.time()
                with _task_lock:
                    _TASK["stage_start"] = new_stage_start
                    _TASK["active_serial"] += 1
                    _TASK["current_stage"] = stage
                for name, _, label in STAGE_WEIGHTS:
                    if name == stage:
                        _task_add_status(
                            '<div class="log-line stage-start">'
                            f'<span class="spinner"></span> 正在{label}...</div>'
                        )
                        break

        _maybe_show_progress_info(msg)

    def _maybe_show_progress_info(msg: str) -> None:
        """精选部分 INFO 消息显示到 web UI"""
        show_patterns = [
            (r"start to translate", "&#128640; 开始翻译文档..."),
            (r"start merge results", "&#128300; 合并翻译结果..."),
            (r"finish merge results", "&#10003; 结果合并完成"),
            (r"Translation completed", "&#10003; 翻译段落处理完毕"),
            (r"Peak memory usage", None),  # None = 直接用 msg
            (r"Processing (.+)", None),
            (r"split points determined", None),
            (r"Only one part", "&#128196; 单文件模式，直接翻译"),
        ]
        for pattern, replacement in show_patterns:
            m = re.search(pattern, msg, re.IGNORECASE)
            if m:
                text = replacement if replacement else msg
                _task_add_status(f'<div class="log-line log-info">{text}</div>')
                return

    # 速度等级 → 参数映射
    speed_map = {
        "标准": {"qps": 4, "pool": 4, "no_glossary": False, "label": "标准"},
        "快速": {"qps": 10, "pool": 8, "no_glossary": False, "label": "快速"},
        "极速": {"qps": 20, "pool": 12, "no_glossary": True, "label": "极速"},
    }
    sp = speed_map.get(speed, speed_map["标准"])

    output_dir = str(task_dir)
    with _task_lock:
        _TASK["output_dir"] = output_dir
        _TASK["task_id"] = task_id

    cmd = [
        "babeldoc",
        "--files", pdf_file,
        "--openai",
        "--openai-model", model,
        "--openai-base-url", base_url.rstrip("/") + "/",
        "--openai-api-key", api_key,
        "--lang-in", lang_in,
        "--lang-out", lang_out,
        "--output", output_dir,
        "--report-interval", "1",
        "--qps", str(sp["qps"]),
        "--pool-max-workers", str(sp["pool"]),
        # 扫描版 PDF（>80% 扫描页）默认会抛 ScannedPDFError 直接退出且无输出；
        # 开启后自动启用 OCR workaround（白色底块 + 黑字覆盖），有隐藏文字层的扫描件可正常翻译
        "--auto-enable-ocr-workaround",
    ]
    if disable_thinking:
        cmd.extend(["--openai-thinking", "disabled"])
    if sp["no_glossary"]:
        cmd.append("--no-auto-extract-glossary")
    # 输出模式：UI 传英文值（both/dual_only/mono_only）
    if output_mode == "mono_only":
        cmd.append("--no-dual")
    elif output_mode == "dual_only":
        cmd.append("--no-mono")

    _task_add_status(
        '<div class="log-line log-info"><b>&#128196; 文件:</b> '
        f"{os.path.basename(pdf_file)}</div>"
    )
    _task_add_status(
        '<div class="log-line log-info"><b>&#127758; 模型:</b> '
        f"{model} ({base_url})</div>"
    )
    _task_add_status(
        '<div class="log-line log-info"><b>&#128272;</b> '
        f"{lang_in} &#8594; {lang_out}</div>"
    )
    _task_add_status(
        '<div class="log-line log-info"><b>&#9889;</b> '
        f'速度: {sp["label"]} (QPS={sp["qps"]}, 线程={sp["pool"]}'
        f'{", 跳过术语提取" if sp["no_glossary"] else ""})</div>'
    )
    _task_add_status('<div class="log-separator"></div>')
    _task_add_status(
        '<div class="log-line log-info"><b>&#128640; 翻译启动，请稍候...</b></div>'
    )

    def _finish(extra: str, result_file: str | None = None, status: str = "完成", output_files: list | None = None) -> None:
        with _task_lock:
            _TASK["extra_html"] = extra
            _TASK["result_file"] = result_file
            _TASK["running"] = False
            _TASK["finished"] = True
            overall_start = _TASK["overall_start"]
        total_elapsed = time.time() - overall_start
        tm, ts = divmod(int(total_elapsed), 60)
        duration = f"{tm}m{ts}s" if tm > 0 else f"{ts}s"
        _add_history_record(
            {
                "task_id": task_id,
                "filename": os.path.basename(pdf_file),
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "lang": f"{lang_in} → {lang_out}",
                "model": model,
                "settings": (
                    f'{sp["label"]} · '
                    + ("关闭思考" if disable_thinking else "开启思考") + " · "
                    + ("双语" if output_mode == "both" else ("双语对照" if output_mode == "dual_only" else "单语"))
                ),
                "duration": duration,
                "status": status,
                "original_file": original_file,
                "result_file": result_file,
                "result_files": output_files or [],
            }
        )

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        _running_process = process

        log_buffer = ""
        for line in process.stdout:
            if _stop_event.is_set():
                try:
                    process.terminate()
                except Exception:
                    pass
                break

            raw = line.rstrip()
            if not raw:
                continue
            with _task_lock:
                _TASK["last_activity"] = time.time()

            if raw.startswith(" ") or raw.startswith("\t") or not raw.startswith("["):
                log_buffer += " " + raw.strip()
            else:
                if log_buffer:
                    raw_stage = _detect_stage_from_raw(log_buffer)
                    parsed = _parse_log(log_buffer)
                    if parsed:
                        _handle_log_line(parsed, raw_stage)
                    else:
                        print(log_buffer, file=_sys.stderr)
                log_buffer = raw

        if log_buffer:
            raw_stage = _detect_stage_from_raw(log_buffer)
            parsed = _parse_log(log_buffer)
            if parsed:
                _handle_log_line(parsed, raw_stage)

        if _stop_event.is_set():
            _finish(
                '<div class="log-line log-warning" style="font-weight:bold">'
                "&#9209; 翻译已停止</div>",
                status="已停止",
            )
            return

        process.wait()

        if _stop_event.is_set():
            _finish(
                '<div class="log-line log-warning" style="font-weight:bold">'
                "&#9209; 翻译已停止</div>",
                status="已停止",
            )
            return

        if process.returncode != 0:
            _finish(
                '<div class="log-line log-error" style="font-weight:bold">'
                f"&#10060; 翻译失败 (exit code: {process.returncode})</div>",
                status="失败",
            )
            return

        # 标记所有阶段完成
        with _task_lock:
            current_stage = _TASK["current_stage"]
            completed_stages = _TASK["completed_stages"]
            stage_start = _TASK["stage_start"]
            overall_start = _TASK["overall_start"]
        if current_stage and current_stage not in completed_stages:
            elapsed = time.time() - stage_start
            em, es = divmod(int(elapsed), 60)
            duration = f"({em}m{es}s)" if em > 0 else f"({es}s)"
            for name, _, label in STAGE_WEIGHTS:
                if name == current_stage:
                    _task_add_status(
                        '<div class="log-line stage-done">'
                        f"&#10003; {label} 完成 "
                        f'<span class="stage-duration">{duration}</span></div>'
                    )
                    break
        with _task_lock:
            _TASK["current_stage"] = None
            _TASK["completed_stages"] = [name for name, _, _ in STAGE_WEIGHTS]

        output_files = []
        for ext in ["*.pdf", "*.PDF"]:
            output_files.extend(glob.glob(os.path.join(output_dir, ext)))
        if not output_files:
            for root, dirs, files in os.walk(output_dir):
                for f in files:
                    if f.lower().endswith(".pdf"):
                        output_files.append(os.path.join(root, f))
        if original_file:
            output_files = [f for f in output_files if os.path.abspath(f) != os.path.abspath(original_file)]
        # 排除 OCR 预处理的中间输入文件
        if ocr_input_file:
            output_files = [f for f in output_files if os.path.abspath(f) != os.path.abspath(ocr_input_file)]

        if output_files:
            total_elapsed = time.time() - overall_start
            tm, ts = divmod(int(total_elapsed), 60)
            total_duration = f"{tm}m{ts}s" if tm > 0 else f"{ts}s"
            extra = (
                '<div class="log-line log-success">'
                f"&#10004; 翻译完成！(总用时 {total_duration})</div>"
                '<div class="log-line log-info" style="margin-top:4px">输出文件:</div>'
                + "".join(
                    '<div class="log-line log-info" style="padding-left:12px;font-size:12px">'
                    f"&#128196; {os.path.basename(f)}</div>"
                    for f in output_files
                )
            )
            result_file = None
            for f in output_files:
                if "dual" in f.lower() or "bilingual" in f.lower():
                    result_file = f
                    break
            if not result_file:
                result_file = output_files[0]
            # 保存全部输出文件（dual + mono 等），供 UI 多文件下载
            with _task_lock:
                _TASK["result_files"] = output_files
            _finish(extra, result_file, output_files=output_files)
        else:
            _finish(
                '<div class="log-line log-error" style="font-weight:bold">'
                "&#9888; 未找到输出 PDF 文件，请检查日志。</div>",
                status="失败",
            )

    except FileNotFoundError:
        _finish(
            '<div class="log-line log-error" style="font-weight:bold">'
            "&#10060; 未找到 babeldoc 命令，请确保已正确安装 BabelDOC</div>"
            '<div class="log-line log-plain" style="font-size:12px">'
            "安装命令: pip install babeldoc</div>",
            status="失败",
        )
    except Exception as e:
        _finish(
            '<div class="log-line log-error" style="font-weight:bold">'
            f"&#10060; 错误: {e}</div>",
            status="失败",
        )


def translate_pdf(
    pdf_file,
    api_key,
    base_url,
    model,
    lang_in,
    lang_out,
    output_mode,
    speed,
    disable_thinking=False,
):
    """启动翻译任务并轮询展示进度。

    实际翻译在后台线程 `_run_translation_worker` 中运行，状态保存在全局
    `_TASK` 字典里。刷新浏览器页面会取消这里的轮询循环，但后台线程不受影响，
    翻译会继续进行；刷新后可通过页面自动或手动重新接上最新进度（见 `resume_progress`）。
    """
    disable_thinking = disable_thinking == "关闭"
    if not pdf_file:
        yield None, '<div class="log-line log-error" style="font-weight:bold">⚠️ 请先上传 PDF 文件</div>', None
        return
    if not api_key:
        yield None, '<div class="log-line log-error" style="font-weight:bold">⚠️ 请先选择或创建 LLM 预设（需包含 API Key）</div>', None
        return

    if _TASK["running"]:
        # 已有任务在跑，直接接上显示
        yield from resume_progress()
        return

    _reset_stop()
    with _task_lock:
        _TASK.update(
            running=True,
            status_lines=[],
            completed_stages=[],
            current_stage=None,
            stage_start=time.time(),
            overall_start=time.time(),
            active_serial=0,
            result_file=None,
            result_files=None,
            output_dir=None,
            task_id=None,
            finished=False,
            extra_html="",
            last_activity=time.time(),
            warning_count=0,
            last_warning="",
        )

    worker = threading.Thread(
        target=_run_translation_worker,
        args=(pdf_file, api_key, base_url, model, lang_in, lang_out, output_mode, speed, disable_thinking),
        daemon=True,
    )
    worker.start()

    yield from resume_progress()


def resume_progress():
    """轮询全局任务状态并 yield 给 UI，直到任务结束。
    可安全被取消（如页面刷新导致的生成器取消）——不会影响后台翻译线程。
    """
    last_len = -1
    next_heartbeat = 0.0
    while True:
        with _task_lock:
            running = _TASK["running"]
            finished = _TASK["finished"]
            extra_html = _TASK["extra_html"]
            result_files = _TASK.get("result_files") or (
                [_TASK["result_file"]] if _TASK.get("result_file") else None
            )
            output_dir = _TASK["output_dir"]
            cur_len = len(_TASK["status_lines"])

        if finished:
            yield result_files, _task_snapshot_html(extra_html), output_dir
            return

        now = time.monotonic()
        if cur_len != last_len or now >= next_heartbeat:
            last_len = cur_len
            next_heartbeat = now + 1.0
            yield None, _task_snapshot_html(), output_dir

        if not running:
            return

        time.sleep(0.5)


def cleanup_temp(temp_dir):
    """清理临时文件"""
    if temp_dir and os.path.exists(temp_dir):
        try:
            shutil.rmtree(temp_dir)
        except Exception:
            pass


# ---- OIDC 认证 ---- #
oauth = OAuth()
oauth.register(
    name="oidc",
    server_metadata_url=f"{OIDC_ISSUER.rstrip('/')}/.well-known/openid-configuration",
    client_id=OIDC_CLIENT_ID,
    client_secret=OIDC_CLIENT_SECRET,
    client_kwargs={"scope": "openid profile email"},
)


def _is_logged_in(request: Request) -> bool:
    return bool(request.session.get("user"))


def gradio_auth_dependency(request: Request) -> str | None:
    """供 gr.mount_gradio_app 使用：从 session 中取用户标识，未登录返回 None"""
    user = request.session.get("user") or {}
    return user.get("name") or user.get("sub")


async def auth_login(request: Request):
    """跳转到 OIDC provider 登录页"""
    redirect_uri = f"{APP_BASE_URL.rstrip('/')}/auth/callback"
    return await oauth.oidc.authorize_redirect(request, redirect_uri)


async def auth_callback(request: Request):
    """OIDC 登录回调：换取 token 并写入 session"""
    try:
        token = await oauth.oidc.authorize_access_token(request)
    except Exception as e:
        return RedirectResponse(url="/auth/login")
    user = token.get("userinfo") or {}
    request.session["user"] = {
        "sub": user.get("sub"),
        "name": user.get("name") or user.get("preferred_username") or user.get("email"),
        "email": user.get("email"),
    }
    return RedirectResponse(url="/")


async def auth_logout(request: Request):
    """清除本地会话，并跳转到 OIDC provider 登出端点"""
    request.session.pop("user", None)
    metadata = await oauth.oidc.load_server_metadata()
    end_session_endpoint = metadata.get("end_session_endpoint")
    if end_session_endpoint:
        return RedirectResponse(
            url=f"{end_session_endpoint}?post_logout_redirect_uri={APP_BASE_URL.rstrip('/')}"
        )
    return RedirectResponse(url="/")


class AuthRequiredMiddleware:
    """未登录时拦截页面访问，强制跳转到 OIDC provider 登录。
    仅放行登录/回调/登出路由以及 Gradio 静态资源、心跳等接口。
    """

    _PUBLIC_PREFIXES = ("/auth/", "/static", "/gradio_api/heartbeat", "/theme.css", "/favicon")

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if path.startswith(self._PUBLIC_PREFIXES):
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive=receive)
        if _is_logged_in(request):
            await self.app(scope, receive, send)
            return
        response = RedirectResponse(url="/auth/login")
        await response(scope, receive, send)


# 自定义样式。
# 注意：Gradio 6 已废弃 Blocks(css=...) 参数（仅 launch() 路径生效），
# 正式服务通过 mount_gradio_app 挂载、不走 launch()，因此改用
# gr.HTML 注入 <style>，保证两种启动路径下样式都生效。
CUSTOM_CSS = """
    /* ==================================================================
       BabelDOC · Neo 设计系统 v2
       品牌靛蓝渐变 / 玻璃拟态顶栏 / 面板化布局 / 终端风日志
       ================================================================== */

    :root {
        --brand: #6366F1;
        --brand-2: #8B5CF6;
        --brand-soft: rgba(99, 102, 241, 0.10);
        --brand-ring: rgba(99, 102, 241, 0.22);
        --bg: #F4F5F7;
        --panel: #FFFFFF;
        --panel-2: #FAFAFC;
        --border: #E7E8EC;
        --shadow: 0 1px 2px rgba(16,18,35,.04), 0 6px 20px rgba(16,18,35,.05);
        --shadow-lg: 0 4px 12px rgba(16,18,35,.06), 0 16px 40px rgba(16,18,35,.09);
        --tx: #17181F;
        --tx-2: #6E7080;
        --tx-3: #A2A4B2;
        --ok: #16A34A;
        --info: #0284C7;
        --warn: #D97706;
        --err: #DC2626;
        --log-bg: #FBFBFD;
        --log-border: #EBEBF0;
        --r-lg: 18px; --r-md: 12px; --r-sm: 8px;
        --mono: 'JetBrains Mono','SF Mono','Fira Code',Consolas,monospace;
    }
    html.dark, body.dark {
        --brand: #818CF8;
        --brand-2: #A78BFA;
        --brand-soft: rgba(129,140,248,.14);
        --brand-ring: rgba(129,140,248,.30);
        --bg: #0E0F14;
        --panel: #171923;
        --panel-2: #1C1F2B;
        --border: #2A2D3A;
        --shadow: 0 1px 2px rgba(0,0,0,.4), 0 8px 24px rgba(0,0,0,.35);
        --shadow-lg: 0 4px 12px rgba(0,0,0,.45), 0 18px 48px rgba(0,0,0,.5);
        --tx: #E9EAF0;
        --tx-2: #9B9DAD;
        --tx-3: #6B6D7C;
        --ok: #4ADE80; --info: #38BDF8; --warn: #FBBF24; --err: #F87171;
        --log-bg: #12141C;
        --log-border: #262936;
    }

    html, body { background: var(--bg) !important; }
    .gradio-container {
        background: var(--bg) !important;
        max-width: 1060px !important;
        margin: 0 auto !important;
        font-feature-settings: "tnum";
    }
    ::-webkit-scrollbar { width: 8px; height: 8px; }
    ::-webkit-scrollbar-thumb { background: rgba(128,130,150,.35); border-radius: 8px; }
    ::-webkit-scrollbar-thumb:hover { background: rgba(128,130,150,.55); }
    ::-webkit-scrollbar-track { background: transparent; }
    footer { display: none !important; }

    /* ===== Hero 顶栏 ===== */
    .hero {
        background: linear-gradient(120deg, #4F46E5 0%, #7C3AED 55%, #9333EA 100%) !important;
        border-radius: var(--r-lg) !important;
        border: none !important;
        box-shadow: 0 8px 28px rgba(99,102,241,.35) !important;
        padding: 0 !important;
        margin: 16px 0 14px !important;
        position: relative;
        overflow: hidden;
        flex-wrap: nowrap !important;
        align-items: center !important;
        gap: 12px !important;
    }
    .hero::after {
        content: ""; position: absolute; right: -60px; top: -80px;
        width: 260px; height: 260px; border-radius: 50%;
        background: rgba(255,255,255,.08); pointer-events: none;
    }
    .hero::before {
        content: ""; position: absolute; right: 90px; bottom: -110px;
        width: 200px; height: 200px; border-radius: 50%;
        background: rgba(255,255,255,.06); pointer-events: none;
    }
    .hero-inner { flex: 1; padding: 20px 24px; position: relative; z-index: 1; }
    .hero-brand { display: flex; align-items: center; gap: 14px; }
    .hero-logo {
        display: inline-flex; align-items: center; justify-content: center;
        width: 46px; height: 46px; font-size: 24px;
        background: rgba(255,255,255,.16);
        border: 1px solid rgba(255,255,255,.25);
        border-radius: 14px; backdrop-filter: blur(6px);
    }
    .hero h1 {
        margin: 0 !important; font-size: 1.35rem !important; font-weight: 700 !important;
        color: #fff !important; letter-spacing: -.01em; line-height: 1.2;
        -webkit-text-fill-color: #fff !important;
        background: none !important;
    }
    .hero p {
        margin: 3px 0 0 !important; font-size: .82rem !important;
        color: rgba(255,255,255,.85) !important;
    }
    .hero .theme-toggle-row {
        margin: 0 !important; padding: 0 16px 0 0 !important;
        justify-content: flex-end !important; position: relative; z-index: 1;
    }
    .theme-toggle-row { justify-content: flex-end !important; }
    .hero .theme-toggle-row button {
        background: rgba(255,255,255,.15) !important;
        border: 1px solid rgba(255,255,255,.3) !important;
        color: #fff !important;
        border-radius: 999px !important;
        font-size: 12px !important; padding: 5px 14px !important;
        box-shadow: none !important;
        backdrop-filter: blur(6px);
    }
    .hero .theme-toggle-row button:hover { background: rgba(255,255,255,.25) !important; }

    /* ===== Tabs 分段控件 ===== */
    .tab-nav, .tab-container > .tab-nav {
        border: 1px solid var(--border) !important;
        background: var(--panel) !important;
        border-radius: var(--r-md) !important;
        padding: 4px !important;
        box-shadow: var(--shadow) !important;
        gap: 4px;
    }
    .tab-nav button {
        border-radius: var(--r-sm) !important;
        font-size: 13.5px !important; font-weight: 500 !important;
        color: var(--tx-2) !important; padding: 8px 18px !important;
    }
    .tab-nav button.selected {
        background: var(--brand-soft) !important;
        color: var(--brand) !important; font-weight: 600 !important;
    }

    /* ===== 步骤条（点线式） ===== */
    .step-bar {
        display: flex; align-items: center; justify-content: center;
        flex-wrap: wrap; gap: 2px; row-gap: 8px;
        margin: 0 0 14px; padding: 12px 10px;
        background: var(--panel);
        border: 1px solid var(--border);
        border-radius: var(--r-md);
        box-shadow: var(--shadow);
    }
    .step-item {
        display: inline-flex; align-items: center; gap: 8px;
        font-size: 12.5px; color: var(--tx-2); font-weight: 500;
        padding: 5px 12px; border-radius: 999px;
        background: var(--panel-2); border: 1px solid var(--border);
    }
    .step-num {
        display: inline-flex; align-items: center; justify-content: center;
        width: 18px; height: 18px; border-radius: 50%;
        background: var(--border); color: var(--tx-2);
        font-size: 10.5px; font-weight: 700;
    }
    .step-sep {
        width: 18px; height: 1.5px;
        background: linear-gradient(90deg, var(--border), transparent);
        margin: 0 2px;
    }

    /* ===== 面板（卡片） ===== */
    .step-card {
        border-radius: var(--r-lg) !important;
        border: 1px solid var(--border) !important;
        box-shadow: var(--shadow) !important;
        padding: 16px 18px !important;
        margin-bottom: 14px !important;
        background: var(--panel) !important;
        transition: box-shadow .25s, border-color .25s;
    }
    .step-card:hover { box-shadow: var(--shadow-lg); }
    /* 面板标题（gr.HTML 注入） */
    .panel-head { display: flex; align-items: center; gap: 11px; margin-bottom: 14px; }
    .panel-ico {
        display: inline-flex; align-items: center; justify-content: center;
        width: 34px; height: 34px; font-size: 16px;
        background: var(--brand-soft);
        border: 1px solid var(--brand-ring);
        border-radius: 10px;
    }
    .panel-title { font-size: 14px; font-weight: 700; color: var(--tx); line-height: 1.25; }
    .panel-sub { font-size: 11.5px; color: var(--tx-3); margin-top: 1px; }
    /* 兼容旧 markdown 标题 */
    .step-card h4, .step-card .prose h4 {
        margin: 0 0 12px !important; font-size: 14px !important; font-weight: 700 !important;
        color: var(--tx) !important; padding-bottom: 10px;
        border-bottom: 1px solid var(--log-border);
    }

    .workflow-col { gap: 4px !important; }
    .action-row { margin: 0 !important; }

    /* ===== 桌面端横版：左（上传+语言） 右（LLM+操作） ===== */
    .desktop-split {
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        align-items: stretch !important;
        gap: 14px !important;
        margin-bottom: 0 !important;
    }
    .col-left  { flex: 5 1 0 !important; min-width: 0 !important; display: flex !important; flex-direction: column !important; }
    .col-right { flex: 6 1 0 !important; min-width: 0 !important; display: flex !important; flex-direction: column !important; }
    .col-left > *, .col-right > * { margin-bottom: 0 !important; }
    .col-left > * + *, .col-right > * + * { margin-top: 14px !important; }
    /* 左列：上传卡片拉伸填满剩余高度（拖拽区天然适合长高），按钮沉底对齐 */
    .col-left > .upload-card {
        flex: 1 1 auto !important;
        display: flex !important;
        flex-direction: column !important;
    }
    .upload-card > *:last-child { flex: 1 1 auto !important; display: flex !important; flex-direction: column !important; }
    /* 逐级弹性传导，让虚线拖拽框撑满整个剩余高度 */
    .upload-card > *:last-child > * { flex: 1 1 auto !important; display: flex !important; flex-direction: column !important; }
    .upload-card > *:last-child > * > * { flex: 1 1 auto !important; display: flex !important; flex-direction: column !important; }
    .upload-card .placeholder[class*="svelte"] {
        flex: 1 1 auto !important;
        height: 100% !important;
        min-height: 240px !important;
    }
    .col-left > .action-row { margin-top: auto !important; }
    .llm-card { display: flex !important; flex-direction: column !important; }
    /* 当前生效配置：品牌色信息面板 */
    .llm-summary {
        background: var(--brand-soft) !important;
        border: 1px solid var(--brand-ring) !important;
        border-radius: var(--r-md) !important;
        padding: 10px 14px !important;
        margin-top: 10px !important;
        font-size: 12.5px !important;
        line-height: 1.7 !important;
        color: var(--tx) !important;
    }
    .llm-summary p { margin: 0 !important; }
    /* 操作按钮沉到与左列底部对齐；卡片本身保持内容自然高度 */

    /* ===== 按钮 ===== */
    .gradio-container button {
        border-radius: var(--r-md) !important;
        font-weight: 550 !important;
        transition: transform .12s ease, box-shadow .2s ease, filter .2s ease, background .2s ease;
    }
    .gradio-container button:active { transform: scale(.97); }
    .gradio-container button.primary, button.variant-primary {
        background: linear-gradient(135deg, #6366F1 0%, #8B5CF6 100%) !important;
        border: none !important; color: #fff !important;
        box-shadow: 0 4px 14px rgba(99,102,241,.4) !important;
    }
    .gradio-container button.primary:hover, button.variant-primary:hover {
        filter: brightness(1.07);
        box-shadow: 0 6px 20px rgba(99,102,241,.5) !important;
    }
    .gradio-container button.secondary, button.variant-secondary {
        background: var(--panel) !important;
        border: 1px solid var(--border) !important;
        color: var(--tx) !important;
    }
    .gradio-container button.secondary:hover, button.variant-secondary:hover {
        border-color: var(--brand) !important; color: var(--brand) !important;
    }
    .gradio-container button.stop, button.variant-stop {
        background: var(--panel) !important;
        border: 1px solid rgba(220,38,38,.35) !important;
        color: var(--err) !important;
    }
    .gradio-container button.stop:hover, button.variant-stop:hover {
        background: rgba(220,38,38,.07) !important;
    }

    /* ===== 输入控件 ===== */
    .gradio-container input:not([type="checkbox"]):not([type="radio"]),
    .gradio-container select, .gradio-container textarea {
        border-radius: var(--r-sm) !important;
        transition: border-color .2s, box-shadow .2s;
    }
    .gradio-container input:focus, .gradio-container select:focus, .gradio-container textarea:focus {
        border-color: var(--brand) !important;
        box-shadow: 0 0 0 3px var(--brand-ring) !important;
    }
    .gradio-container label span, .gradio-container .wrap label {
        font-size: 12px !important; color: var(--tx-2) !important; font-weight: 550 !important;
    }

    /* ===== 日志终端 ===== */
    .log-panel {
        font-family: var(--mono) !important;
        font-size: 12.5px !important; line-height: 1.6 !important;
        height: auto !important; min-height: 180px; max-height: 560px;
        overflow-y: auto !important;
        background: var(--log-bg) !important;
        border: 1px solid var(--log-border) !important;
        border-radius: var(--r-md) !important;
        padding: 12px 14px !important;
        color: var(--tx);
        flex-shrink: 0;
    }
    .log-line {
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        margin: 0; line-height: 1.65; border-radius: 4px; padding: 0 6px;
    }
    .log-line b { font-weight: 600; }
    .log-time { color: var(--tx-3); font-size: 11px; font-family: var(--mono); }
    .log-error  { color: var(--err); background: rgba(220,38,38,.07); }
    .log-warning { color: var(--warn); background: rgba(217,119,6,.07); }
    .log-success { color: var(--ok); background: rgba(22,163,74,.08); font-weight: 600; }
    .log-info   { color: var(--tx); }
    .log-plain  { color: var(--tx-3); }
    .log-separator { height: 0; border-bottom: 1px solid var(--log-border); margin: 5px 0; }
    .stage-done  { color: var(--ok); }
    .stage-start { color: var(--info); }
    .stage-duration { color: var(--tx-3); font-size: 11px; }

    /* ===== 动画 ===== */
    .spinner {
        display: inline-block; width: 12px; height: 12px;
        border: 2px solid var(--info); border-top-color: transparent;
        border-radius: 50%; animation: spin .8s linear infinite;
        vertical-align: middle; margin-right: 2px;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    .alive-dot {
        display: inline-block; width: 8px; height: 8px;
        background: var(--ok); border-radius: 50%;
        animation: pulse-dot 1s ease-in-out infinite;
        vertical-align: middle; margin-right: 4px;
        box-shadow: 0 0 0 3px rgba(22,163,74,.15);
    }
    @keyframes pulse-dot {
        0%, 100% { opacity: 1; transform: scale(1); }
        50%      { opacity: .4; transform: scale(.7); }
    }
    .elapsed { color: var(--tx-3); font-size: 11px; font-family: var(--mono); }

    /* ===== 进度条 ===== */
    .progress-area {
        margin-bottom: 10px; padding-bottom: 10px;
        border-bottom: 1px solid var(--log-border);
    }
    .progress-text { font-size: 12.5px; display: block; margin-bottom: 6px; color: var(--tx); }
    .progress-bar {
        width: 100%; height: 12px;
        background: var(--log-border); border-radius: 999px;
        overflow: hidden; display: flex;
        border: none;
    }
    .progress-bar > div {
        height: 100%;
        border-right: 2px solid var(--panel);
        transition: background .3s;
    }
    .pg-done    { background: linear-gradient(180deg,#22C55E,#16A34A); }
    .pg-current { background: linear-gradient(180deg,#38BDF8,#0284C7); animation: pulse-current 1.2s ease-in-out infinite; }
    .pg-pending { background: rgba(128,130,150,.25); }
    @keyframes pulse-current { 0%,100%{opacity:1} 50%{opacity:.6} }
    .progress-bar > div[title] { cursor: help; }

    /* ===== 预设弹窗 ===== */
    .preset-modal-overlay {
        position: fixed !important;
        top: 0; left: 0; right: 0; bottom: 0;
        width: 100%; height: 100%;
        background: rgba(10,10,25,.5);
        backdrop-filter: blur(6px);
        -webkit-backdrop-filter: blur(6px);
        z-index: 1000; overflow-y: auto;
        padding: 16px;
        /* flex + margin:auto 实现垂直水平居中：
           内容超出屏幕时 auto margin 自动归零，顶部不会被裁切、仍可滚动 */
        display: flex !important;
    }
    .preset-modal-card {
        background: var(--panel) !important;
        border-radius: var(--r-lg) !important;
        border: 1px solid var(--border) !important;
        box-shadow: var(--shadow-lg) !important;
        width: 100%; max-width: 540px;
        margin: auto !important;
        padding: 22px !important;
    }
    .preset-modal-card > div { gap: 6px !important; }
    .preset-modal-card .form { gap: 6px !important; }
    .preset-modal-card fieldset { padding: 6px 10px !important; margin: 0 !important; }
    .preset-summary { font-size: 12.5px; color: var(--tx-2); margin: 6px 0 0; }

    /* ===== 表格 ===== */
    .gradio-container table { border-radius: var(--r-md); overflow: hidden; }
    .gradio-container thead th {
        background: var(--brand-soft) !important;
        color: var(--tx) !important; font-weight: 650 !important; font-size: 12.5px !important;
    }
    .gradio-container tbody td { font-size: 12.5px !important; }

    /* ===== 响应式 ===== */
    @media (min-width: 1200px) {
        .gradio-container { max-width: 1240px !important; }
        .hero h1 { font-size: 1.5rem !important; }
        .log-panel { font-size: 13px !important; max-height: 640px; }
    }
    @media (max-width: 1199px) and (min-width: 1024px) {
        .gradio-container { max-width: 96vw !important; }
    }
    @media (max-width: 1023px) {
        .desktop-split { flex-direction: column !important; }
        .col-left, .col-right { width: 100% !important; min-width: 0 !important; }
        .col-left > * + *, .col-right > * + * { margin-top: 0 !important; }
        .col-left > *, .col-right > * { margin-bottom: 14px !important; }
        .col-left > .action-row { margin-top: 0 !important; }
        .col-left > .upload-card { flex: 0 0 auto !important; }
    }
    @media (max-width: 768px) {
        .gradio-container { max-width: 100vw !important; padding: 0 8px !important; }
        .hero { margin-top: 8px; }
        .hero-inner { padding: 14px 16px; }
        .hero-logo { width: 38px; height: 38px; font-size: 19px; }
        .hero h1 { font-size: 1.1rem !important; }
        .hero p { font-size: .74rem !important; }
        .step-card { padding: 12px 14px !important; border-radius: var(--r-md) !important; }
        .step-bar { padding: 8px 6px; }
        .step-item { font-size: 11px; gap: 5px; padding: 4px 8px; }
        .step-num { width: 16px; height: 16px; font-size: 9.5px; }
        .step-sep { width: 10px; }
        .log-panel { font-size: 11px !important; min-height: 140px; max-height: 320px; padding: 8px !important; }
        .progress-bar { height: 10px; }
        .gradio-container button { font-size: 13px !important; }
        .gradio-container input, .gradio-container select, .gradio-container textarea { font-size: 13px !important; }
        .tab-nav button { font-size: 12.5px !important; padding: 7px 10px !important; }

        .preset-modal-card { padding: 14px !important; }
    }
"""


# 创建 Gradio 界面
with gr.Blocks(
    title="BabelDOC 论文翻译 - LLM",
    theme=gr.themes.Soft(),
) as demo:
    # 注入自定义样式（见上方 CUSTOM_CSS 注释说明）
    gr.HTML("<style>" + CUSTOM_CSS + "</style>")

    # 状态变量
    temp_output_dir = gr.State(None)
    # LLM 预设列表与当前生效预设 id
    presets_state = gr.State([])
    active_id_state = gr.State(None)

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
    def _panel_head(icon: str, num: str, title: str, sub: str) -> str:
        return (
            f'<div class="panel-head">'
            f'<span class="panel-ico">{icon}</span>'
            f'<div><div class="panel-title"><span class="panel-num">{num}</span>{title}</div>'
            f'<div class="panel-sub">{sub}</div></div>'
            f"</div>"
        )

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
                            gr.HTML(_panel_head("📥", "1", "上传文件", "拖拽或点击上传 PDF 文献"))
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
                            resume_btn = gr.Button("🔄 恢复进度", variant="secondary", size="lg", scale=1)
                            stop_btn = gr.Button("⏹ 停止", variant="stop", size="lg", scale=1)

                    with gr.Column(elem_classes="col-right"):
                        with gr.Group(elem_classes="step-card llm-card"):
                            gr.HTML(_panel_head("🧠", "2", "LLM 模型配置", "选择或管理 API 预设"))
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
                            config_status = gr.Markdown("")
                            # 隐藏状态：当前生效的 api_key / base_url / model，供翻译任务使用
                            active_api_key = gr.State("")
                            active_base_url = gr.State("")
                            active_model = gr.State("")

                        with gr.Group(elem_classes="step-card"):
                            gr.HTML(_panel_head("🌐", "3", "语言与速度", "翻译方向与输出偏好"))
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
                    gr.HTML(_panel_head("📡", "4", "翻译日志与进度", "实时进度与终端日志"))
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
                    datatype=["str", "str", "str", "str", "str"],
                    interactive=False,
                    wrap=True,
                )
                with gr.Row():
                    history_select = gr.Dropdown(
                        label="选择历史任务",
                        choices=[],
                        value=None,
                        scale=3,
                    )
                    history_refresh_btn = gr.Button("🔄 刷新", scale=1)
                with gr.Row():
                    history_download_original_btn = gr.Button("📥 下载原文", scale=1)
                    history_download_result_btn = gr.Button("📥 下载译文", scale=1)
                    history_delete_btn = gr.Button("🗑️ 删除", variant="stop", scale=1)
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
            model_test_btn = gr.Button("🧪 模型测试（可行性 / 性能 / 思考开关）", variant="secondary")
            model_test_status = gr.Markdown("")
            preset_edit_status = gr.Markdown("")
            with gr.Row():
                save_preset_btn = gr.Button("💾 保存", variant="primary", scale=1)
                apply_preset_btn = gr.Button(
                    "✅ 应用并关闭", variant="primary", scale=1
                )
                close_preset_modal_btn = gr.Button("✖️ 关闭", scale=1)

    # 事件绑定
    # 注意：cancels 需要指向真正承载长耗时任务（translate_pdf/resume_progress）的
    # 事件对象本身，因此按钮 loading 态的切换放在 .then() 链的前后，
    # 而 translate_event/resume_event 变量始终绑定在核心任务事件上。
    translate_btn.click(
        fn=lambda: gr.update(value="⏳ 翻译中...", interactive=False),
        inputs=[],
        outputs=[translate_btn],
    )
    translate_event = translate_btn.click(
        fn=translate_pdf,
        inputs=[
            pdf_input,
            active_api_key,
            active_base_url,
            active_model,
            lang_in,
            lang_out,
            output_mode,
            speed,
            thinking_switch,
        ],
        outputs=[result_download, log_output, temp_output_dir],
        api_name="translate",
    )
    translate_event.then(
        fn=lambda: gr.update(value="🚀 开始翻译", interactive=True),
        inputs=[],
        outputs=[translate_btn],
    )

    # 恢复进度：重新接上后台正在运行（或已结束）的任务状态
    # 用于翻译过程中刷新页面后，手动点击接回最新进度
    resume_btn.click(
        fn=lambda: gr.update(value="⏳ 翻译中...", interactive=False),
        inputs=[],
        outputs=[translate_btn],
    )
    resume_event = resume_btn.click(
        fn=resume_progress,
        inputs=[],
        outputs=[result_download, log_output, temp_output_dir],
    )
    resume_event.then(
        fn=lambda: gr.update(value="🚀 开始翻译", interactive=True),
        inputs=[],
        outputs=[translate_btn],
    )

    # 停止按钮：杀死子进程 + 取消 Gradio 事件（补充取消恢复进度的轮询）
    stop_btn.click(
        fn=lambda: (request_stop(), "⏹ 已请求停止")[1],
        inputs=[],
        outputs=[config_status],
        cancels=[translate_event, resume_event],
    ).then(
        fn=lambda: gr.update(value="🚀 开始翻译", interactive=True),
        inputs=[],
        outputs=[translate_btn],
    )

    # ---- LLM 预设管理事件 ----
    def _thinking_switch_update(p):
        """根据预设的测试结论生成思考模式开关的更新"""
        if p and p.get("thinking_supported"):
            val = "关闭" if p.get("thinking_disabled") else "开启"
            return gr.update(interactive=True, value=val, info="关闭后翻译更快更省")
        if p and p.get("thinking_supported") is False:
            return gr.update(interactive=False, value="开启", info="该模型不支持关闭思考")
        return gr.update(interactive=False, value="开启", info="先在预设管理中运行「🧪 模型测试」")

    def _persist_thinking_choice(presets, active_id, val):
        """把思考模式开关的选择写入当前生效预设并保存"""
        p = get_preset_by_id(presets, active_id)
        if p:
            p["thinking_disabled"] = val == "关闭"
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
            )
        return (
            gr.update(choices=_preset_choices(presets), value=preset_id),
            p.get("api_key", ""),
            p.get("base_url", ""),
            p.get("model", ""),
            _preset_summary(p),
            _thinking_switch_update(p),
        )

    # 主面板下拉框：切换预设立即生效
    preset_select.input(
        fn=lambda presets, preset_id: _apply_preset_ui(presets, preset_id)[1:],
        inputs=[presets_state, preset_select],
        outputs=[active_api_key, active_base_url, active_model, preset_summary, thinking_switch],
    )

    # 测试当前预设的 API 连通性：先立即给出提示并禁用按钮，结束后恢复
    test_conn_btn.click(
        fn=lambda: (gr.update(interactive=False), "🔄 正在测试连接，请稍候..."),
        inputs=[],
        outputs=[test_conn_btn, config_status],
    )
    test_conn_event = test_conn_btn.click(
        fn=test_preset_connection,
        inputs=[active_api_key, active_base_url, active_model],
        outputs=[config_status],
    )
    test_conn_event.then(
        fn=lambda: gr.update(interactive=True),
        inputs=[],
        outputs=[test_conn_btn],
    )

    # 思考模式开关变化：持久化到当前生效预设，刷新页面后仍保留
    thinking_switch.change(
        fn=lambda presets, active_id, val: (
            _persist_thinking_choice(presets, active_id, val)
        ),
        inputs=[presets_state, active_id_state, thinking_switch],
        outputs=[presets_state],
    )

    # 模型能力测试（弹窗内）：测试结论写入所选预设并持久化
    model_test_btn.click(
        fn=lambda: "🧪 正在测试模型（连通性 / 性能 / 思考开关），请稍候...",
        inputs=[],
        outputs=[model_test_status],
    ).then(
        fn=test_model_capabilities,
        inputs=[presets_state, preset_radio, active_id_state, preset_api_key, preset_base_url, preset_model],
        outputs=[model_test_status, presets_state],
    )

    # 打开弹窗：以“新建预设”的空表单开始
    def open_preset_modal(presets):
        return (
            gr.update(visible=True),
            gr.update(choices=_preset_choices(presets), value=None),
            "",
            "",
            "",
            "",
            "",
        )

    manage_preset_btn.click(
        fn=open_preset_modal,
        inputs=[presets_state],
        outputs=[
            preset_modal,
            preset_radio,
            preset_name,
            preset_api_key,
            preset_base_url,
            preset_model,
            preset_edit_status,
        ],
    )

    close_preset_modal_btn.click(
        fn=lambda: gr.update(visible=False),
        inputs=[],
        outputs=[preset_modal],
    )

    # 弹窗内选中某个预设：载入编辑表单
    def load_preset_to_editor(presets, preset_id):
        p = get_preset_by_id(presets, preset_id)
        if not p:
            return "", "", "", "", ""
        return (
            p.get("name", ""),
            p.get("api_key", ""),
            p.get("base_url", ""),
            p.get("model", ""),
            "",
        )

    preset_radio.input(
        fn=load_preset_to_editor,
        inputs=[presets_state, preset_radio],
        outputs=[
            preset_name,
            preset_api_key,
            preset_base_url,
            preset_model,
            preset_edit_status,
        ],
    )

    # 新建预设：清空编辑表单并取消 radio 选中
    new_preset_btn.click(
        fn=lambda: (
            gr.update(value=None),
            "",
            "",
            "",
            "",
            "🆕 请填写新预设信息后点击「保存」",
        ),
        inputs=[],
        outputs=[
            preset_radio,
            preset_name,
            preset_api_key,
            preset_base_url,
            preset_model,
            preset_edit_status,
        ],
    )

    # 保存预设：radio 选中了预设则更新，否则新建
    def handle_save_preset(presets, active_id, edit_id, name, api_key, base_url, model):
        name = (name or "").strip()
        if not name:
            return presets, active_id, "⚠️ 请填写预设名称"
        presets = list(presets)
        target = get_preset_by_id(presets, edit_id) if edit_id else None
        if target:
            target.update(
                name=name,
                api_key=api_key or "",
                base_url=(base_url or "").strip(),
                model=(model or "").strip(),
            )
            new_id = target["id"]
            msg = "✅ 预设已更新"
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
        )

    save_preset_btn.click(
        fn=handle_save_preset,
        inputs=[
            presets_state,
            active_id_state,
            preset_radio,
            preset_name,
            preset_api_key,
            preset_base_url,
            preset_model,
        ],
        outputs=[presets_state, active_id_state, preset_edit_status, preset_radio],
    )

    # 删除当前 radio 选中的预设
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

    delete_preset_btn.click(
        fn=handle_delete_preset,
        inputs=[presets_state, active_id_state, preset_radio],
        outputs=[presets_state, active_id_state, preset_radio, preset_edit_status],
    ).then(
        fn=lambda: ("", "", "", ""),
        inputs=[],
        outputs=[preset_name, preset_api_key, preset_base_url, preset_model],
    )

    # 应用并关闭：将 radio 选中的预设设为当前生效预设
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
        )

    apply_preset_btn.click(
        fn=handle_apply_preset,
        inputs=[presets_state, active_id_state, preset_radio],
        outputs=[
            presets_state,
            active_id_state,
            preset_modal,
            preset_select,
            active_api_key,
            active_base_url,
            active_model,
            preset_summary,
            thinking_switch,
        ],
    )

    def clear_all(temp_dir):
        cleanup_temp(temp_dir)
        return None, None, None, ""

    clear_btn.click(
        fn=clear_all,
        inputs=[temp_output_dir],
        outputs=[pdf_input, result_download, temp_output_dir, log_output],
    )

    # ---- 历史记录事件 ----
    history_refresh_btn.click(
        fn=refresh_history,
        inputs=[],
        outputs=[history_table, history_select],
    )

    # 翻译/恢复进度结束后，顺带刷新历史记录列表
    translate_event.then(
        fn=refresh_history,
        inputs=[],
        outputs=[history_table, history_select],
    )
    resume_event.then(
        fn=refresh_history,
        inputs=[],
        outputs=[history_table, history_select],
    )

    history_select.change(
        fn=show_history_files,
        inputs=[history_select],
        outputs=[history_original_file, history_result_file],
    )

    history_download_original_btn.click(
        fn=lambda task_id: download_history_file(task_id, "original"),
        inputs=[history_select],
        outputs=[history_original_file],
    )
    history_download_result_btn.click(
        fn=lambda task_id: download_history_file(task_id, "result"),
        inputs=[history_select],
        outputs=[history_result_file],
    )
    history_delete_btn.click(
        fn=delete_history_selected,
        inputs=[history_select],
        outputs=[history_table, history_select, history_original_file, history_result_file],
    )

    # 启动时加载配置：恢复预设列表与当前生效预设
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
        )

    demo.load(
        fn=load_config_ui,
        inputs=[],
        outputs=[
            presets_state,
            active_id_state,
            preset_select,
            active_api_key,
            active_base_url,
            active_model,
            preset_summary,
            thinking_switch,
        ],
    )

    demo.load(
        fn=refresh_history,
        inputs=[],
        outputs=[history_table, history_select],
    )

    # 主题初始化：读取本地存储的偏好（默认跟随系统）
    # Gradio 自身的深色样式以 <body> 是否带 .dark 类为准，
    # 因此这里复用同一套机制，保证组件文字/背景色都能正确联动。
    demo.load(
        fn=None,
        inputs=[],
        outputs=[],
        js="""
        () => {
            const labels = {system: '🖥️ 跟随系统', light: '☀️ 亮色', dark: '🌙 暗色'};
            const saved = localStorage.getItem('babeldoc-theme') || 'system';
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            const shouldBeDark = saved === 'dark' || (saved === 'system' && prefersDark);
            document.documentElement.classList.toggle('dark', shouldBeDark);
            document.body.classList.toggle('dark', shouldBeDark);
            const btn = document.querySelector('.theme-toggle-row button');
            if (btn) btn.textContent = labels[saved];
        }
        """,
    )

    # 主题切换按钮：跟随系统 → 亮色 → 暗色 → 循环
    theme_toggle_btn.click(
        fn=None,
        inputs=[],
        outputs=[],
        js="""
        () => {
            const order = ['system', 'light', 'dark'];
            const labels = {system: '🖥️ 跟随系统', light: '☀️ 亮色', dark: '🌙 暗色'};
            const current = localStorage.getItem('babeldoc-theme') || 'system';
            const next = order[(order.indexOf(current) + 1) % order.length];
            localStorage.setItem('babeldoc-theme', next);
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            const shouldBeDark = next === 'dark' || (next === 'system' && prefersDark);
            document.documentElement.classList.toggle('dark', shouldBeDark);
            document.body.classList.toggle('dark', shouldBeDark);
            const btn = document.querySelector('.theme-toggle-row button');
            if (btn) btn.textContent = labels[next];
        }
        """,
    )

    # 关闭后清理临时文件
    demo.unload(cleanup_temp)

    # 示例
    gr.Markdown(
        """
        ---
        ### 💡 使用说明
        1. **安装 BabelDOC**: `pip install babeldoc`
        2. **创建 LLM 预设**: 点击「⚙️ 管理预设」填写名称、API Key、Base URL 与模型
        3. **上传 PDF**: 选择需要翻译的论文
        4. **切换预设**: 主面板下拉框即可快速切换不同 LLM（DeepSeek / OpenAI 兼容接口均可）
        5. **开始翻译**: 点击按钮等待完成，结果可直接下载
        """
    )


if __name__ == "__main__":
    if AUTH_ENABLED:
        if not OIDC_ISSUER or not OIDC_CLIENT_ID or not OIDC_CLIENT_SECRET:
            raise SystemExit(
                "AUTH_ENABLED=true requires OIDC_ISSUER, OIDC_CLIENT_ID, "
                "and OIDC_CLIENT_SECRET"
            )
        # 启用 OIDC 登录认证：创建独立 FastAPI app，挂载认证路由与中间件，
        # 再将 Gradio 挂载到该 app 上，最后用 uvicorn 启动
        import uvicorn
        from fastapi import FastAPI

        app = FastAPI()
        app.add_route("/auth/login", auth_login, methods=["GET"])
        app.add_route("/auth/callback", auth_callback, methods=["GET"])
        app.add_route("/auth/logout", auth_logout, methods=["GET"])
        # 中间件后添加的先执行，AuthRequiredMiddleware 需要用到 request.session，
        # 因此必须晚于 SessionMiddleware 添加，使其运行在 SessionMiddleware 外层
        app.add_middleware(AuthRequiredMiddleware)
        app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, same_site="lax")

        gr.mount_gradio_app(app, demo, path="/", auth_dependency=gradio_auth_dependency)
        uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 7865)))
    else:
        print(
            "⚠️ AUTH_ENABLED 未开启，本次启动不启用登录认证保护",
            file=_sys.stderr,
        )
        demo.launch(
            server_name="0.0.0.0",
            server_port=int(os.environ.get("PORT", 7865)),
            show_error=True,
        )
