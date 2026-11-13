# Demo B 真实测试状态 · 2026-11-13

## 当前冻结结果

my-demo-b-03：实际原始 PDF 解析、资产核对、自主单页规划、HTML v3、独立内容/视觉审核及可编辑 PPTX 导出已完成。12 分 35.3 秒，33 次逻辑模型调用，39 次工具调用 / 5 次报错。

**整体 incomplete / export_requires_final_validation。** PowerPoint 实际渲染两次失败（BadImageFormatException / 0x80070570），根因未确认。结构验证使用 compare_rendered_previews=false。正式 delivery 虽保存 pass/complete，不能等同最终视觉验收。

- [冻结产物](../showcase/demo-b-2026-11-13/README.md)、[用量](../showcase/demo-b-2026-11-13/run-summary.json)、[工具轨迹](../showcase/demo-b-2026-11-13/tool-trace.json)。
- 累计输入 1,251,708 / 输出 38,150；缓存子集 1,155,072、推理输出子集 17,303；费用和 SDK HTTP 重试未知。
- Qwen3.8 Flash 主 Agent 29 次 + 内容审核 1 次；DeepSeek Flash PDF/原图 2 次；豆包 Turbo 视觉 1 次，没有 Qwen Max。
- v1/v2 经程序检查驱动修订到 v3；独立内容/视觉模型审核仅在 v3 执行一次。不能把前两次几何修订包装成视觉模型指导修订的效果。
- 原始运行完整保留在本地忽略目录 outputs/my-demo-b-03，公开副本不修改页面、状态或失败证据。

## 历史失败保留

| 试跑 | 当时结果 |
|---|---|
| 最初预制资产试跑 | 18 轮后 HTML 生成/渲染/审核，未完成修订交付；发现内容漏报和字号误判 |
| 最初原始 PDF 限时试跑 | 解析、核对、规划和草稿完成；路径问题致绑定失败，约 9 分 56 秒停止，未导出 |
| 用户 my-demo-b-02 | 151.12 秒，APIConnectionError，未完成，不是超时 |
| 用户 my-demo-b-03 | 当前结果，导出成功，最终 PowerPoint 渲染未通过 |

历史日志与旧 ZIP 保留在本地，不覆盖、不把旧 ZIP 当本轮发行物。一页合成输入无复杂表格/公式，也未运行完整论文的独立逐页/全局规划审核 Harness，不能外推整套稳定交付。
