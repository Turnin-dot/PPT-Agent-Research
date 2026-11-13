# PDF 资产读取与结构化工具结果

本文件仅说明读取接口与状态，不规定规划、制作或审核顺序。准确参数以当前工具定义为准。

## 证据可信度边界

`reliability.states` 分别记录 visual、text、structure、semantic 的 verified/unverified/conflict/uncertain/stale。
旧版pass及is_verified最多代表截图质量，不迁移成文字、结构、语义全部通过。当前局部核实只认证指定单元格，
不认证整张表。原始table_body保留；发现差异时用get_asset读取content_verifications或read_file读取报告。
关键实验配置依赖异常符号或空白时，可用inspect_image的table_cells指定1-based数据行和逻辑列，
table_header_rows明确跳过的HTML表头行数。实际图像进入独立模型，trace记录数量、版本、提交及响应状态。
空白OCR不等于未启用，不为所有表格逐格重识别。source_pages支持跨页合并正文检索，记录本身仍只返回一次。

## 只读入口

- `get_paper_context(manifest_path, segment_index=0, input_budget_tokens=80000)`：程序化逐页原始资料，
  含正文、表格文本、图注、既有图像描述、几何和必要版本状态；不生成理解或规划。本段正文直接完整返回，
  不需要再打开result_ref拼同一段。首次输入已有paper_context时先复用；存在pending_segments时按相同预算
  读取后续段。覆盖完整指存量记录均纳入，仍须保留空文本、缺图或过期状态，不等于PDF无遗漏。

- `get_document_overview(manifest_path)`：页级计数、章节线索与图表 ID 索引；不是自动论文总结。
  `page_count_basis` 区分页数来自 PDF 还是资产最高页；`review_summary` 区分当前全量覆盖与当前通过。
- `query_assets(manifest_path, page_numbers, asset_types, query, offset, limit)`：目录、图注、描述、几何和版本。
  不返回整篇正文/表格正文；有 `next_offset` 时可以继续读取。
- `get_evidence` 与 `get_evidence_bundle` 共用实现；支持多个 `evidence_ids`、多个 1-based `page_numbers`，
  以及正文、图注、表格、语义/结构说明关键词。给出多个筛选条件时取交集。
- `get_asset`：精确 ID/版本读取；`include_text` 控制原文，`include_raw=true` 将原记录加入完整结果。
  表格截图也在资产 `path`；不需要从 table_body 重新绘制才能使用图片。

## 字段和状态

- `captions` 是图注数组；`table_body` 是提取表格内容。证据文本包含相关原文/图注/表格。
- `semantic_description`、`structure_description` 是辅助说明，不替代论文证据。
- 几何包括 `pixel_width/pixel_height/aspect_ratio/orientation`；bbox 的单位由 `bbox_coordinate_space` 决定。
- `description_status` 非 current 时，不把旧描述当作当前事实。旧描述可能仍匹配关键词，以便定位候选。
- `review_status` 是原资产结论；`review.applicability` 表示报告适用性；`is_verified` 需要当前版本报告佐证。
- `file_exists` 与 `visual_inspection_completed=false` 都不能用于声称已经看过图片或核对通过。
- 资产修改后，关注 get_task_state.reference_health 的 affected_slide_ids，并修正相关精确版本引用。

## 有界摘要、完整结果与续读

工具摘要为合法 JSON，带 `summary_only`、集合计数、状态、对象引用与 `result_ref`。
列表和文字可能只是示例/摘录；需要完整本次业务结果时使用已注册 `read_file(path=result_ref, offset, limit)`。
Harness 内 result_ref 位于工作区中，Session 恢复后仍可读取；不要使用摘要的前几项当成全部资产。

证据工具的 `next_cursor={offset,text_offset}` 用于继续下一段业务读取，包括单个超长表格。
保持相同的 manifest、筛选条件、max_chars 和受检版本；Manifest 变更后重新确认游标适用性。
`text_complete` 只说明本次业务返回是否包含该记录全文，摘要的 text 仍可能是摘录。
一个 result_ref 只保存本次读取范围，不能代替沿游标继续读取全文。

工具执行成功与内容通过不同。页面 `needs_revision`、交付 `incomplete` 是有效结果；执行错误看
ToolMessage.is_error/error_code。输出校验、渲染或保存失败可能已有文件副作用，先读取引用，不原样重试写操作。
