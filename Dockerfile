# ============================================================
# BabelDOC 论文翻译工具 - Docker 镜像
# ============================================================
FROM python:3.13-slim

LABEL description="BabelDOC PDF Translation Tool with DeepSeek"
LABEL maintainer="BabelDoc User"

# 避免交互式提示
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# 安装系统依赖
#   - libgl1, libglib2.0: OpenCV / PDF 渲染所需
#   - libsm6, libxext6, libxrender-dev: 图形相关
#   - fonts-wqy-zenhei / fonts-noto-cjk: 中文字体支持
#   - poppler-utils: PDF 工具
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    fonts-wqy-zenhei \
    fonts-noto-cjk \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# 创建工作目录
WORKDIR /app

# 先复制依赖文件（利用 Docker 缓存）
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY babeldoc_translator.py .
COPY .babeldoc_config.json .

# 创建临时输出目录
RUN mkdir -p /tmp/babeldoc_output

# 暴露 Gradio 服务端口
EXPOSE 7865

# 启动应用
CMD ["python", "babeldoc_translator.py"]
