# 代码结构

应用代码位于 `babeldoc_app/`，与第三方 `babeldoc` 包分开命名。根目录的 `babeldoc_translator.py` 仅负责启动分发，原有 `start.sh`、`start.bat` 和 Docker 启动命令继续可用，也可执行 `python -m babeldoc_app`。

## 模块职责

| 模块 | 职责 |
| --- | --- |
| [settings.py](../babeldoc_app/settings.py) | 环境变量与项目根目录下的数据路径 |
| [presets.py](../babeldoc_app/presets.py) | 模型预设读写、密钥编码与摘要 |
| [model_api.py](../babeldoc_app/model_api.py) | 连通性、性能、思考与推理深度测试 |
| [preflight.py](../babeldoc_app/preflight.py) | 上传文件检查、页数及用量估算 |
| [history.py](../babeldoc_app/history.py) | 历史记录读写、文件筛选、选择和删除 |
| [state.py](../babeldoc_app/state.py) | 唯一的后台任务状态、锁、停止信号与进程引用 |
| [progress.py](../babeldoc_app/progress.py) | 原生进度事件与日志 HTML |
| [engine.py](../babeldoc_app/engine.py) | BabelDOC 调用、OCR、子进程事件协议与终止监督 |
| [tasks.py](../babeldoc_app/tasks.py) | 后台任务生命周期、结果入库与浏览器进度轮询 |
| [auth.py](../babeldoc_app/auth.py) | OIDC 路由、会话与认证中间件 |
| [server.py](../babeldoc_app/server.py) | ASGI 应用创建和 HTTP 服务启动 |
| [runtime.py](../babeldoc_app/runtime.py) | 固定依赖版本检查，以及部署前翻译/OCR API 和实际界面构建验证 |
| [ui/](../babeldoc_app/ui/) | 页面布局、具名组件容器、预设回调及各区域事件注册 |
| [assets/](../babeldoc_app/assets/) | CSS、历史整行选择及主题 JavaScript |

## 依赖与运行边界

- `ui/app.py` 的 `build_ui()` 按需构建页面；`server.py` 的 `create_app()` 按需构建 ASGI 服务。导入启动入口、执行引擎或服务模块不会创建页面，也不会启动 HTTP 服务。
- `ui/layout.py` 只创建布局并返回 `Components`；预设、翻译、历史和浏览器事件分别在对应模块注册，预设回调可以独立验证。
- `tasks.py` 启动后台线程，再由 `engine.py` 启动独立进程组。子进程经兼容入口的 `--translation-worker` 分支执行，只导入执行层；任务配置通过 stdin 传递，密钥不进入命令行。
- 共享状态只在 `state.py` 创建一次。可重新赋值的运行进程引用通过 `state` 模块访问，避免模块拆分后停止按钮与监督线程读取不同引用。
- 浏览器刷新或离开页面只结束进度轮询，后台任务与历史输出继续保留。输出文件由历史记录的两次点击删除流程显式清理。
- `.babeldoc_config.json`、`.babeldoc_history.json` 和 `outputs/` 始终位于项目根目录；不会因 Python 文件移动而改变数据位置。认证环境变量仍由私有部署配置提供。

## 部署与验证

镜像同时复制启动入口、应用包和静态资源。Compose 挂载启动入口与整个应用包，修改现有模块后可重启服务；首次切换至本结构时必须重建镜像并重新创建容器，以应用新的目录挂载。

```bash
docker compose up -d --build --force-recreate babeldoc
```

本次部署复用了已验证运行镜像的系统及 Python 依赖，仅更新应用层后重新创建容器；常规全量构建因重新下载系统依赖而中止，不作为本次验证结果。新镜像内执行了依赖一致性、翻译/OCR 导入及完整回归检查。

在安装了项目依赖的环境运行：

```bash
python -m unittest discover -s tests -v
```

回归覆盖独立翻译进程与 OCR 快速停止、进度和结果协议、真实子进程入口、导入边界、原数据路径、预设持久化、历史下载与删除、清空及恢复进度、界面事件绑定，以及无认证访问和模拟 OIDC 会话。模拟认证与翻译协议不代表真实账号登录或完整 PDF 翻译验收。
