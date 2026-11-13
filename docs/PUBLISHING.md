# 许可与发布说明

## 当前选择：No license

项目负责人选择暂不添加开源许可证。根目录不保留先前生成的 LICENSE PENDING 占位文件，也不在根安装元数据中宣称正在等待选择许可证。没有添加 MIT、Apache 或 Unlicense；No license 不等于放弃版权或授予任意使用/修改/再分发许可。

不选择许可证本身并不禁止在 GitHub 公开展示代码。GitHub 说明见 https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository 。项目定位应称为公开研究原型或源码展示，不宣称已获得开放源代码许可。

本次只调整本仓库新增的许可说明。复制 Harness 的 Proprietary 元数据、第三方声明和依赖义务保留；No license 不能替代对他人代码的分发授权。代码权属和第三方义务仍应据实际来源核对。

## 发布文件与证据

- showcase/demo-b-2026-11-13 冻结自制输入、原始 HTML/图像、HTML 截图、可编辑 PPTX 和脱敏记录；不是正式任务恢复包。
- 使用 python tools/package_release.py --check 更新白名单与哈希。候选包只在本地生成，不会上传、提交或改变仓库可见性。
- .env、虚拟环境、node_modules、.build、outputs、缓存、完整请求和会话均排除。旧论文展示和旧安全审查报告保留本地，避免与当前许可选择混淆。
- .gitignore 无法清除已有索引/历史。首次提交仅暂存明确白名单，并检查实际 Git blob；后续导入其他历史仍需重新审计。
- PowerPoint 最终渲染失败、既有依赖告警继续披露，不因许可选择修改测试状态。

收尾记录见 RELEASE_CLOSEOUT.md 和 PUBLICATION_CHECK.json；其历史测试结论与当前许可政策分别记录。
