# Demo B 冻结快照 · 2026-11-13

用户实际运行 my-demo-b-03 的公开展示副本。输入为自制一页 SignalFusion 合成 PDF，不是真实论文；图像和数值都是软件测试素材。

- [源 PDF](source.pdf)、[HTML v3](slide.html)、[Chromium 截图](preview.png)、[可编辑 PPTX](final.pptx) 及 resources 图像均按原始字节复制，没有修改页面或审核结果。
- [运行统计](run-summary.json)：12 分 35.3 秒，33 次逻辑模型调用，39 次工具调用 / 5 次工具错误。累计输入 1,251,708、输出 38,150 Token；缓存与推理是子集；费用未知。
- [精简工具轨迹](tool-trace.json)：保留全部工具返回顺序、耗时及成败。5 次工具错误均保留，包括最后两次 PowerPoint 渲染失败；不公开参数、原始对话或机器路径。
- [来源与 SHA256](provenance.json)：文件与本地原始产物一致，原始运行仍保留在 Git 忽略的 outputs/my-demo-b-03。

真实 MinerU 解析、正式资产核对、自主单页规划/HTML、Chromium 渲染、独立内容/视觉审核和可编辑 PPTX 导出已完成。PPTX 来自审核过的 HTML v3：31 个文本、1 张图片、33 个其他形状。

**最终 PowerPoint 自动渲染未完成。** 两次 render_pptx 报 BadImageFormatException / 0x80070570，根因未确认。validate_export 使用 compare_rendered_previews=false，仅验证结构。内部 delivery 虽记录 pass/complete，不能据此宣称最终视觉验收通过。本次整体状态 incomplete，CLI 为 export_requires_final_validation。

截图是 HTML 渲染，不是最终 PPTX 渲染。该单页样例不证明复杂表格、公式、多页规划或完整论文稳定交付。这里是展示快照，不是正式状态恢复包；不要将其作为改过路径的 Manifest、绑定或审核记录导入门禁。重新运行使用正式入口和新输出目录。

当前采用 No license：未提供开源许可证，此展示快照不额外授予源代码或素材分发许可。既有来源声明保留。
