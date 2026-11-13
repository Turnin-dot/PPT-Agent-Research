# 场景选择、恢复与参考路径

以下路径是决策示例，不是必须照做的全局工作流。始终根据当前任务、已有 manifest、报告范围和
revision 缩小动作。

## 1. 新 PDF，制作完整论文汇报

判断：需要整篇候选资产，并最终知道整篇视觉核对覆盖情况。

参考路径：

1. 如果希望一次获得解析与整篇核对结果，调用 `prepare_pdf_assets`，页面范围留空。
2. 首次建议 `auto_repair=false`，先读取完整问题；只有允许修改派生资产且问题是安全重裁剪时，才
   使用自动修复或单独调用修复工具。
3. 检查嵌套 review 的 coverage、revision、verdict 和 unresolved issues。
4. `needs_repair` 不等于执行失败。正确资产可以继续使用，但正式完成资产准备前要修复或明确保留。

也可分别调用 `parse_pdf` 与 `review_pdf_assets`，例如需要在核对前检查解析诊断时。

## 2. 新 PDF，只查看或解释某一部分

- 只需看原始某页：直接 `view_pdf_page`；需要模型解释可设置 `describe=true`。无需先解析整篇。
- 需要使用某页提取资产：`parse_pdf` 后对相关页调用局部 `review_pdf_assets`。
- 只做阶段性解释时，说明未执行整篇资产核对；不要为了完整形式启动全量组合工具。

## 3. 已有 manifest 或资产库

先核对 PDF hash/scope、manifest revision、资产 ID 和已有报告。已知 `manifest_path` 时直接使用，
不要无故再次解析。即使调用 `parse_pdf`，也应期待 `reused=true`，而不是把复用误认为新解析。

只有 PDF 内容、解析范围或 MinerU 结果确实变化时，才使用 `force=true` 或建立新 manifest。

## 4. 已解析但尚未全量视觉核对

- 完整资产准备：对 manifest 调用空范围的 `review_pdf_assets`。
- 当前只需要部分页面：核对相关页或资产，完成用户当前请求，同时报告整篇仍为未完成。
- 不要把 manifest 的存在或 `review_verdict=not_reviewed` 解释成失败；它表示还没有当前结论。

## 5. 只完成部分批次，存在失败或未检查范围

读取 `plan_path`、coverage、failed batches 和 execution errors。若 manifest revision、scope 和配置未变，
用相同参数再次调用 `review_pdf_assets`；工具会利用已有计划并跳过成功批次。

如果错误是参数、无效资产 ID 或报告结构问题，先修正原因。不要对同一个确定性错误原样重试，也
不要重新调用 `parse_pdf` 来恢复模型请求失败。

## 6. 页面和资产已核对，只读取指定内容

确认报告对当前 revision 和当前 scope 仍是 `current`。读取已有 manifest/report 中的对象引用即可；
无需再次全量核对。若要重新查看原始证据，调用 `view_pdf_page`，但它不会改变 verified 状态。

当前没有独立 `get_asset`/`inspect_image` PDF 工具。不要发明调用；需要新的候选资产视觉检查时使用
局部 `review_pdf_assets`。

## 7. 图片缺失、裁剪不完整、混入正文或清晰度不足

1. 用 `view_pdf_page` 获取原页尺寸与坐标，或读取 review issue 的 `suggested_bbox`。
2. bbox 有可见依据时调用 `crop_pdf_asset`；缺失资产可不传 `asset_id` 创建派生资产。
3. 修改后检查新 `asset_version` 与 `manifest_revision`。
4. 对新资产或受影响页重新调用 `review_pdf_assets`。

如果无法确定边界，先保留 `uncertain` 或登记 issue，不要凭猜测裁剪。清晰度受原 PDF 限制时，
登记问题并请求更高质量来源比反复放大更可靠。

## 8. 图表编号、图注或正文引用配对错误

根据原页可见编号和图注确认目标资产，再调用 `update_asset_mapping`。该工具只修映射，不修图像。
返回新版本后局部复核。若一个图注对应多个候选或跨批次一致性无法判断，保留问题并扩大核对范围。

## 9. 表格、公式或关键数字识别疑点

先确定原页与 bbox，然后调用 `re_recognize_pdf_region`，使用与内容相符的 `recognition_kind`。该工具
会写入新资产版本，因此随后必须复核受影响范围。识别文本是候选结果，不替代原页证据。

## 10. 跨页内容、重复资产或整篇覆盖确认

需要整篇完成结论时，使用空页面和资产范围调用 `review_pdf_assets`。工具内部会做所有页面/资产
覆盖检查以及结构化的跨批一致性检查。局部页通过不能回答“整篇是否覆盖完整”。

## 11. 修改后旧报告 stale

局部任务先复核受影响页或资产，避免为了当前小修改立即重跑无关范围。但当前实现不会把旧 revision
的全量覆盖自动迁移到新 revision：如果最终要声称整篇当前版本已完成，必须获得当前 revision 的
全量报告，或明确交付状态仅为局部复核完成。

## 12. 工具失败、超时、参数错误或结果无法解析

- 文件不存在：确认路径和工作区，不要换模型重试。
- 页码错误：`view/review/repair` 使用 1-based；`parse_pdf` 的解析起止页使用 0-based。
- 数组参数错误：新调用使用原生数组；若恢复旧调用中的 `*_json` 字段，其值必须是合法 JSON 数组。
- bbox/坐标错误：根据 `view_pdf_page` 返回坐标说明修正。
- 未知资产 ID：重新读取当前 manifest，避免使用旧 revision 的 ID。
- 模型超时/连接错误：保留成功批次；相同 scope/revision 再次调用 review 以恢复失败部分。
- 无效模型报告：按执行失败处理，不能根据空 issues 推断 pass。

重试要有限，并针对原因调整。连续失败后登记问题并请求用户输入或外部状态变化。

## 13. 用户中途修改需求或任务中断后继续

重新判断新目标所需范围。保存并复用 `manifest_path`、revision、plan/report 路径和 unresolved issues。
如果用户从完整汇报改成局部页面，停止不再必要的全量动作；如果从局部扩大到整篇，启动缺失范围的
核对。不要因为会话恢复就强制从解析重新开始。

## 14. 多次尝试仍无法恢复

使用 `register_pdf_asset_issue` 记录具体页、问题类型、描述和可选资产 ID。保留所有正确资产与成功
报告，向用户返回：已完成范围、未完成范围、最后错误、是否需要更清晰 PDF/人工 bbox/正确图注，
以及当前成果是否可用于草稿。

## 参考调用路径

### 路径 A：直接查看，不建立资产库

```text
view_pdf_page(pdf_path, page_number=6, describe=true)
→ 回答该页问题，并说明未进行资产解析或全量核对
```

### 路径 B：复用 manifest，局部修复

```text
读取已有 report/manifest
→ 已有可信 bbox 时 view_pdf_page(问题页, describe=false) 只取坐标；否则 describe=true 让模型实际读取原页
→ crop_pdf_asset(有证据的 bbox, asset_id=现有 ID)
→ review_pdf_assets(asset_ids=["..."], page_numbers=[6])
→ 返回新版本与局部复核状态
```

### 路径 C：完整准备但保留人工判断

```text
prepare_pdf_assets(pdf_path, page_numbers=[], auto_repair=false)
→ 若完整且 pass：记录当前 scope/revision
→ 若 needs_repair：按 issue 类型选择独立修复工具
→ 若执行失败：用相同范围恢复失败批次
→ 无法恢复：登记 issue，保留部分成果
```

### 路径 D：修改需求后缩小范围

```text
原计划：整篇核对
用户改为只制作方法页
→ 停止无关动作
→ 核对方法页及其引用资产
→ 完成当前页面，明确整篇覆盖尚未完成
```
