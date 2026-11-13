# Demo B 手动测试与实时进度

本说明只提供启动和只读观察方法。运行测试会真实调用已配置的供应商模型；进度查看脚本不调用模型、不改任务、也不会生成页面。

## 文件

| 文件 | 用途 |
|---|---|
| `demos/single_page.py` | 正式单页Agent入口，支持预制资产与原始PDF两种输入 |
| `tools/run_demo_b_timed.py` | 启动同一正式入口，最多900秒，正式门禁通过后才可能导出 |
| `tools/watch_demo_b.py` | 只读显示当前活动、工具失败、正式资产及页面状态 |
| `.env.example` | 空凭据与可选路径配置模板 |
| `outputs/manual-demo-b/source.pdf` | 本机另存的自制合成示例PDF；被Git忽略，不是论文成果 |

本机示例PDF已复制到单独输入目录，测试不会读取旧Manifest、规划、HTML或审核记录。原始PDF模式当前仍是一页合成数据测试任务，不应仅换入真实论文就把它当成正式论文汇报流程。

## 1. 环境

在仓库根目录运行。新环境请先按根README安装依赖并激活虚拟环境，然后使用 `python`。当前本机已验证环境为 `.build/clean-env`，下方用其相对路径，避免使用系统里其他Python。

如果尚无本地 `.env`，可以自行执行：

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

在本地配置Key，不要贴到聊天或提交Git。两种模式均需配置Qwen、豆包与DeepSeek：制作/内容审核使用Qwen Flash，原图/表格核验及PDF审核使用DeepSeek Flash，页面视觉审核使用豆包。已有环境变量不会被模板覆盖。

原始PDF模式还需要MinerU、模型缓存和设备配置。本机路径参数已另存于被Git忽略的 `.build/manual_demo_b_paths.ps1`，只设置可执行文件/缓存/临时目录，不读取或设置真实Key。它适用于当前电脑，不是可分发配置。在新的PowerShell窗口运行测试前可点加载：

```powershell
. .\.build\manual_demo_b_paths.ps1
```

先预检，**没有模型请求**：

```powershell
& .\.build\clean-env\Scripts\python.exe -m demos.single_page --pdf outputs/manual-demo-b/source.pdf --output outputs/my-demo-b-preflight
```

预检通过只说明工具依赖可加载和配置可读取，不证明模型账户或ID一定可用。若Key缺失，真实入口会在调用前报错。

## 2. 窗口一：原始PDF、最长15分钟

```powershell
& .\.build\clean-env\Scripts\python.exe tools/run_demo_b_timed.py --pdf outputs/manual-demo-b/source.pdf --output outputs/my-demo-b-01 --seconds 900 --export
```

首次测试使用新输出目录。再次测试请换 `my-demo-b-02`，不要覆盖已有 `console.log` 或任务。

该入口不预先解析或规划，模型自行决定正式工具。外层轮次安全阀为100000，在15分钟范围内不构成实际限制；内部审核有限重试和所有门禁仍保留。超时会中止当前本地请求并留下产物，服务器可能继续计费，不能把中止用量当作0。

最新冻结运行已完成解析、HTML制作/审核和PPTX导出，最终PowerPoint渲染仍失败。详见 DEMO_B_TEST_STATUS.md。公开自制输入为 showcase/demo-b-2026-11-13/source.pdf。此处 .build 和 outputs/manual-demo-b 为原本机步骤，不是公开仓库依赖；新环境优先使用根README通用命令。

## 3. 窗口二：实时看进度

同样在仓库根目录执行，`--output`必须与窗口一完全一致：

```powershell
& .\.build\clean-env\Scripts\python.exe tools/watch_demo_b.py --output outputs/my-demo-b-01 --watch
```

每3秒读取一次，不启动模型。可以在测试前就打开，等待目录创建。`Ctrl+C`仅退出进度查看，不会停止窗口一中的Agent；限时进程仍由900秒监督器控制。

只看一次或取得JSON：

```powershell
& .\.build\clean-env\Scripts\python.exe tools/watch_demo_b.py --output outputs/my-demo-b-01
& .\.build\clean-env\Scripts\python.exe tools/watch_demo_b.py --output outputs/my-demo-b-01 --json
```

显示内容包括：

- 等待模型/接收响应/等待工具返回/超时或结束。
- 最后提交工具、累计工具失败、最近失败工具名、已返回的Token和模型分布。
- PDF解析工具成功事件、资产数量和revision、PDF审核是否当前且全文覆盖。
- 规划是否保存、HTML是否绑定、截图记录、程序/内容/视觉/综合审核状态。
- PPTX导出、PowerPoint渲染、导出和最终交付验收记录。

### 正确理解状态

- `tool_start`只证明工具请求已提交，可能仍在排队；不等于执行成功。
- 没有新日志不等于卡死，可能在解析、模型思考、服务排队或网络等待。查看器不能进一步分离这些原因。
- 磁盘上有Manifest不等于实际运行了解析；预制/合成模式会明确显示跳过解析。
- `write_file`成功不等于正式HTML已绑定或审核通过。正式任务状态在 `tasks/sample/task.json`。
- `pass`是当前正式记录的结论，不是独立人工背书。查看器不重做来源哈希、完整性或学术事实核验。
- 模型 `end_turn`或入口退出码0不能代替完整验收；最终还要检查当前导出、实际PPTX截图和正式交付报告。
- 预检/启动错误若尚无Agent事件，需结合窗口一退出码及 `console.log` 判断，不能只凭“等待事件”认定还在运行。

## 4. 原始日志和产物

```powershell
Get-Content outputs/my-demo-b-01/console.log -Tail 20 -Wait
```

| 路径 | 用途 |
|---|---|
| `console.log` | 入口输出、异常、工具开始摘要 |
| `real-*-events.jsonl` | 模型调用、工具返回、错误、用量、压缩与停止原因 |
| `sessions/` | 正式Session恢复记录 |
| `pdf/` | 实际解析、Manifest、原始JSON/MD、分页MD及PDF核验 |
| `tasks/sample/task.json` | 正式对象索引与版本 |
| `tasks/sample/slides/` | 成功绑定后保存的HTML、截图与独立审核 |
| `tasks/sample/exports/` | 正式导出（存在与否不能代替验收） |
| `timed-execution.json` | 是否超时、墙钟和退出码 |
| `real-*-summary.json` / `real-*-result.json` | 正常结束时的计量与状态；硬中止时可能不存在 |

日志可能包含本机路径和文档内容，只保留在忽略的outputs中，不要直接上传。

## 5. 只测试预制资产到HTML

如果不想测MinerU/PDF解析：

```powershell
& .\.build\clean-env\Scripts\python.exe -m demos.single_page --run --max-turns 100 --output outputs/my-demo-b-prepared-01
```

这是另一输入模式，无PDF解析、无自主论文规划，且该命令不是900秒计时入口。需要时使用对应的只读查看器，但不能把两种测试混称完整端到端。


限时入口当前默认与最大值均为900秒（15分钟），显式传600仍可运行10分钟。已启动进程会保留启动时的时限，不会随源码更新而自动延长。


主模型连接配置当前为 `max_retries=3`：可重试错误最多额外重试3次，初始请求加重试最多4次HTTP尝试；仍受15分钟进程总时限约束。已运行的进程不会自动采用新配置。该改动没有改变模型路由或审核工具内部的重试合同。


原图与表格视觉检查当前固定为 `deepseek:deepseek-flash`，预检与实际工具共用一个模型解析函数。旧环境变量若仍指定其他模型，会在付费调用前报配置错误；需要清除旧终端中的 `PPT_AGENT_ASSET_INSPECTION_MODEL` 覆盖，或改为已批准值。新启动进程生效，历史运行记录保持原样。
