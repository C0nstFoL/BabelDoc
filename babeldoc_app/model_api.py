"""Model connectivity, performance and reasoning capability probes."""

import json
import time
import urllib.error
import urllib.request
from datetime import datetime
from statistics import median

from .presets import (
    get_preset_by_id,
    save_config,
)


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


def _probe_chat(
    api_key, base_url, model, extra=None, prompt="hi", max_tokens=400, timeout=60
):
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
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
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


REASONING_EFFORT_LEVELS = ("low", "high", "max")
GLM53_MODELS = {"glm-5.3", "glm-5.3-flash", "glm-5.3-flashx"}
REASONING_EFFORT_TEST_VERSION = 3


def _is_glm53_model(model):
    return (model or "").lower().split("/")[-1] in GLM53_MODELS


def _reasoning_measure(response):
    """分别提取可见思考字数和接口报告的推理 token 数。"""
    msg = (response.get("choices") or [{}])[0].get("message") or {}
    usage = response.get("usage") or {}
    tokens = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
    return len(_msg_reasoning(msg)), tokens


def test_model_capabilities(presets, edit_id, active_id, api_key, base_url, model):
    """模型能力测试：可行性、性能、思考开关及 GLM-5.3 推理深度。

    返回 (测试报告 Markdown, 更新后的 presets)。测试结论写入对应预设并持久化，
    供主界面的思考模式和推理深度控件判断是否可调。
    """
    if not api_key or not base_url:
        return "⚠️ 请先填写 API Key 与 Base URL 再测试", presets

    report = [f"### 🧪 模型测试报告：`{model or '(未填写)'}`"]
    performance = "未完成"

    effort_supported = None
    effort_ordered = None

    def finish(supported=None):
        result = "\n".join(report)
        preset = get_preset_by_id(presets, edit_id) if edit_id else None
        # 编辑框中的配置还没保存时，不把测试结果写到原预设上。
        if not preset or any(
            (preset.get(key) or "").strip() != (value or "").strip()
            for key, value in (
                ("api_key", api_key),
                ("base_url", base_url),
                ("model", model),
            )
        ):
            return result + "\n\n> 请先保存此模型预设，再重新测试以保留结果。", presets
        preset["last_model_test"] = {
            "tested_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "performance": performance,
            "report": result,
        }
        if supported is not None:
            preset["thinking_supported"] = supported
        if effort_supported is not None:
            preset["reasoning_effort_supported"] = effort_supported
            preset["reasoning_effort_test_version"] = REASONING_EFFORT_TEST_VERSION
            preset["reasoning_effort_ordered"] = effort_ordered
            if not effort_supported:
                preset.pop("reasoning_effort", None)
        save_config(presets, active_id)
        return result + "\n\n> 结论已保存到该预设，刷新页面后仍可查看。", presets

    # ---- 1) 可行性 ----
    try:
        data0, lat0 = _probe_chat(
            api_key, base_url, model, prompt="hi", max_tokens=5, timeout=30
        )
    except urllib.error.HTTPError as e:
        hint = {401: "API Key 无效", 403: "无权限", 404: "Base URL 或模型名不正确"}.get(
            e.code, ""
        )
        report.append(
            f"❌ **模型不可用**（HTTP {e.code}{'：' + hint if hint else ''}）"
        )
        return finish()
    except Exception as e:
        report.append(f"❌ **模型不可用**（{type(e).__name__}: {e}）")
        return finish()
    report.append(f"- **可行性**：✅ 可用于翻译（连通 {lat0:.2f}s）")

    # ---- 2) 性能（一段真实小翻译）----
    perf_prompt = (
        "Translate to Chinese. Output only the translation:\n"
        "The regular languages are closed under union, concatenation, and the Kleene star operation."
    )
    try:
        d1, lat1 = _probe_chat(
            api_key, base_url, model, prompt=perf_prompt, max_tokens=2000, timeout=180
        )
        ctok = (d1.get("usage") or {}).get("completion_tokens", 0)
        tps = ctok / lat1 if lat1 > 0 else 0
        performance = f"{lat1:.2f}s · {tps:.0f} tok/s"
        report.append(
            f"- **性能**：✅ 延迟 {lat1:.2f}s · 输出 {ctok} tokens · 约 {tps:.0f} tok/s"
        )
    except Exception as e:
        performance = "测试失败"
        report.append(f"- **性能**：⚠️ 测试失败（{type(e).__name__}），不影响可用性")

    # ---- 3) 思考开关探测 ----
    supported = False
    if _is_glm53_model(model):
        report.append("- **思考模式**：ℹ️ GLM-5.3 系列固定开启思考，使用推理深度调节")
    else:
        default_thinks = bool(
            _msg_reasoning((data0.get("choices") or [{}])[0].get("message"))
        )
        detail = []
        label = "thinking.type=disabled"
        try:
            dv, _ = _probe_chat(
                api_key,
                base_url,
                model,
                extra={"thinking": {"type": "disabled"}},
                prompt="hi",
                max_tokens=400,
                timeout=90,
            )
            still_thinks = bool(
                _msg_reasoning((dv.get("choices") or [{}])[0].get("message"))
            )
            if still_thinks:
                detail.append(f"- `{label}`：⚠️ 请求被接受但思考未关闭")
            else:
                detail.append(f"- `{label}`：✅ 未返回思考内容")
                supported = True
        except urllib.error.HTTPError as e:
            detail.append(f"- `{label}`：❌ HTTP {e.code}")
        except Exception as e:
            detail.append(f"- `{label}`：❌ {type(e).__name__}")

        if not default_thinks and not supported:
            report.append("- **思考模式**：ℹ️ 该模型默认不输出思考内容，无需关闭")
            supported = True
        elif supported:
            report.append("- **思考模式**：✅ 支持关闭，主界面开关已解锁")
        else:
            report.append("- **思考模式**：❌ 不支持关闭")
        report.extend(detail)

    # 单次思考量有随机波动；记录三轮中位数供参考。
    # 档位是否可选只取决于三种请求能否完整返回，不以思考长度排序为门槛。
    if _is_glm53_model(model):
        observed = {level: [] for level in REASONING_EFFORT_LEVELS}
        observed_tokens = {level: [] for level in REASONING_EFFORT_LEVELS}
        try:
            for _ in range(3):
                for level in REASONING_EFFORT_LEVELS:
                    response, _ = _probe_chat(
                        api_key,
                        base_url,
                        model,
                        extra={"reasoning_effort": level},
                        prompt=perf_prompt,
                        max_tokens=1200,
                        timeout=120,
                    )
                    choice = (response.get("choices") or [{}])[0]
                    if (
                        not (choice.get("message") or {}).get("content")
                        or choice.get("finish_reason") == "length"
                    ):
                        raise ValueError(f"{level} 档位响应不完整")
                    chars, tokens = _reasoning_measure(response)
                    observed[level].append(chars)
                    observed_tokens[level].append(tokens)
            if any(size for sizes in observed.values() for size in sizes):
                samples, unit = observed, "可见思考字符"
            else:
                samples, unit = observed_tokens, "推理 token"
            middle = {
                level: median(samples[level]) for level in REASONING_EFFORT_LEVELS
            }
            effort_supported = True
            effort_ordered = 0 <= middle["low"] < middle["high"] < middle["max"]
            counts = " · ".join(
                f"{level} {middle[level]:g}" for level in REASONING_EFFORT_LEVELS
            )
            if effort_ordered:
                report.append(
                    f"- **推理深度**：✅ 三档请求均成功，可在主界面选择；三轮中位数依次增加（{unit}：{counts}）"
                )
            else:
                report.append(
                    f"- **推理深度**：⚠️ 三档请求均成功，可在主界面选择；三轮中位数未按档位递增（{unit}：{counts}），实际效果未确认"
                )
        except Exception as e:
            effort_supported = False
            effort_ordered = None
            report.append(
                f"- **推理深度**：❌ 请求失败或响应不完整（{type(e).__name__}: {e}），暂不开放选择"
            )
    return finish(supported)
