# 独立发布副本验收记录 · 2026-11-13

结论：**离线机制与独立安装验证通过；真实模型单页闭环尚未验证；许可待确认。** 未宣称自主 PPTX 交付成功。本轮真实模型调用 0、模型 API 费用 0；依赖下载与本地程序运行不属于模型调用。

| 检查 | 实际结果 |
|---|---|
| 全新 Python 环境 | Python 3.12.12；`include-system-site-packages=false`；从约束文件安装；`pip check` 无冲突 |
| 独立模块来源 | Harness / Domain / Application 均来自发布目录；另用 Python -I + 禁止打开原项目文件的审计钩子预检通过，Node 使用系统安装及新目录 node_modules |
| 原代码保护 | 95 个来源文件逐项 SHA256 与复制前一致；没有对原项目执行文件写入。该哈希范围不是整个磁盘的完整快照 |
| 离线回归 | **89 passed**，0 failed / error / skipped；耗时 5.972s（pytest 报告值，非整个整理耗时） |
| 工具和 Skills | 正式 full 配置 40 工具、3 Skill；无新增模型路由框架 |
| Demo C | 两版实际 Chromium 截图、相同 Session 恢复、2 次预期错误；程序布局检查 pass；内容/视觉审核仍未进行，所以正式导出被拒绝 |
| Demo C 墙钟 | 两次 Harness run 合计 2.72s；不含安装及输入准备；FakeModel 字符估算不当作真实 Token |
| Demo B | 正式入口和环境预检通过；没有调用真实模型验证账号、ID、审核或生成质量 |
| Demo A | Chromium 实际验证桌面 1440px / 移动 390px：0 丢失图片、0 页面错误、0 页面横向溢出、0 外部请求 |
| 可编辑转换 | 原有程序测试实际调用 Chromium + PptxGenJS，检查 XML 文本/背景/图片和禁止科学图 cover 裁剪；是低层合成夹具，不是正式审批 PPTX |
| PowerPoint 最终渲染 | 本轮未执行新 PPTX 的 COM 渲染；仅展示已存在的历史候选封面截图，且明确区分版本 |

## 失败与最小修复记录

1. 无约束安装会拉取更新主版本及大量无关传递包。新增兼容版本约束，并另建干净 venv 从约束开始安装，检查通过；未把初始试装环境称为唯一验证环境。
2. 保留模块外层目录时，pytest importlib 模式与同名包冲突，出现 18 个收集错误。发布配置改用默认导入方式及仓库内相对 src 路径，解决。Harness 源码未修改。
3. 系统临时目录权限导致本地浏览器失败。改用发布目录 `.build/tmp` 重新执行，真实渲染通过，没有跳过检查；最初失败日志保留。
4. 新预检辅助脚本直接读取 `pptxgenjs/package.json` 被包 exports 限制拒绝。改用当前 node_modules 中的元数据文件，89 项测试通过。
5. 独立沙箱进程间 localhost 访问被阻断。增加仅本机、同进程临时 HTTP 服务验证脚本，验证后自动关闭。与模型能力无关。
6. Demo C 判定要求实际双版本截图存在，避免把绑定保存成功但 closeout partial 当作演示完成。失败的初次尝试仍保留。

## 未解决事项

- `npm audit` 报 2 项 high：PptxGenJS 的 `image-size` 传递依赖涉及特定图像解析拒绝服务风险（GHSA-5p2g-fcmc-qvqq / GHSA-w3rx-r6r6-pgpr）。未执行 `audit fix --force`、未升级导出库。当前只验证自制可信图像，不是可接收任意不可信上传的托管服务。修复/升级需后续兼容回归。
- 许可按项目负责人选择保留待确认；PyMuPDF 及其他第三方许可尚需发布前复核。
- 真实模型 ID、Key/区域权限、费用和最终单页质量未验证；真实运行不得根据预检宣称通过。
- 完整 PDF Pipeline、Linux/CI 实际执行与新 PPTX 最终视觉一致性未在本轮验证。

## 本地可追溯文件

以下均位于本发布目录，不复制旧项目原始日志：

- `.build/clean-install.log`、`.build/clean-env/pyvenv.cfg`、`requirements-tested.txt`：干净环境。
- `.build/pytest-release.xml`、`.build/pytest-release.log`：最终 89 项测试。
- `reports/pytest-initial.log`、`reports/pytest-portable-02.log` 等：早期失败（仅本地，默认不发布）。
- `outputs/offline-final/`：脚本模拟的 `initial/resumed-events.jsonl`、正式 Session、任务版本、双版 HTML 和截图、`result.json`。
- `outputs/preflight-final/preflight.json`：真实入口无 API 预检。
- `outputs/showcase-verification/desktop.png`、`mobile.png`、`result.json`：实际静态网页检查。
- `.build/npm-audit.json`：原始依赖审计；`.build/copied-source-exact.patch`：复制源码的精确差异（含被删除的私有路径，仅本地保留）。
- `docs/source_manifest.json`、`docs/changed_files.json`、`docs/exhibit_provenance.json`：公开候选的来源及哈希。

公开候选只包含脱敏摘要，不包含上述原始本机日志、虚拟环境或真实凭据。发布包白名单及哈希见 `release_manifest.json`。
