# ============================================================
# BabelDOC 论文翻译工具 - Docker 镜像
# ============================================================
FROM python:3.13-slim

LABEL description="BabelDOC PDF Translation Tool with DeepSeek"
LABEL maintainer="BabelDoc User"

# 避免交互式提示
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# 安装系统依赖（使用清华 apt 镜像源加速）
#   - libgl1, libglib2.0: OpenCV / PDF 渲染所需
#   - libsm6, libxext6, libxrender-dev: 图形相关
#   - fonts-wqy-zenhei / fonts-noto-cjk: 中文字体支持
#   - poppler-utils: PDF 工具
#   - tesseract-ocr(+eng/chi-sim): 扫描版 PDF OCR 预处理（配合 ocrmypdf）
#   - ghostscript, qpdf: ocrmypdf 必需的系统依赖
RUN sed -i \
    -e 's|URIs: http://deb.debian.org/debian-security|URIs: http://mirrors.aliyun.com/debian-security|g' \
    -e 's|URIs: http://deb.debian.org/debian|URIs: http://mirrors.aliyun.com/debian|g' \
    /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    fonts-wqy-zenhei \
    fonts-noto-cjk \
    poppler-utils \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-chi-sim \
    ghostscript \
    qpdf \
    && rm -rf /var/lib/apt/lists/*

# 使用清华 pip 镜像源加速
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    && pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn

# 创建工作目录
WORKDIR /app

# 先复制依赖文件（利用 Docker 缓存）
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY babeldoc_translator.py .

# 创建历史任务输出目录（配置文件与历史记录通过 volume 挂载持久化，不在镜像中复制）
RUN mkdir -p /app/outputs

# 暴露 Gradio 服务端口
EXPOSE 7865

# 启动应用
CMD ["python", "babeldoc_translator.py"]
