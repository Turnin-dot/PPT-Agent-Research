# 代码来源与整理报告

来源：现有 PPT Agent 工作区，2026-11-13 快照。`docs/source_manifest.json` 记录 95 项初始复制文件的相对路径及来源 SHA256。该清单是来源快照，不等同于当前发布白名单；当前文件 SHA 另见 `release_manifest.json`。

## 保留

- `agent_harness/src` 及原有 8 个测试文件：Loop、模型适配、工具、Context、Skills、权限、Session、MCP/子代理等通用机制。未重写或修改 Harness 源码。
- `packages/ppt_domain/src`：PDF 资产、Manifest、分页/证据、规划、页面绑定、双维审核、渲染、可编辑导出及保护。
- `apps/api/src`：现有应用装配服务；不是完整 API 产品。
- `skills`：原有三个 Skill 及引用资源，未重写其规则。
- 选定 9 个领域测试文件和应用装配测试；不复制付费模型测试、历史论文依赖或专用恢复脚本。

## 对复制文件的最小整理

| 文件 | 修改 | 理由 |
|---|---|---|
| `presentation/config.py` | Node 从环境/PATH 读取，node_modules 从当前仓库祖先目录发现 | 移除 Codex 私有缓存路径 |
| `pdf_assets/config.py` | MinerU 可执行文件/缓存/设备改为环境、PATH、用户缓存和 cpu 默认 | 移除原机磁盘路径；未重新验证 PDF Pipeline |
| `packages/ppt_domain/pyproject.toml` | 补 Pillow 依赖 | 实际源码与测试使用 Pillow |
| `test_slide_review_dimensions.py` | 移除仅依赖私有历史报告的一个可选测试 | 不复制内部材料，不以 skip 冒充验收 |
| 两个模块 README | 替换旧机器路径和未复制脚本命令，指向根说明 | 避免无法运行的安装指导 |

其余新增文件为发布装配：根与应用安装元数据、环境模板、依赖约束、Demo CLI、自制输入、静态展示、发布检查与文档。没有改写模型循环、审核阈值、版本检查或导出保护；没有改动原项目。

## 明确排除

`agent_old`、历史 artifacts 整目录、测试论文 PDF、论文图表/长表、缓存和模型权重、个人文档/简历、账号/密钥、原 `.env`、原始模型请求与完整 Session、无关实验脚本、未实现 Web 平台。

历史展示只复制三份候选封面材料；来源/哈希/版本见 `docs/exhibit_provenance.json`。运行与审核数据只用白名单字段摘录。没有把旧 PPTX/完整内审目录搬来。

## 验证边界

详见 `reports/verification.md`：本地程序与 FakeModel 机制验证、真实浏览器转换与静态页面检查。没有付费模型调用，没有重新解析论文，也没有新模型自主生成的正式 PPTX。许可证仍待确认，Node 传递依赖告警需后续处理。


## 后续模型路由修正（2026-11-13）

发布副本的源图像/表格检查原先沿用未批准的Qwen Max默认值，现已统一为DeepSeek Flash。正式工厂、Demo预检和环境模板已对齐；本地环境文件仅修改模型路由行。旧的未批准环境覆盖在模型创建前拒绝。普通图像和表格单元格工具分支均有离线路由回归。该修改没有重写Harness、工具Schema、审核门禁或原项目；历史Qwen Max调用记录原样保留。


## 发布收尾更新（2026-11-13，后续状态）

前文为初次整理时记录。当前展示切换为自制 SignalFusion 的真实单页运行，旧论文封面/截图与历史展示数据留本地并从 Git 和候选排除。

新增 showcase/demo-b-2026-11-13：输入 PDF、HTML v3/资源、截图、可编辑 PPTX 按原始字节复制；运行记录仅保留白名单数值、工具顺序和错误分类。PowerPoint 最终渲染失败明确保留。

本轮仅调整文档、静态展示、打包白名单与发布相关测试，不改 Harness、领域业务、Skills、模型配置或原始运行。负责人后续选择 No license，移除的是发布时新增的许可占位说明；Harness 原有声明保持不变。验收见 RELEASE_CLOSEOUT.md。
