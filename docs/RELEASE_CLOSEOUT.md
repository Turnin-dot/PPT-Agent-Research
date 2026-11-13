# 发布收尾与安全复核 · 2026-11-13

## 结论

Demo 冻结、README、静态展示和本地公开候选核查已完成。**敏感信息/提交范围检查：PASS（有扫描局限）。** 后续负责人已选择 No license，缺少开源许可证不再作为本仓库的发布阻断原因；复制来源声明和第三方义务仍需保留。未推送或初始化项目 Git。

这不是新一轮功能开发。Harness、领域业务、Skills、模型配置以及原始运行均未修改；没有付费模型调用。

## 冻结内容与来源

[展示页](../showcase/index.html) 改为自制 SignalFusion 单页真实运行；[冻结目录](../showcase/demo-b-2026-11-13/README.md) 含源 PDF、HTML v3/图片、实际 HTML 截图、可编辑 PPTX，均与原始字节 SHA256 一致。[provenance.json](../showcase/demo-b-2026-11-13/provenance.json) 可复核。

公开精简记录保留全部 39 次工具调用的名称、耗时、成败和错误分类，33 次模型调用的模型名与 usage。删除的是公开副本中的对话/参数/本机路径字段，不是原始日志里的失败记录；原始 84 个文件继续留在忽略目录 outputs/my-demo-b-03，哈希全部一致。

此次 HTML 双维审核通过，PPTX 已导出；PowerPoint 自动渲染失败两次，整体 incomplete。内部 delivery 的 pass/complete 与最终视觉验收范围不同，README 和展示页均明确披露。没有重做 PPT 或为发布补制截图。

旧论文封面/截图和历史展示数据保留本地，Git 与候选白名单均排除，避免继续带入第三方材料分发疑问。初次来源报告/安全报告保留为历史快照，最新结果在本报告与 PUBLICATION_CHECK.json。

## 修改范围

- README：研究定位、模块职责、三个 Demo 命令、真实结果与限制；区分预制资产和原始 PDF 模式。
- showcase/index.html 与 demo-b-2026-11-13：自有样例及白名单运行记录；HTML/PPTX 本体不改写。
- docs：更新测试状态、手动说明、架构输入模式、发布边界和来源增量说明。
- .gitignore / tools/package_release.py：排除旧展示材料，允许已核验自制 PDF/PPTX/JPEG；扫描 PDF 内容/对象、PPTX XML 和图片元数据，原有环境文件不读取保护保留。
- 发布相关测试：校验冻结文件哈希、图片引用、累计用量、39 次调用/5 次失败、实际可编辑对象和无外部关系，以及二进制元数据的虚构凭据拒绝。

未删除依赖、活跃安装目录、运行证据或无法确认用途的文件。虚拟环境、node_modules、pip 临时目录、模型缓存、.build、outputs 和原始日志继续忽略。

## 安全与 Git

候选扫描未发现真实 Key/Token/私钥或未处理隐私候选。真实 .env 没有读取、输出或复制进报告。4 项宽泛 Windows 路径命中分别是 3 项通用浏览器安装位置、1 项虚构测试路径，不是用户目录或旧项目依赖，因此未修改业务源码。

检查自制 PDF 文本/对象及元数据、PPTX XML/关系/作者信息、PNG/JPEG 元数据；PPTX 无外部关系，作者为 PPT Agent，PDF 无个人作者信息。没有分发原论文、简历、个人文档或原始模型请求。

项目当前无 .git，因此没有实际暂存区、跟踪文件或提交历史可审。通过独立临时 Git 探针核对实际 ignore 与候选可见文件；11 类敏感/临时/历史展示路径全部忽略。最初 bare 探针对 check-ignore 的调用不适用，已保留失败记录并改用独立非 bare 探针复核；没有把项目初始化为 Git。以后实际暂存或导入历史仍需再审。

模式扫描不能排除未知/编码凭据或图片隐写；不是全面法律审查。此前 npm image-size / pptxgenjs 两个 high 受影响包条目继续披露，本轮没有联网重审或升级依赖。

## 离线验收

- **122 passed**，0 失败/错误/跳过。首次 121 通过、1 失败的原因是系统临时目录拒绝 Chromium 写入；仅把 TEMP/TMP 改为本地忽略目录后复测通过，没有改业务逻辑。
- pip check 通过；正式 Harness 的 40 工具 / 3 Skills 预检通过，没有模型请求。
- FakeModel Demo 完成：真实浏览器生成 2 份预览，Session 恢复成功，2 次预期保护拒绝，pptx_delivered=false。
- 静态页桌面/移动检查：无图片缺失、页面错误、横向溢出或外部请求，桌面实际截图已人工查看。
- 102 个受保护源码/Skills/Demo 文件、84 个原始运行文件 SHA256 均保持一致。

## 追溯

- [公开机器摘要](PUBLICATION_CHECK.json)、[冻结来源哈希](../showcase/demo-b-2026-11-13/provenance.json)、[发布文件清单](../release_manifest.json)。
- 私有本地：.build/release-closeout-2026-11-13/baseline.json、verification.json、pytest-retest.xml/log、offline.log、showcase.log、preflight.log、ignore-probe-retest.log；均被忽略。
- 旧发布报告保留当时状态，当前应以上述摘要和本报告为准。

收尾止于可复核本地发布候选。负责人随后选择 No license，根 LICENSE PENDING 占位文件已撤出；源模块原有声明及第三方义务保留。不追加付费测试。旧安全报告留本地，不进入新候选包。
