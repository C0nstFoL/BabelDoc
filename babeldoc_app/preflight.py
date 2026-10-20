"""PDF inspection and upload summary."""

import html
from pathlib import Path


def _format_file_size(size: int) -> str:
    """将字节数转换为易读的文件大小。"""
    units = ("B", "KB", "MB", "GB")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def _format_token_count(tokens: int) -> str:
    """将 Token 数量转换为紧凑且易读的格式。"""
    return f"{tokens / 1000:.1f}K" if tokens >= 1000 else str(tokens)


def _pdf_preflight(pdf_path: Path) -> tuple[int | None, str, int]:
    """读取 PDF 页数与文字抽样，并返回用于估算 API 用量的字符数。"""
    try:
        try:
            import pymupdf
        except ImportError:
            import fitz as pymupdf

        with pymupdf.open(pdf_path) as doc:
            page_count = len(doc)
            sample_pages = min(3, page_count)
            sample_text = "".join(
                doc.load_page(index).get_text().strip() for index in range(sample_pages)
            )
        text_status = (
            "已检测到可提取文字"
            if len(sample_text) >= 80
            else "文字层较少，可能需要 OCR"
        )
        average_chars = len(sample_text) / max(sample_pages, 1)
        estimated_chars = max(800 * page_count, int(average_chars * page_count))
        return page_count, text_status, estimated_chars
    except Exception:
        return None, "暂未完成检查", 0


def _translation_estimate(
    page_count: int | None, estimated_chars: int, speed: str, text_status: str
) -> tuple[str, str]:
    """按页数、文字抽样和速度生成时长及 Token 用量的保守估算。"""
    if not page_count:
        return "等待文件检查", "等待文件检查"

    seconds_per_page = {"标准": 18, "快速": 10, "极速": 6}.get(speed, 10)
    if "可能需要 OCR" in text_status:
        seconds_per_page *= 2
    estimated_seconds = 25 + page_count * seconds_per_page
    low_minutes = max(1, round(estimated_seconds * 0.7 / 60))
    high_minutes = max(low_minutes + 1, round(estimated_seconds * 1.35 / 60))
    total_tokens = max(1200, int(estimated_chars / 4 * 1.9))
    return (
        f"约 {low_minutes}–{high_minutes} 分钟",
        f"约 {_format_token_count(total_tokens)} tokens",
    )


def file_info_panel(
    file_value, lang_in="en", lang_out="zh", output_mode="both", speed="快速"
):
    """生成上传区下方的翻译前检查面板，兼容 Gradio 返回的临时文件路径。"""
    if not file_value:
        return """
        <div class="file-info-empty">
            <span class="file-info-empty-icon">🗂️</span>
            <div><strong>等待选择文件</strong><p>支持单个 PDF 文档。上传后将在这里检查页数、文字层及本次翻译设置。</p></div>
        </div>
        """

    path = Path(str(file_value))
    filename = html.escape(path.name)
    try:
        size = _format_file_size(path.stat().st_size)
        status = "已就绪，可选择语言与模型后开始翻译"
    except OSError:
        size = "暂不可用"
        status = "文件信息读取中，请稍候"
    extension = path.suffix.upper().lstrip(".") or "未知"
    page_count, text_status, estimated_chars = _pdf_preflight(path)
    pages = f"{page_count} 页" if page_count is not None else "暂不可用"
    time_estimate, token_estimate = _translation_estimate(
        page_count, estimated_chars, speed, text_status
    )
    language_names = {
        "en": "英语",
        "zh": "中文",
        "ja": "日语",
        "fr": "法语",
        "de": "德语",
        "ru": "俄语",
        "es": "西班牙语",
        "ko": "韩语",
    }
    output_names = {
        "both": "双语对照 + 译文",
        "dual_only": "仅双语对照",
        "mono_only": "仅译文",
    }
    speed_names = {"标准": "标准", "快速": "快速", "极速": "极速"}
    translation_summary = " · ".join(
        (
            f"{language_names.get(lang_in, lang_in)} → {language_names.get(lang_out, lang_out)}",
            output_names.get(output_mode, output_mode),
            f"{speed_names.get(speed, speed)}速度",
        )
    )
    return f"""
    <div class="file-info-ready">
        <div class="file-info-status"><span>✓</span>{status}</div>
        <div class="file-info-grid">
            <div><span>文件名称</span><strong title="{filename}">{filename}</strong></div>
            <div><span>文件大小</span><strong>{size}</strong></div>
            <div><span>文件格式</span><strong>{html.escape(extension)}</strong></div>
            <div><span>文档页数</span><strong>{pages}</strong></div>
            <div><span>文字层检查</span><strong>{text_status}</strong></div>
        </div>
        <div class="translation-summary"><span>本次翻译</span><strong>{translation_summary}</strong></div>
        <div class="estimate-grid">
            <div><span>预计时长</span><strong>{time_estimate}</strong></div>
            <div><span>预估成本（API 用量）</span><strong>{token_estimate}</strong><small>金额按当前模型服务商费率计算</small></div>
        </div>
    </div>
    """
