---
name: pdf-asset-preparation
description: 指导 PPT 主 Agent 根据 PDF、manifest、核对覆盖与资产版本，按需选择解析、查看、全量或局部视觉核对及修复工具。用于论文 PDF 资产准备、恢复和问题处理；不用于不涉及项目资产库的一般 PDF 问答。
---

# PDF 资产准备决策指南

## 目标

根据用户当前目标和已有资产状态选择最小必要动作。不要把 PDF 资产准备变成每次都从解析开始的
固定工作流。主 Agent 决定是否进入、调用哪个工具和处理什么范围；工具内部负责稳定的解析、
分批核对和有限修复逻辑。

## 开始前先判断

当前解析策略为 Pipeline 主资产＋离线 VLM 公式/表格补充。`parse_pdf(vlm_result_dir=...)`
只读取已有 VLM content_list 缓存，不提交整篇 VLM 解析任务。匹配依赖类型、物理页与原始 bbox；
保留全部 Pipeline 原字段和图片。缺少缓存、匹配歧义或公式覆盖不足时回退，并读取补充决策记录。
VLM 的图注可能串配，因此不覆盖 Pipeline 的 captions；匹配不等于 OCR 内容正确。

1. 当前请求是完整论文汇报、局部页面制作、查看解释，还是修复已知问题。
2. 是否已有与当前 PDF 内容和解析范围匹配的 `manifest_path`。
3. 所需页面和资产是否存在，当前 `manifest_revision` 与资产版本是多少。
4. 是否有覆盖当前范围与版本的报告；报告是 `current` 还是 `stale`。
5. 当前请求需要原始页、候选资产、已核对证据，还是只需要说明现有状态。

缺少这些信息时，优先读取已有工具结果、manifest、plan 和 report；不要凭路径名或旧对话假设状态。

## 选择最小必要工具

| 需要 | 选择 |
|---|---|
| 新建或复用 MinerU 资产清单 | `parse_pdf` |
| 查看原始 PDF 页、尺寸和坐标 | `view_pdf_page` |
| 对当前 manifest 做全量或指定范围视觉核对 | `review_pdf_assets` |
| 从原页重新裁剪或新增区域资产 | `crop_pdf_asset` |
| 修正图表编号或图注配对 | `update_asset_mapping` |
| 登记缺失或暂时无法解决的问题 | `register_pdf_asset_issue` |
| 对指定区域重新识别文本、表格或公式 | `re_recognize_pdf_region` |
| 检查清单结构、对象引用、文件与当前版本 | `validate_pdf_asset_manifest` |
| 新 PDF 的解析、核对及可选安全重裁剪组合 | `prepare_pdf_assets` |

以下不是当前 PDF 工具集中的可调用工具：`validate_asset_manifest`（实际名称是
`validate_pdf_asset_manifest`）、`get_asset`、`inspect_image`、
`crop_asset`、`re_ocr`。不要按架构图中的概念简称发起调用。

需要构造具体参数、解释返回字段或确认读写影响时，调用
`read_skill(name="pdf-asset-preparation", resource="references/tool-contracts.md")`。遇到恢复、局部修复
或任务切换时，按需读取 `references/scenarios-and-recovery.md`。不要在普通调用中一次加载全部资料。

## 核对范围与完成判断

PDF 资产模型审核正式使用 `deepseek:deepseek-flash`，通过现有 Harness 模型适配器调用。
Qwen Flash 负责后续论文理解与页面规划的独立审核，不能与 PDF 资产审核角色混用。

当前审核契约为 `ppt-visual-assets/v3`：所有原页都检查图表遗漏，图片和原表截图检查完整性、
清晰度、配对与重要脚注。正文保留阅读顺序和明显缺失问题，不逐字校对；公式原文/原始记录
保留，不进行独立视觉审核。不要为连字符、DOI、LaTeX 或 HTML 表格细节反复重新识别。
视觉审核同时保存图表语义、结构、类型、布局提示，尺寸由程序计算。优先复用
`description_status=current` 且 provenance 对应当前资产版本的描述；裁剪后旧描述失效。
需要按页读取时，可用 `validate_pdf_asset_manifest(manifest_path=..., page_numbers=[...])`；
返回正文/公式原文及图表索引、描述、几何与状态，不需要读取完整 manifest。

- `parse_pdf` 成功只代表候选资产已登记，不代表视觉核对通过。
- 外层工具执行失败由 `ToolMessage.is_error=true` 和结构化 `error_code` 表示。成功的核对业务结果中，
  `execution_status=succeeded` 表示报告已生成；`review_run_status=complete|partial` 表示批次执行是否
  覆盖完整；`review_verdict` 表示内容结论；`applicability` 表示报告是否仍对应当前版本。不能互相替代。
- `coverage.status=complete` 只表示指定范围全部执行完成，不表示内容全部通过。
- `review_verdict=pass` 只有与 `scope`、`manifest_revision` 和 `applicability=current` 一起解释才有意义。
- `is_verified=true` 只证明返回报告中的指定范围和版本，不自动证明整份 PDF。
- 本契约的通过重点是图表截图质量与粗粒度正文覆盖，不证明HTML单元格、所有数字或公式均正确。
  PPT侧读取reliability区分截图与内容验证。若当前工具清单提供inspect_image，可按需核实关键表格单元格；
  get_asset和inspect_image属于PPT工具集，并非本PDF工具集；不存在时不要调用。不要因单个符号疑点重跑全篇。
- 完整资产准备要求：必需范围覆盖完整、无失败批次、报告属于当前 revision，并根据任务要求处理或
  明确保留 `needs_repair` / `uncertain` 问题。
- 局部查看、解释或修复可以先完成当前请求；同时说明未检查页面、资产或整篇一致性仍未完成。

全量核对的分批、输入预算、超时、失败拆分和恢复由 `review_pdf_assets` 内部管理。不要让主 Agent
手工复制批次调度，也不要在 Skill 中假设固定页数、并发数或 token 数。
`full_document_coverage=false` 的通过报告仅适用于指定范围。修复后重新请求完整范围时，
工具会按页面输入指纹复用未受影响的成功批次；整体状态由完整范围汇总确认。

## 修改与版本规则

- `view_pdf_page` 只读。
- `review_pdf_assets` 不修改资产内容，但会保存计划、报告并更新核对状态。
- `crop_pdf_asset`、`update_asset_mapping`、`re_recognize_pdf_region` 会修改或新增资产、增加版本，
  并使旧核对报告失效。
- `register_pdf_asset_issue` 记录未解决问题，不修改资产内容。
- 修改后先核对受影响范围。若要重新声明整份 PDF 已完成，必须确认当前实现是否已有覆盖当前 revision
  的整篇报告；不能用旧版全量报告加新版局部报告自行推断全局通过。

## 错误处理

- 参数错误：按工具 Schema 修正页码基准、原生数组、bbox、坐标系、路径或资产 ID，不要原样重试。
- 外部 MinerU 结果 hash 不匹配时，只有用户在当前请求中明确知晓并接受该风险，才设置
  `allow_unverified_reuse=true`；仅提供或要求使用某个 `result_dir` 不算授权。
- 执行失败或超时：读取 `execution_errors`、失败批次和已有覆盖；相同 scope 与 revision 可再次调用
  `review_pdf_assets` 以利用断点，不要重新解析整篇 PDF。
- 工具摘要带有 `result_ref` 时，完整规范结果已由 Harness 保存。需要查看全部问题、嵌套记录或恢复
  处理时，用 `read_file(path=result_ref, offset=..., limit=...)` 分页读取；不要从摘要反推业务对象。
- `OUTPUT_VALIDATION_FAILED`、`RESULT_PERSIST_FAILED` 或 `RESULT_RENDER_FAILED` 可能发生在业务写入之后。
  先检查错误中的 `artifact_refs` / `result_ref`，不要自动重放有副作用的裁剪、配对或识别调用。
- `needs_repair`：按问题类型选择裁剪、更新配对或重新识别；修复后核对受影响范围。
- `uncertain`：补充原页或扩大核对范围；证据仍不足时保留不确定性。
- `stale`：旧报告不能支持当前版本。重新核对需要使用的范围。
- 多次尝试仍失败：保留正确资产和成功报告，使用 `register_pdf_asset_issue` 登记问题，并向用户说明
  未完成范围、原因和建议输入。

工具结果里的本地图片路径只是对象引用，不等于模型已看过图片。只有工具明确传入图像并产生视觉
结果时，才能声称完成视觉检查。

## 结束当前动作

返回或记录以下信息，便于下一轮与中断恢复：

- 当前 `manifest_path` 和 `manifest_revision`；
- 本次处理的页面与资产范围；
- 执行状态、核对结论、适用性和覆盖缺口；
- 新资产版本、报告或计划路径；
- 未解决问题与下一步建议。

结束当前回答不等于整份 PDF 资产准备完成。若用户改变需求，重新按新目标选择必要范围，不必回到
固定起点。
