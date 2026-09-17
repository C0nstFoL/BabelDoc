# BabelDOC 论文翻译工具

基于 [BabelDOC](https://github.com/funstory-ai/BabelDOC) 和 Gradio 构建的 PDF 论文翻译 Web 界面，支持 DeepSeek 及其他 OpenAI 兼容接口。

## 功能

- PDF 论文翻译，输出双语对照版（dual）和纯译文版（mono）
- 亮色 / 暗色 / 跟随系统三种主题，自动记忆偏好
- 历史任务列表：原文/译文在线预览、下载、删除
- 翻译进度、日志实时展示

## 快速开始

### 方式一：Docker（推荐）

```bash
# 首次运行前，创建持久化文件（宿主机需预先存在，否则 Docker 会误创建为目录）
touch babeldoc_config.json babeldoc_history.json
mkdir -p outputs

docker compose up -d --build
```

访问 http://localhost:7865

代码更新后需要重新构建镜像并重建容器，否则容器会继续运行旧代码：

```bash
docker compose build babeldoc
docker compose up -d --force-recreate
```

### 方式二：本地运行

```bash
pip install -r requirements.txt
./start.sh start      # 后台启动
./start.sh status     # 查看状态
./start.sh logs       # 查看日志
./start.sh stop       # 停止
```

或直接前台运行：

```bash
python babeldoc_translator.py
```

## Windows 部署

### 方式一：Docker Desktop（推荐）

1. 安装并启动 [Docker Desktop](https://www.docker.com/products/docker-desktop/)，安装时启用 WSL 2 backend。
2. 安装 Git，然后在 PowerShell 中执行：

```powershell
git clone https://github.com/C0nstFoL/BabelDoc.git
Set-Location BabelDoc
```

3. 创建 Docker 需要挂载的本地文件和目录：

```powershell
New-Item -ItemType File -Force babeldoc_config.json, babeldoc_history.json
New-Item -ItemType Directory -Force outputs
```

4. 如果需要 OIDC 登录，在项目根目录创建 `.env`，填写以下变量；不使用登录认证时可以省略 `.env`：

```dotenv
ZITADEL_ISSUER=https://your-zitadel.example.com
ZITADEL_CLIENT_ID=
ZITADEL_CLIENT_SECRET=
APP_BASE_URL=http://localhost:7865
SESSION_SECRET=请替换为随机字符串
```

5. 构建并启动：

```powershell
docker compose up -d --build
docker compose ps
```

打开 <http://localhost:7865>，然后在“管理预设”中填写 API Key、Base URL 和模型名称。查看日志、停止和更新服务：

```powershell
docker compose logs -f babeldoc
docker compose down
git pull --ff-only
docker compose up -d --build --force-recreate
```

### 方式二：本地 Python

1. 安装 Python 3.10 或更高版本，并在安装程序中勾选 **Add Python to PATH**。
2. 在 PowerShell 中进入项目目录，创建虚拟环境并安装依赖：

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

如果 PowerShell 禁止执行脚本，可先运行：

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

3. 启动应用：

```powershell
python babeldoc_translator.py
```

4. 浏览器访问 <http://localhost:7865>。配置和翻译结果会保存在项目目录中的 `babeldoc_config.json`、`babeldoc_history.json` 和 `outputs/`。

Windows 本地运行不使用 Linux 专用的 `start.sh`；需要停止服务时，在运行 Python 的 PowerShell 窗口按 `Ctrl+C` 即可。

## 配置

首次打开页面后，在界面中填写 API Key / Base URL / 模型名称并保存，配置会写入项目根目录下的本地文件：

- `.babeldoc_config.json`：API 配置（Key 经过简单编码存储，**不是加密**，仍属敏感信息）
- `.babeldoc_history.json`：历史任务记录
- `outputs/`：历史任务的原文与译文文件

**这些文件包含你的真实 API Key，切勿提交到 Git 或分享给他人。** 项目已在 [.gitignore](.gitignore) 中排除它们，正常使用 `git status` 不会看到这些文件被跟踪。若要打包、复制项目给其他人（如迁移到新服务器、上传网盘、发给协作者），请先删除或替换这些文件里的 `api_key` 字段。

Docker 部署时这些文件通过 volume 挂载持久化到宿主机同名文件/目录，不会打进镜像，重新构建镜像不会清空已保存的配置。

## 目录说明

| 路径 | 说明 |
|---|---|
| `babeldoc_translator.py` | 主程序（Gradio 应用） |
| `Dockerfile` / `docker-compose.yml` | Docker 部署配置 |
| `start.sh` | 本地后台运行管理脚本 |
| `.babeldoc_config.json` | API 配置（含敏感信息，勿分享） |
| `.babeldoc_history.json` | 历史任务记录（含敏感信息，勿分享） |
| `outputs/` | 历史任务文件（原文/译文 PDF） |
| `cache/` | BabelDOC 运行时缓存（字体、模型等） |
