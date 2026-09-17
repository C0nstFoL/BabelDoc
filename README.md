# BabelDOC 论文翻译工具

基于 [BabelDOC](https://github.com/funstory-ai/BabelDOC) 和 Gradio 构建的 PDF 论文翻译 Web 界面，支持 DeepSeek 及其他 OpenAI 兼容接口。

## 功能

- PDF 论文翻译，输出双语对照版（dual）和纯译文版（mono）
- 亮色 / 暗色 / 跟随系统三种主题，自动记忆偏好
- 历史任务列表：原文/译文在线预览、下载、删除
- 翻译进度、日志实时展示

## 从 0 开始部署

下面以一台 Ubuntu/Debian Linux 服务器和 Docker Compose 为例。部署前准备：

- 一台可以联网的 Linux 服务器（建议至少 2 核 CPU、4 GB 内存）
- 一个用于调用翻译模型的 OpenAI 兼容 API Key
- 如果需要登录认证，一个可访问的域名和 Zitadel OIDC 应用

### 1. 安装 Docker

在服务器上安装 Docker Engine 和 Compose 插件：

```bash
sudo apt update
sudo apt install -y ca-certificates curl git openssl
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
```

重新登录服务器，使 Docker 用户组生效，然后确认安装成功：

```bash
docker --version
docker compose version
```

### 2. 获取项目

```bash
git clone https://github.com/C0nstFoL/BabelDoc.git
cd BabelDoc
```

如果服务器无法访问 GitHub，可以在其他机器下载项目后，再将源码目录复制到服务器。

### 3. 创建持久化目录和文件

这些文件和目录用于保存 API 配置、翻译历史、输入输出文件以及模型缓存。它们属于运行时数据，不要提交到 Git：

```bash
touch babeldoc_config.json babeldoc_history.json
mkdir -p outputs "$HOME/.cache/babeldoc"
```

### 4. 配置环境变量

复制下面的模板创建 `.env`。OIDC 配置是可选的；不配置 `ZITADEL_CLIENT_ID` 和 `ZITADEL_CLIENT_SECRET` 时，应用仍可使用，但不会启用登录认证。

```bash
cat > .env <<'EOF'
# 时区
TZ=Asia/Shanghai

# OIDC 配置（不使用登录认证时可留空）
ZITADEL_ISSUER=https://your-zitadel.example.com
ZITADEL_CLIENT_ID=
ZITADEL_CLIENT_SECRET=

# 用户访问应用的完整地址，必须与 OIDC 回调地址一致
APP_BASE_URL=https://translate.example.com

# 用于保护登录会话，请替换为随机值
SESSION_SECRET=
EOF

# 生成会话密钥并写入 .env
SESSION_SECRET_VALUE=$(openssl rand -base64 32)
sed -i "s|^SESSION_SECRET=.*|SESSION_SECRET=$SESSION_SECRET_VALUE|" .env
```

`.env`、`babeldoc_config.json` 和 `babeldoc_history.json` 都可能包含敏感信息，请勿上传或发送给他人。

### 5. 构建并启动

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f babeldoc
```

看到服务正常启动后，在浏览器打开 `http://服务器IP:7865`。首次进入页面后，在“管理预设”中填写 API Key、Base URL 和模型名称并保存。

检查 HTTP 服务是否可访问：

```bash
curl -I http://127.0.0.1:7865
```

### 6. 配置域名和 HTTPS（可选）

如果只在内网使用，可以直接访问 `7865` 端口。对公网提供服务时，建议使用 Nginx、Caddy 或云厂商反向代理：

1. 将 `translate.example.com` 的 DNS A/AAAA 记录指向服务器。
2. 反向代理到 `http://127.0.0.1:7865`，并启用 WebSocket 转发。
3. 使用 HTTPS 证书。
4. 将 `.env` 中的 `APP_BASE_URL` 改为实际的 HTTPS 地址。
5. 在 Zitadel 应用中添加回调地址 `https://translate.example.com/auth/callback`，退出登录回调地址填写 `https://translate.example.com`。
6. 重启容器：

```bash
docker compose up -d
```

### 7. 更新和停止

更新代码并重新构建：

```bash
git pull --ff-only
docker compose up -d --build --force-recreate
```

查看日志和状态：

```bash
docker compose ps
docker compose logs --tail=100 babeldoc
```

停止服务但保留数据：

```bash
docker compose down
```

不要删除 `outputs/`、`babeldoc_config.json`、`babeldoc_history.json` 或 `~/.cache/babeldoc`，否则会丢失历史任务、配置或已下载的模型缓存。

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
