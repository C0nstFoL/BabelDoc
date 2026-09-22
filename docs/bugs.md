# 漏洞与缺陷清单

> 状态说明：未修复 / 已修复
> 后续修复按编号引用，修复后更新状态并注明提交

<!-- 使用示例：
## BUG-001 已修复（6a1873d）
- 位置：backend/app/main.py:141
- 描述：SPA fallback 路径穿越漏洞，`frontend_dist / full_path` 未校验，可通过 `//etc/passwd` 或编码穿越读取服务器任意文件
-->

## BUG-001 已修复（52536a0）
- 位置：babeldoc_translator.py:1484
- 描述：桌面端上传卡片被强制拉伸以匹配右侧配置区高度，拖拽框最小高度为 240px，造成大量无效空白。
- 修复：上传区改为内容自适应，拖拽框最小高度调整为 132px，操作按钮紧随卡片显示。

## BUG-002 已修复（ddf8cf7）
- 位置：babeldoc_translator.py:1850
- 描述：上传操作按钮下方的区域没有承载内容，无法让用户确认已选文件的基本属性。
- 修复：增加动态文件信息模块，展示上传说明或文件名称、大小、格式和就绪状态。

## BUG-003 已修复（50e4ed9）
- 位置：babeldoc_translator.py:102
- 描述：文件信息模块只能展示静态属性，用户在开始翻译前无法确认 PDF 的文字层情况和当前翻译参数。
- 修复：增加 PDF 页数、前三页文字层抽样检查与实时翻译设置摘要。

## BUG-004 已修复（c2098a9）
- 位置：babeldoc_translator.py:1570
- 描述：文件信息卡片的值被限制为单行并以省略号截断，长文件名、文字层状态等内容无法完整阅读，且缺少资源预估。
- 修复：卡片改为可换行的响应式网格，并增加处理时长和 API Token 用量估算。

## BUG-005 已修复（da53752）
- 位置：babeldoc_translator.py:665
- 描述：进度条仅以不完整的静态阶段权重计算，未包含 BabelDOC 的部分阶段，也未使用其原生 `overall_progress`，导致条形显示与实际翻译进度不一致。
- 修复：解析 BabelDOC 调试进度事件并显示精确总进度；事件不可用时标注为保守阶段估算，同时改为完整宽度进度条。

## BUG-006 已修复（71c2d63）
- 位置：babeldoc_translator.py:475, 850, 1820
- 描述：调试模式生成的 `.decompressed.pdf` 被混入译文下载列表；日志行的时间戳未占用固定列，且分隔线被注入时间文本后发生错位。
- 修复：过滤调试 PDF，并将日志时间固定为独立列；分隔线不再写入时间戳。

## BUG-007 已修复（115af8f）
- 位置：babeldoc_translator.py:1040
- 描述：为读取精确进度而使用 CLI `--debug`，导致 BabelDOC 将调试框和布局标记绘制到最终译文。
- 修复：改用 `async_translate()` 原生事件并保持 `debug=False`，在不污染 PDF 的前提下更新精确进度。

## BUG-008 已修复（2637867）
- 位置：babeldoc_translator.py:740
- 描述：原生阶段完成事件只更新进度条状态，阶段开始日志保留加载动画，未切换为完成图标。
- 修复：在 `progress_end` 时原位替换阶段日志为完成状态并附带阶段耗时。

## BUG-009 已修复（ed2fef3）
- 位置：babeldoc_translator.py:1555, 2777
- 描述：恢复进度可能向 `gr.File` 返回已失效 PDF 路径，引发 FileNotFoundError；此外“清空”不应删除输出目录。
- 修复：恢复时过滤不存在的结果路径；清空操作仅移除日志显示，保留所有输出文件与内存文件引用。

## BUG-010 已修复（8851da7、5a17786、872d78d）
- 位置：babeldoc_translator.py:2443
- 描述：历史任务表格设为非交互模式，导致 Gradio 6 不派发 `select` 事件；首次修复后，未把当前表格数据传给回调，筛选或排序时无法稳定对应到实际任务。
- 修复：启用表格交互事件并使用 `static_columns` 锁定所有列；将表格行数据和事件行值一并传入回调匹配任务，关闭该轻量操作的队列与加载动画，并清除 Gradio `cell-selected` 的选中边框。

## BUG-011 已修复（465c9b8、a8bdd0e）
- 位置：babeldoc_translator.py:1973
- 描述：历史翻译记录表格点击记录时，Gradio 默认黄色选择框只覆盖一个单元格，无法直观识别当前选中的整条记录。
- 修复：根据 Gradio Dataframe 网格单元格的 `data-row` 属性将选中状态同步到同行所有单元格，禁用 `body-cell.cell-selected` 的默认橙色 ring，仅保留整行浅色背景。

## BUG-012 已修复
- 位置：babeldoc_translator.py:1970
- 描述：Gradio Dataframe 的 `table-wrap` 使用 `transition: all`，点击表格时状态变化触发缩小动画；同时 Svelte 作用域样式继续绘制默认橙色选择 ring。
- 修复：禁用历史表格容器和选中单元格的过渡、缩放动画，并将 `--ring-color` 与 `--sel-*` 全部覆盖为透明。
