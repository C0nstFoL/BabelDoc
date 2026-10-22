# 漏洞与缺陷清单

> 状态说明：未修复 / 已修复
> 后续修复按编号引用，修复后更新状态并注明提交

<!-- 使用示例：
## BUG-001 已修复（6a1873d）
- 位置：backend/app/main.py:141
- 描述：SPA fallback 路径穿越漏洞，`frontend_dist / full_path` 未校验，可通过 `//etc/passwd` 或编码穿越读取服务器任意文件
-->

## BUG-001 已修复（ea8d38f）
- 位置：babeldoc_translator.py:1484
- 描述：桌面端上传卡片被强制拉伸以匹配右侧配置区高度，拖拽框最小高度为 240px，造成大量无效空白。
- 修复：上传区改为内容自适应，拖拽框最小高度调整为 132px，操作按钮紧随卡片显示。

## BUG-002 已修复（6392537）
- 位置：babeldoc_translator.py:1850
- 描述：上传操作按钮下方的区域没有承载内容，无法让用户确认已选文件的基本属性。
- 修复：增加动态文件信息模块，展示上传说明或文件名称、大小、格式和就绪状态。

## BUG-003 已修复（04dcc2c）
- 位置：babeldoc_translator.py:102
- 描述：文件信息模块只能展示静态属性，用户在开始翻译前无法确认 PDF 的文字层情况和当前翻译参数。
- 修复：增加 PDF 页数、前三页文字层抽样检查与实时翻译设置摘要。

## BUG-004 已修复（0a9c18e）
- 位置：babeldoc_translator.py:1570
- 描述：文件信息卡片的值被限制为单行并以省略号截断，长文件名、文字层状态等内容无法完整阅读，且缺少资源预估。
- 修复：卡片改为可换行的响应式网格，并增加处理时长和 API Token 用量估算。

## BUG-005 已修复（e63f9f5）
- 位置：babeldoc_translator.py:665
- 描述：进度条仅以不完整的静态阶段权重计算，未包含 BabelDOC 的部分阶段，也未使用其原生 `overall_progress`，导致条形显示与实际翻译进度不一致。
- 修复：解析 BabelDOC 调试进度事件并显示精确总进度；事件不可用时标注为保守阶段估算，同时改为完整宽度进度条。

## BUG-006 已修复（fc1dca2）
- 位置：babeldoc_translator.py:475, 850, 1820
- 描述：调试模式生成的 `.decompressed.pdf` 被混入译文下载列表；日志行的时间戳未占用固定列，且分隔线被注入时间文本后发生错位。
- 修复：过滤调试 PDF，并将日志时间固定为独立列；分隔线不再写入时间戳。

## BUG-007 已修复（462ab75）
- 位置：babeldoc_translator.py:1040
- 描述：为读取精确进度而使用 CLI `--debug`，导致 BabelDOC 将调试框和布局标记绘制到最终译文。
- 修复：改用 `async_translate()` 原生事件并保持 `debug=False`，在不污染 PDF 的前提下更新精确进度。

## BUG-008 已修复（05a0948）
- 位置：babeldoc_translator.py:740
- 描述：原生阶段完成事件只更新进度条状态，阶段开始日志保留加载动画，未切换为完成图标。
- 修复：在 `progress_end` 时原位替换阶段日志为完成状态并附带阶段耗时。

## BUG-009 已修复（e873840）
- 位置：babeldoc_translator.py:1555, 2777
- 描述：恢复进度可能向 `gr.File` 返回已失效 PDF 路径，引发 FileNotFoundError；此外“清空”不应删除输出目录。
- 修复：恢复时过滤不存在的结果路径；清空操作仅移除日志显示，保留所有输出文件与内存文件引用。

## BUG-010 已修复（f26d4dd、babae30、ea7cc19）
- 位置：babeldoc_translator.py:2443
- 描述：历史任务表格设为非交互模式，导致 Gradio 6 不派发 `select` 事件；首次修复后，未把当前表格数据传给回调，筛选或排序时无法稳定对应到实际任务。
- 修复：启用表格交互事件并使用 `static_columns` 锁定所有列；将表格行数据和事件行值一并传入回调匹配任务，关闭该轻量操作的队列与加载动画，并清除 Gradio `cell-selected` 的选中边框。

## BUG-011 已修复（b62bbbb、e5be09a）
- 位置：babeldoc_translator.py:1973
- 描述：历史翻译记录表格点击记录时，Gradio 默认黄色选择框只覆盖一个单元格，无法直观识别当前选中的整条记录。
- 修复：根据 Gradio Dataframe 网格单元格的 `data-row` 属性将选中状态同步到同行所有单元格，禁用 `body-cell.cell-selected` 的默认橙色 ring，仅保留整行浅色背景。

## BUG-012 已修复
- 位置：babeldoc_translator.py:1970
- 描述：Gradio Dataframe 的 `table-wrap` 使用 `transition: all`，点击表格时状态变化触发缩小动画；同时 Svelte 作用域样式继续绘制默认橙色选择 ring。
- 修复：禁用历史表格容器和选中单元格的过渡、缩放动画，并将 `--ring-color` 与 `--sel-*` 全部覆盖为透明。

## BUG-013 已修复（92f7bcd）
- 位置：babeldoc_translator.py:1973
- 描述：Gradio Dataframe 的橙色选择框仍只覆盖被点击的单个单元格，无法表示当前选中的整条历史记录。
- 修复：继续同步同行所有单元格的选中状态，并给首尾单元格添加边界标记；用内阴影拼出贯穿整行的橙色选择框。

## BUG-014 已修复
- 位置：babeldoc_translator.py:608, 2580
- 描述：历史记录不选择记录就点击删除会导致报错，页面所有板块显示错误标识
- 修复：删除按钮默认禁用，仅在已选择记录且勾选确认后启用；未选中时的异常路径返回无操作状态，不再抛出全局 `gr.Error`。

## BUG-015 已修复（59f330b）
- 位置：babeldoc_translator.py:2576
- 描述：删除确认复选框未在页面中稳定显示，导致确认操作不可用。
- 修复：移除未稳定显示的复选框，改用删除按钮自身进行两段式确认。

## BUG-016 已修复（9156ee4）
- 位置：babeldoc_translator.py:639
- 描述：Gradio 6 的 `Button` 组件不接受 `label` 参数，删除按钮两段式确认状态更新触发 `Button.__init__() got an unexpected keyword argument 'label'`；按钮初始状态也未按“是否已选择记录”控制。
- 修复：改用 `Button.value` 更新按钮文字；默认禁用删除按钮，表格或下拉框选中记录后启用，清空/删除后重新禁用。

## BUG-017 已修复（aaa4a43）
- 位置：babeldoc_translator.py:597
- 描述：历史记录表格选中后仍按 3 个值解包 `show_history_files()` 的返回值，而该函数在删除按钮状态调整后实际返回 5 个值，触发 `ValueError: too many values to unpack (expected 3)`，选中后不再加载历史记录。
- 修复：按实际返回值完整解包原文、译文、详情、删除按钮状态和删除确认状态，并将其同步到表格选中的全部输出组件。

## BUG-018 已修复（782153e）
- 位置：babeldoc_translator.py:358
- 描述：DeepSeek 模型测试额外探测 `enable_thinking=false`，该参数被接口接受但不关闭思考，报告产生与实际翻译无关的警告。
- 修复：模型测试只探测实际翻译使用的 `thinking.type=disabled`，并根据响应中的思考字段报告结果。

## BUG-019 已修复（aad42f6）
- 位置：babeldoc_translator.py:2899
- 描述：主面板切换预设时未同步当前预设 ID，思考或推理深度设置可能保存到先前的预设，刷新后也无法恢复当前选择。
- 修复：切换预设时同步并持久化当前预设 ID，确保设置保存到正确预设。

## BUG-020 已修复（6c9a631）
- 位置：babeldoc_translator.py:454
- 描述：GLM 推理深度测试每档只请求一次，且只比较 max 与 low；即使 high 的思考量低于 low，仍报告全部档位有效并解锁选择。
- 修复：每档重复三次并比较中位数，仅当 low < high < max 时解锁；未确认效果时清除旧选择并禁用控件。

## BUG-021 已修复（2d4a444）
- 位置：babeldoc_translator.py:454
- 描述：三档请求均成功时，仅因思考量中位数未依次增加就禁用档位选择，导致用户无法使用已被接口接受的参数。
- 修复：将请求可用性与效果观测分开；三档请求成功即保留选择，未按顺序递增时显示效果未确认，只有请求失败或响应不完整才禁用。

## BUG-022 未修复
- 位置：翻译服务公网 HTTPS 入口
- 描述：域名迁移后公网访问返回 Cloudflare 525；本机应用正常响应，但本机 1Panel/OpenResty 尚无该域名的 HTTPS 站点配置。需核对域名实际回源地址并配置匹配的站点与证书。

## BUG-023 已修复（88b732e）
- 位置：babeldoc_translator.py 停止按钮、翻译后台任务与 OCR 预处理
- 描述：停止操作仅取消外层 asyncio 任务，底层同步翻译线程、API 请求或 OCR 子进程可能继续阻塞，导致停止响应慢或任务一直处于运行状态；停止按钮也未绕过 Gradio 队列。
- 修复：通过 stdin 传递任务配置，在独立进程组运行 BabelDOC API 和 OCR，保留原生进度事件；停止回调使用 queue=False，后台以 0.1 秒间隔检查停止信号，终止超过 0.5 秒则强制结束整个进程组并回收主进程。保留进度轮询，确认退出后展示已停止并保存历史，移除不再执行的旧 CLI 路径。
- 验证：容器内 7 项回归通过，忽略 SIGTERM 的阻塞翻译与 OCR 进程组实测约 0.61 秒停止；回归覆盖忽略 SIGTERM 的翻译进程与 OCR 子进程、启动期间停止、停止后重新启动、正常进度/结果、错误传播和停止历史记录；真实卡死模型请求的浏览器操作待人工验收。

## BUG-024 已修复（e37697d）
- 位置：requirements.txt、constraints.txt、Dockerfile
- 描述：依赖使用范围版本，重建镜像自动安装 bitstring 5.0.0；BabelDOC 0.6.4 的 PDF 创建模块仍导入 BitStream，触发 cannot import name 'BitStream'，翻译无法启动。pip check 不会发现此类 API 不兼容。
- 修复：bitstring 固定为 4.3.1；直接依赖全部固定版本，并通过 constraints.txt 锁定当前 Python 3.13 / Linux 部署的传递依赖。Docker 同时复制约束文件，安装后执行 pip check、BitStream 读操作以及 BabelDOC 翻译模块与 OCR 导入检查，防止不兼容镜像发布。
- 验证：独立容器中复现 5.0.0 的导入失败；降级后 BitStream 读操作、BabelDOC 翻译模块与 OCR 导入、pip check 均通过，现有 7 项翻译进程回归通过。Docker 全新构建及重新部署完成，运行容器 bitstring 为 4.3.1，已安装依赖全部匹配约束，本机入口返回 HTTP 307 认证跳转。完整 PDF 翻译待人工验收。

## BUG-025 已修复
- 位置：私有 Git 仓库 main 分支首次同步
- 描述：新建远端已有一条仅含 README 的独立初始化提交，与本地项目历史无共同祖先，普通首次推送无法快进；该初始化提交包含非匿名作者，直接合并会将其带入后续公开版本历史。
- 修复：先在本机 Git 私有目录创建并验证初始化提交的完整 bundle 备份，经用户明确授权，使用绑定已确认远端提交编号的 force-with-lease 替换私有 main，保留本地项目全部祖先提交；配置默认跟踪 origin/main。
- 验证：完整待推送历史隐私检查通过，远端返回 forced update 成功；GitHub 未推送，禅道关联仍待单独验收。

## BUG-026 已修复（11dff6a）
- 位置：原界面构建代码；现为 [ui/layout.py](../babeldoc_app/ui/layout.py)
- 描述：上传输出目录、预设列表与当前预设 ID 状态在同一页面重复创建，第一组对象未使用，增加界面状态管理与模块拆分的歧义。
- 修复：布局只创建一组状态，通过具名组件容器传给各事件注册模块。
- 验证：界面构建与事件绑定回归通过，85 个可见组件配置与拆分前一致。

## BUG-027 已修复（11dff6a）
- 位置：原页面卸载事件与临时文件清理；现为 [ui/app.py](../babeldoc_app/ui/app.py)、[tasks.py](../babeldoc_app/tasks.py)
- 描述：页面卸载回调绑定需要一个目录参数的清理函数，但 Gradio unload 不传入参数，注册时出现参数数量警告；历史输出目录也不应随浏览器关闭而删除。
- 修复：移除无效卸载绑定及其专用清理函数，保留后台任务与持久化输出，由历史记录显式删除流程清理任务目录。
- 验证：进度清空后仍可恢复结果，历史删除仍需两次点击确认；界面构建不再出现卸载回调参数警告。

## BUG-028 已修复（3670cdb）
- 位置：[Windows 启动脚本](../start.bat)、[运行环境检查](../babeldoc_app/runtime.py)、[服务启动](../babeldoc_app/server.py)、[Dockerfile](../Dockerfile)
- 描述：用户反馈 Windows 部署时 Gradio 4.44 与历史表格不兼容。原启动脚本只检查模块能否导入，已有旧版本也会跳过安装；未创建虚拟环境的 `start` 路径还可能使用全局 Python。历史表格依赖新版 `static_columns`、`show_search`、`pinned_columns` 等接口。
- 修复：Windows 启动统一使用项目 `.venv`，逐项检查直接依赖的固定版本，缺失或版本不符时按 `requirements.txt` 自动修复；启动前执行 `pip check`、BitStream 操作、翻译/OCR API 与实际界面构建检查。手动及 ASGI 启动在导入界面前阻止不匹配的依赖，输出实际版本、要求版本和修复命令；Docker 构建同步执行运行环境及界面检查。补充 Windows 排错步骤，保留批处理 CRLF 换行。
- 验证：4 项环境检查回归通过，覆盖固定版本、旧 Gradio 4.44.1、缺失依赖、手动及 ASGI 启动拦截；完整 21 项回归、真实界面构建、翻译/OCR API、`pip check`、静态检查与批处理 CRLF 检查通过。Docker 复用已验证的原镜像依赖更新应用层后重新创建容器，新镜像与运行容器检查通过，Gradio 为 6.30.0，本机首页 HTTP 307、登录入口 HTTP 302。常规全量构建在重新下载系统包时主动中止，不计作全新依赖安装验证；Windows 实机操作及完整 PDF 翻译待人工复测。
