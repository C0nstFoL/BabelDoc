# BabelDOC

### PDF 文档翻译，保留原文结构

[![Latest Release](https://img.shields.io/github/v/release/C0nstFoL/BabelDoc?display_name=tag&sort=semver)](https://github.com/C0nstFoL/BabelDoc/releases/latest)
[![License](https://img.shields.io/github/license/C0nstFoL/BabelDoc)](https://github.com/C0nstFoL/BabelDoc)

BabelDOC 是一个面向论文、课程资料和技术文档的 PDF 翻译工具。它基于 [BabelDOC](https://github.com/funstory-ai/BabelDOC) 构建，通过 OpenAI 兼容接口完成翻译，并提供简洁的 Web 界面管理任务和结果。

当前版本：**v1.0.0** · [查看发布说明](https://github.com/C0nstFoL/BabelDoc/releases/tag/v1.0.0)

## 主要功能

- **双语与纯译文输出**：同时生成双语对照版（Dual）和纯译文版（Mono）。
- **版式友好的 PDF 翻译**：尽量保留原文页面结构、段落和图文布局。
- **兼容主流模型服务**：支持 DeepSeek 及其他 OpenAI 兼容 API。
- **实时任务状态**：查看翻译阶段、耗时、进度和模型响应状态。
- **历史任务管理**：在线预览、下载或删除过去的原文与译文。
- **跨平台部署**：支持 Docker，也支持 Linux 和 Windows 本地运行。
- **可选登录保护**：可通过任意兼容 OpenID Connect 的身份提供商启用登录认证。

## 快速开始

### 方式一：Docker（推荐）

```bash
# 首次运行前，创建持久化文件（宿主机需预先存在，否则 Docker 会误创建为目录）
touch .babeldoc_config.json .babeldoc_history.json
mkdir -p outputs

docker compose up -d --build
```

打开 <http://localhost:7865>，在“管理预设”中填写 API Key、Base URL 和模型名称，即可开始翻译。

修改配置或程序后，可使用以下命令管理服务：

```bash
docker compose restart babeldoc
```

修改 `Dockerfile` 或 `requirements.txt` 后，请重新构建镜像：

```bash
docker compose build babeldoc
docker compose up -d --force-recreate
```

### 本地运行

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

## Windows

### Docker Desktop

1. 安装并启动 [Docker Desktop](https://www.docker.com/products/docker-desktop/)，安装时启用 WSL 2 backend。
2. 安装 Git，然后在 PowerShell 中执行：

```powershell
git clone https://github.com/C0nstFoL/BabelDoc.git
Set-Location BabelDoc
```

3. 创建 Docker 需要使用的本地文件和目录：

```powershell
New-Item -ItemType File -Force .babeldoc_config.json, .babeldoc_history.json
New-Item -ItemType Directory -Force outputs
```

4. 如需启用 OIDC 登录，在项目根目录创建 `.env`：

```dotenv
AUTH_ENABLED=false
OIDC_ISSUER=https://your-oidc-provider.example.com
OIDC_CLIENT_ID=
OIDC_CLIENT_SECRET=
APP_BASE_URL=http://localhost:7865
SESSION_SECRET=请替换为随机字符串
```

不启用认证时保持 `AUTH_ENABLED=false` 即可。

5. 构建并启动：

```powershell
docker compose up -d --build
docker compose ps
```

打开 <http://localhost:7865>，然后在“管理预设”中填写 API Key、Base URL 和模型名称。常用维护命令：

```powershell
docker compose logs -f babeldoc
docker compose down
git pull --ff-only
docker compose up -d --build --force-recreate
```

### 本地 Python

1. 安装 Python 3.10、3.11、3.12 或 3.13，推荐 Python 3.12，并在安装程序中勾选 **Add Python to PATH**。当前不支持 Python 3.14。
2. 在 PowerShell 中进入项目目录，创建虚拟环境并安装依赖：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

3. 启动应用：

```bat
start.bat
```

也可以直接双击 `start.bat`。脚本会自动选择受支持的 Python 版本、创建虚拟环境、安装依赖并启动服务。

查看状态、日志、重启和停止：

```bat
start.bat start
start.bat status
start.bat logs
start.bat restart
start.bat stop
```

也可以直接前台运行：

```powershell
python babeldoc_translator.py
```

配置和翻译结果会保存在项目目录中的 `.babeldoc_config.json`、`.babeldoc_history.json` 和 `outputs/`。

Windows 本地运行不使用 Linux 专用的 `start.sh`。通过 `start.bat` 后台启动时使用 `start.bat stop` 停止；直接执行 `python babeldoc_translator.py` 时，在 PowerShell 窗口按 `Ctrl+C` 停止。

## 使用说明

上传 PDF 后选择目标语言和翻译预设即可开始任务。大型文档的处理时间取决于页数、文本量、模型服务速度和 API 限流情况。刷新页面不会终止后台任务，重新打开页面后仍可查看任务状态。

页面会显示当前阶段耗时、最近输出时间，以及模型响应警告和降级重试次数，方便判断任务是在持续处理还是需要调整模型设置。

## 配置与数据

首次打开页面后，在“管理预设”中保存 API Key、Base URL 和模型名称。配置与翻译结果保存在项目目录：

- `.babeldoc_config.json`：API 配置
- `.babeldoc_history.json`：历史任务记录
- `outputs/`：原文与译文 PDF

`.babeldoc_config.json` 包含 API Key，Key 仅经过简单编码存储，**不是加密**。这些文件已被 [.gitignore](.gitignore) 排除，请勿提交到 Git、上传网盘或分享给他人。备份或迁移实例时，请一并保存上述文件和目录。

认证由环境变量 `AUTH_ENABLED` 控制，默认关闭。启用时需配置任意兼容 OpenID Connect 的身份提供商，并填写 `OIDC_ISSUER`、`OIDC_CLIENT_ID`、`OIDC_CLIENT_SECRET`、`APP_BASE_URL` 和 `SESSION_SECRET`。`OIDC_ISSUER` 应指向身份提供商的 issuer 地址，应用会从其标准 `.well-known/openid-configuration` 端点发现认证配置。

## 故障排查

如果任务长时间停留在“段落翻译”：

1. 查看“最近输出”和“最近警告”。只要最近输出时间仍在更新，任务通常仍在处理。
2. 如果反复出现 `Unterminated string`、`Invalid control character` 或“输出过长/过短”，请降低翻译速度或更换 OpenAI 兼容模型。
3. Docker 用户可运行 `docker compose logs -f babeldoc` 查看日志；Windows 用户可运行 `start.bat logs`。
4. 确认任务无响应后，再从页面停止任务或重启服务。重启会中断未完成的翻译。

代码更新后，Docker 部署运行：

```bash
docker compose restart babeldoc
```

Windows 本地部署运行：

```bat
start.bat restart
```

## 目录说明

| 路径 | 说明 |
|---|---|
| `babeldoc_translator.py` | 主程序（Gradio 应用） |
| `Dockerfile` / `docker-compose.yml` | Docker 部署配置 |
| `start.sh` | 本地后台运行管理脚本 |
| `start.bat` | Windows 后台运行管理脚本 |
| `.babeldoc_config.json` | API 配置（含敏感信息，勿分享） |
| `.babeldoc_history.json` | 历史任务记录（含敏感信息，勿分享） |
| `outputs/` | 历史任务文件（原文/译文 PDF） |
| `cache/` | BabelDOC 运行时缓存（字体、模型等） |
