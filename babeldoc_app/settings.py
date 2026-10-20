"""Environment settings and stable project data paths."""

import base64
import os
from pathlib import Path

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
# 完整外部访问地址，用于拼接 OIDC 回调地址
APP_BASE_URL = os.environ.get("APP_BASE_URL", "").strip()
# 用于加密登录会话 Cookie，生产环境务必通过环境变量设置固定值，
# 否则每次重启服务都会导致已登录用户全部掉线
SESSION_SECRET = os.environ.get(
    "SESSION_SECRET", base64.b64encode(os.urandom(32)).decode()
)

# 配置文件路径（放在项目目录下，避免 macOS 沙箱权限问题）
CONFIG_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = CONFIG_DIR / ".babeldoc_config.json"
