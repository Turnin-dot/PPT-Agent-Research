# 当前 PDF 资产工具契约与边界

本文件依据 `packages/ppt_domain/src/ppt_agent_domain/pdf_assets/tools.py` 与当前服务实现整理。参数的
最终权威来源仍是 Harness 暴露的工具定义；本文件强调选择、状态和副作用。

## 工具概览

| 工具 | 主要输入 | 关键结果 | 资产影响 |
|---|---|---|---|
| `parse_pdf` | PDF、可选 MinerU 结果、解析范围 | manifest、revision、资产计数、诊断 | 创建候选资产；相同 hash+scope 可复用 |
| `view_pdf_page` | PDF、1-based 页码 | 页图、尺寸、坐标；可选描述 | 只读 |
| `review_pdf_assets` | manifest、可选资产/页范围 | coverage、verdict、报告、计划、错误 | 不改资产内容；写报告和核对状态 |
| `crop_pdf_asset` | manifest、页码、bbox | 新资产版本、图片路径、新 revision | 写资产，旧报告 stale |
| `update_asset_mapping` | manifest、资产 ID、图注/编号 | 新资产版本、新 revision | 写资产，旧报告 stale |
| `register_pdf_asset_issue` | manifest、页码、问题 | unresolved issue | 不改资产内容 |
| `re_recognize_pdf_region` | manifest、页码、bbox、类型 | 识别文本、报告、新版本 | 先裁剪再识别，旧报告 stale |
| `validate_pdf_asset_manifest` | manifest、检查开关 | 结构、引用、文件与版本诊断 | 只读；不代替视觉核对 |
| `prepare_pdf_assets` | PDF、核对页范围、自动修复开关 | parse+review+repairs+未解决问题 | 依参数可能写资产 |

## `parse_pdf`

```text
parse_pdf(
  pdf_path,
  result_dir="",
  force=false,
  page_start=null,
  page_end=null,
  allow_unverified_reuse=false
)
```

- `page_start` / `page_end` 是 MinerU 的 **0-based** 页范围；省略或 `null` 表示默认整篇。
- `result_dir` 必须指向已有 MinerU `auto` 结果目录。工具会检查其中 `_origin.pdf` 与目标 PDF 的
  hash；不匹配时默认拒绝。
- `allow_unverified_reuse=true` 只表示显式接受来源无法验证或不匹配的 MinerU 结果，绝不表示资产
  已核对。只有用户明确接受该风险且结果确实属于目标材料时才使用，并保留 diagnostics。
- `force=true` 会绕过已有 manifest 复用。没有来源或范围变化时不要使用。
- 相同 PDF hash 与解析 scope 已有 manifest 时，返回 `reused=true`。
- 关注 `manifest_path`、`revision`、`review_verdict`、`asset_counts`、`diagnostics` 和
  `mineru_result_dir`。新解析默认 `review_verdict=not_reviewed`。

## `view_pdf_page`

```text
view_pdf_page(pdf_path, page_number, output_dir="", describe=false)
```

- `page_number` 是 **1-based**。
- 始终返回页图路径、像素尺寸、PDF point 尺寸、DPI 和坐标说明；`read_only=true`。
- `describe=false` 只渲染并返回引用，不能把路径当作模型已查看页面。
- `describe=true` 才会把实际图像字节传给内部模型，并返回 `description`、`internal_model` 和
  `model_usage`。
- 适合确认原页、坐标或局部问题，不登记资产，也不产生核对通过结论。

## `review_pdf_assets`

```text
review_pdf_assets(
  manifest_path,
  asset_ids=[],
  page_numbers=[]
)
```

- 两个范围参数都是原生数组，页码是 1-based。兼容层仍接受旧 `*_json` 字符串，但新调用不要使用。
- 两者均为空数组时，覆盖整篇原页与需审核资产；公式原记录保留，排除独立公式视觉核对。
- 只给页码时，核对这些页面及页面上的全部已登记资产。
- 只给资产 ID 时，核对这些资产及其来源页。
- 同时给出时，只保留同时落在指定页面内的指定资产。
- 当前工具内部负责全量材料估算、动态分批、单页拆分、检查点保存、失败局部拆分和相同计划恢复。
  不要由主 Agent 手工创建批次。
- 关注：
  - `execution_status`：外层核对操作完成并保存报告时为 `succeeded`；
  - `review_run_status`：`complete` 表示范围完整，`partial` 表示仍有失败或未覆盖范围；
  - `review_verdict`：`pass` / `needs_repair` / `uncertain`；
  - `applicability`、`manifest_revision`、`scope`；
  - `coverage.missing_pages`、`missing_asset_ids`、`failed_batches`；
  - `completed_batch_count`、`failed_batch_count`；
  - `issues`、`execution_errors`、`consistency`；
  - `plan_path` 与 `report_path`。
- 相同 revision、scope、契约和输入指纹可恢复计划并跳过成功批次。revision 改变后旧报告 stale；
  工具可按页面输入指纹采用未受影响的成功批次，重新汇总并绑定当前版本，不能直接沿用旧整体结论。
- `is_verified=true` 只适用于返回的 scope。局部页通过不能解释为整篇通过。
- `full_document_coverage=true` 才表明请求范围包含整篇应检查对象；仍需结合 complete、pass、current。
- 正常图表同时保存简短语义与结构描述；有问题截图的描述标 uncertain，裁剪/配对后旧描述 stale。
- 纯文本/参考文献页仍检查原页是否遗漏图表，但不凭空创建图表描述。不因审核 JSON 协议错误重新 OCR 正文。

## `crop_pdf_asset`

```text
crop_pdf_asset(
  manifest_path,
  page_number,
  bbox,
  asset_id="",
  asset_type="image",
  coordinate_space="pdf_points"
)
```

- `bbox` 是四个数字组成的原生数组 `[x0,y0,x1,y1]`。
- `coordinate_space` 仅支持 `pdf_points`（左上原点）或 `mineru_normalized_0_1000`。
- 指定 `asset_id` 时更新已有资产；为空时创建手工派生资产。
- 返回 `asset_id`、`asset_version`、`manifest_revision`、`image_path` 和
  `previous_reviews=stale`。
- bbox 必须有原页或核对报告依据。不要凭猜测裁剪，也不要用相同参数反复操作。

## `update_asset_mapping`

```text
update_asset_mapping(manifest_path, asset_id, caption, figure_number="")
```

- 用于修正候选资产与图注、图表编号的映射，不重新裁剪图像。
- 需要已存在的 `asset_id` 和有证据支持的 caption/number。
- 返回新资产版本与 manifest revision，并使旧报告 stale。

## `register_pdf_asset_issue`

```text
register_pdf_asset_issue(
  manifest_path,
  page_number,
  issue_type,
  description,
  asset_id=""
)
```

- 用于登记漏提取、无法判断、无法自动恢复或需要人工处理的问题。
- 如果问题没有对应已登记资产，`asset_id` 留空；不要虚构 ID。
- 返回 `issue`、当前 `manifest_revision` 和 `assets_modified=false`。
- 它记录问题，不代表问题已修复，也不会生成视觉核对结论。

## `re_recognize_pdf_region`

```text
re_recognize_pdf_region(
  manifest_path,
  page_number,
  bbox,
  recognition_kind,
  asset_id=""
)
```

- `recognition_kind` 用于说明要识别的内容类型，如 text、table 或 equation；当前工具定义没有更窄的
  枚举校验，仍应使用与问题相符的明确值。
- 工具先调用裁剪逻辑，再把区域图像真实传入模型。因此它是写操作，会产生新版本并使旧核对报告
  stale，不是只读 OCR。
- 返回 `recognized_text`、`report_path`、模型与用量；识别结果仍需根据任务风险重新核对，不能自动
  视为 verified。

## `prepare_pdf_assets`

```text
prepare_pdf_assets(
  pdf_path,
  result_dir="",
  page_numbers=[],
  auto_repair=false,
  allow_unverified_reuse=false
)
```

- 这是局部复合入口，当前实现依次调用解析和核对；解析步骤可以命中相同 hash+scope 的缓存。
- 空 `page_numbers` 会核对整份 PDF；指定页面时只核对该范围。
- `auto_repair=false` 时只返回问题，不修改候选资产。
- `auto_repair=true` 当前只自动处理同时具备 `repair_action=recrop`、合法资产 ID 和建议 bbox 的问题，
  并受尝试次数与总耗时限制。它不会自动执行 mapping 修复、重新识别或缺失登记。
- 关注嵌套的 `parse`、`review`、`repairs`、`unresolved_issues`、`stopped_reason` 和总耗时。
- 只想查看原页、只想解析或已有 manifest 时，不要为了形式统一调用该组合工具。

## `validate_pdf_asset_manifest`

```text
validate_pdf_asset_manifest(
  manifest_path,
  check_source_hash=true,
  check_asset_files=true
)
```

- 只读检查 schema、源 PDF、hash、资产 ID 唯一性、页码、版本、bbox、资产文件和 current review
  是否确实对应当前 revision。
- `validation_status=pass` 只代表清单结构与引用检查通过，不代表图像、表格或公式已经视觉核对通过。
- 读取外部迁移产物、怀疑路径失效或修复后准备继续时适合先调用；普通局部读取无需机械调用。

## 当前未实现或未暴露的能力

- 架构图概念名 `validate_asset_manifest` 不是实际工具名；实际只读工具是
  `validate_pdf_asset_manifest`。
- 没有 PDF 领域的 `get_asset` 或 `inspect_image` 工具。可通过当前 Harness 的文件读取能力读取 JSON
  manifest/report；候选图像的真实视觉检查目前由 `review_pdf_assets`、`view_pdf_page(describe=true)`
  或 `re_recognize_pdf_region` 内部完成。
- 修改任一资产会把已有 review 全部标成 stale。当前实现可以只重核受影响范围来完成局部任务，
  但还不能自动把旧 revision 的未受影响覆盖迁移成新 revision 的整篇 verified 报告。需要整篇完成
  结论时，应重新取得当前 revision 的全量报告，或明确说明当前仅完成局部复核。
- 正式 `review_pdf_assets` 当前自行串行执行计划批次；容量基准脚本不等同于生产工具已启用并发。

## Harness 输出、长结果与错误

- 上述九个工具均声明内部 Pydantic `result_schema`。该 Schema 不会发送给模型作为工具参数；它在
  业务函数返回后、成功消息产生前校验实际结果。
- 规范业务结果、模型摘要和日志元数据彼此分离。组合工具读取服务返回值或
  `Tool.invoke_result(...).value`，不解析模型摘要。
- 在项目 Harness 中，完整规范结果保存为 `.tool-results/<tool>/<call-id>.json`。模型摘要末尾和
  `ToolMessage.result_ref` 都会提供引用；使用 `read_file` 的 `offset/limit` 分页读取。
- `INPUT_VALIDATION_FAILED` 可按字段修正后重试。`OUTPUT_VALIDATION_FAILED` 表示实现与输出协议不符，
  不代表内容问题。`RESULT_PERSIST_FAILED` / `RESULT_RENDER_FAILED` 需先检查保留的产物引用。
- `review_verdict=needs_repair` 是有效核对结论，不是工具执行失败；`review_run_status=partial` 也会保留
  已完成批次、覆盖缺口、执行错误、计划和报告，不能冒充全量完成。
