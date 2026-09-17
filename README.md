# BabelDOC 论文翻译工具

基于 [BabelDOC](https://github.com/funstory-ai/BabelDOC) 和 Gradio 构建的 PDF 论文翻译 Web 界面，支持 DeepSeek 及其他 OpenAI 兼容接口。

## 功能

- PDF 论文翻译，输出双语对照版（dual）和纯译文版（mono）
- 亮色 / 暗色 / 跟随系统三种主题，自动记忆偏好
- 历史任务列表：原文/译文在线预览、下载、删除
- 翻译进度、阶段耗时和子进程心跳实时展示
- 汇总显示模型响应警告与降级重试，便于区分长任务和程序卡死

## 快速开始

### 方式一：Docker（推荐）

```bash
# 首次运行前，创建持久化文件（宿主机需预先存在，否则 Docker 会误创建为目录）
touch .babeldoc_config.json .babeldoc_history.json
mkdir -p outputs

docker compose up -d --build
```

访问 http://localhost:7865

本项目将主程序挂载到容器中。只修改 `babeldoc_translator.py` 时重启容器即可生效：

```bash
docker compose restart babeldoc
```

如果修改了 `Dockerfile` 或 `requirements.txt`，则需要重新构建镜像：

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
New-Item -ItemType File -Force .babeldoc_config.json, .babeldoc_history.json
New-Item -ItemType Directory -Force outputs
```

4. 如果需要 OIDC 登录，在项目根目录创建 `.env`，填写以下变量；不使用登录认证时可以省略 `.env`：

```dotenv
AUTH_ENABLED=false
ZITADEL_ISSUER=https://your-zitadel.example.com
ZITADEL_CLIENT_ID=
ZITADEL_CLIENT_SECRET=
APP_BASE_URL=http://localhost:7865
SESSION_SECRET=请替换为随机字符串
```

需要启用 OIDC 登录时，将 `AUTH_ENABLED` 改为 `true`，并填写 `ZITADEL_CLIENT_ID`、`ZITADEL_CLIENT_SECRET`、`ZITADEL_ISSUER` 和 `APP_BASE_URL`。不启用认证时保持 `AUTH_ENABLED=false` 即可。

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

也可以直接双击 `start.bat`，脚本会自动选择受支持的 Python 版本、创建虚拟环境、安装依赖、创建运行数据文件并启动服务。批处理文件使用 Windows CRLF 换行，建议通过 Git 克隆或下载完整发布包，不要用会自动转换换行符的编辑器保存。

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

Windows 本地运行不使用 Linux 专用的 `start.sh`。通过 `start.bat` 后台启动时使用 `start.bat stop` 停止；直接执行 `python babeldoc_translator.py` 时，在对应 PowerShell 窗口按 `Ctrl+C` 停止。

## 翻译进度与排障

翻译大型 PDF 时，页面会持续显示当前阶段耗时、子进程最近输出时间，以及模型响应警告/降级重试次数。刷新页面不会终止后台翻译，重新打开页面后可继续查看当前任务。

如果长时间停留在“段落翻译”：

1. 查看“最近输出”和“最近警告”。只要最近输出时间仍在更新，任务通常仍在运行。
2. 若反复出现 `Unterminated string`、`Invalid control character` 或“输出过长/过短”，说明模型返回格式不稳定。可将速度从“极速”降为“快速”或“标准”，或者切换其他 OpenAI 兼容模型。
3. Docker 部署可运行 `docker compose logs -f babeldoc` 查看完整日志；Windows 本地部署可运行 `start.bat logs`。
4. 确认任务确实无响应后，再从页面停止任务或重启服务。重启会中断尚未完成的翻译。

代码更新后，Docker 部署运行：

```bash
docker compose restart babeldoc
```

Windows 本地部署运行：

```bat
start.bat restart
```

## 配置

认证由环境变量 `AUTH_ENABLED` 控制，默认值为 `false`。没有 OIDC 服务时保持关闭即可；只有将其设为 `true`，并同时填写完整的 Zitadel 配置后，应用才会启用登录保护。

首次打开页面后，在界面中填写 API Key / Base URL / 模型名称并保存，配置会写入项目根目录下的本地文件：

- `.babeldoc_config.json`：API 配置（Key 经过简单编码存储，**不是加密**，仍属敏感信息）
- `.babeldoc_history.json`：历史任务记录
- `outputs/`：历史任务的原文与译文文件

**这些文件包含你的真实 API Key，切勿提交到 Git 或分享给他人。** 项目已在 [.gitignore](.gitignore) 中排除它们，正常使用 `git status` 不会看到这些文件被跟踪。若要打包、复制项目给其他人（如迁移到新服务器、上传网盘、发给协作者），请先删除或替换这些文件里的 `api_key` 字段。

Docker 部署时这些文件通过 volume 挂载持久化到宿主机同名文件/目录，不会打进镜像，重新构建镜像不会清空已保存的配置。

宿主机与容器统一使用带点的文件名：删除容器不会删除这些文件，执行 `docker compose down` 也不会删除翻译历史和配置。备份或迁移时请一并保存 `.babeldoc_config.json`、`.babeldoc_history.json` 和 `outputs/`。

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
