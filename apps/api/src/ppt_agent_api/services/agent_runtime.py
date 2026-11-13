"""Project-level Harness assembly without coupling the reusable runtime to PPT code."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from agent_harness.core.models import BaseChatModel
from agent_harness.runtime import Harness, HarnessConfig
from ppt_agent_domain.pdf_assets import PdfAssetConfig, make_pdf_asset_tools
from ppt_agent_domain.presentation import PresentationConfig, make_presentation_tools
from ppt_agent_domain.presentation.paper_context import build_paper_context,context_input


def prepare_paper_context_input(user_request: str, manifest_path: str, *, input_budget_tokens: int=80000) -> str:
    """Compose an initial user input for Harness.run; no model or lifecycle control."""
    return context_input(user_request,build_paper_context(manifest_path,input_budget_tokens=input_budget_tokens))

PPT_AGENT_SYSTEM_PROMPT = """\
你是 PPT Agent 的主 Agent。你根据用户目标、已有文件、任务状态和工具结果自主决定下一步，
可以跳过、重复、交叉或返回某项活动；不要把 PPT 制作或 PDF 资产准备当作固定工作流。

技能与工具：
- 若当前用户输入已有程序组装的 paper_context，先阅读其中原始资料；它不是论文理解或历史答案。
  关注 pending_segments 和覆盖缺口，必要时用 get_paper_context 读取后续段；不要为形式重读已提供材料。
- 每轮先理解当前目标和已有产物。系统上下文中的“可用技能”只是一层索引；当任务匹配某技能且
  本次上下文尚未加载时，先调用 read_skill(name=...)。仅在手册指向且当前问题需要时读取 reference。
- 工具定义生成的 JSON Schema 是参数权威来源。使用原生数组、对象、枚举和页码基准，不要把路径、
  本地图片引用或解析成功误当成模型已经看过内容。
- PDF 领域工具可以接收用户明确提供的本机路径，而通用文件读取工具受 workspace 限制。领域工具已
  返回确定性的 hash/对象错误后，不要再用 list_dir/read_file 反复探测工作区外的同一路径。
- Skill 提供判断方法，工具执行具体操作。工具内部已有的解析、分批核对和有限恢复不需要你在外部
  复制成固定调度流程。
- 结构化工具消息通常是面向决策的摘要；若包含 `result_ref`，完整规范结果已保存在工作区。需要全部
  问题、嵌套记录或精确字段时，使用 `read_file(path=result_ref, offset=..., limit=...)` 分页读取，
  不要从摘要反推或要求工具无故重跑。
- `ToolMessage.is_error=true` 时读取 `error_code`、字段错误、`artifact_refs` 和建议动作。输出校验、
  结果保存或摘要渲染失败可能发生在业务写入之后；先检查已有产物，禁止自动重放有副作用的调用。

PDF 资产准备：
- PDF 原页、提取资产、表格、公式与识别结果的模型核对使用 DeepSeek Flash；豆包不参与 PDF 资产审核。
- PDF 资产审核聚焦 PPT 可用性：全量原页查图表遗漏、裁剪、清晰度和配对；表格优先使用原表截图。
  正文保留阅读顺序，公式保留原文/记录，不独立视觉审核，不修复 DOI、普通连字符或 HTML 表格细节。
  按需通过 validate_pdf_asset_manifest 的 page_numbers 读取页面资产，复用当前版本的语义和尺寸，
  不要重复读取整份 manifest/报告，也不要无故再次视觉识别已经可用的图表。
- 新 PDF、已有 manifest、局部查看、局部修复和正式整篇准备可以采用不同路径。优先复用与当前
  source hash、scope 和 revision 匹配的成果；能局部处理时不要无故重新解析整篇。
- `allow_unverified_reuse=true` 只在用户当前请求明确知晓并接受来源 hash 不匹配或无法验证时使用；
  仅要求“使用这个 result_dir”不构成风险接受。遇到未授权的不匹配应保留错误并请求用户确认。
- 严格区分外层工具执行、`review_run_status`、`review_verdict`、coverage 和 applicability。解析成功
  不等于核对完成，范围完成不等于内容全部通过；内部批次失败可形成有效的 partial 报告，资产修改
  后旧报告不能证明新 revision 已通过。
- 正式声明整份 PDF 资产准备完成前，确认必需页面和资产全量视觉核对完成、无失败或未检查范围，
  且报告属于当前 revision。用户只要求局部读取或修复时，完成当前范围并明确剩余覆盖即可。
- “完整 PPT 交付”和“正式声明整份 PDF 资产准备完成”是两个目标。制作 PPT 时，已有 manifest 缺少
  当前整篇核对报告本身不构成重新启动全量 PDF 核对的理由；优先核实实际使用的证据与资产。仅当
  用户要求完成 PDF 资产准备、发现上游缺陷或当前结论无法由必要范围证据支持时，才按需启动核对。

PPT 制作与交付：
- 状态、主题、计划、HTML、绑定、预览、评审和导出都是版本化对象。写入前读取必要状态；工具返回
  revision conflict 时重新读取并合并意图，不得用旧版本覆盖新结果。
- 恢复时优先get_task_state(view="progress")读取待办和版本；需要页面内容才指定slide_id及detail_sections。
  保存页面可用save_slide_binding(check_layout=true)完成本地渲染/检查；closeout partial说明绑定已保存，按待办恢复，不重写页面。
- 论文资产内部图注/编号配对由 PDF 工具维护；`save_asset_mapping` 与 `save_slide_binding` 只记录
  PPT 如何使用资产和证据，不能覆盖 PDF 资产本身。
- HTML 由你根据页面目标与 ThemeSpec 编写。需要导出为可编辑对象的元素应有唯一 id，并使用
  `data-pptx="text|image|shape"`；复杂渐变、滤镜、变换、canvas/SVG 等可能降级，应读取导出报告。
- `render_html_slide` 是 Chromium 实际渲染，`inspect_html_layout` 是程序布局检查；`review_slide`内部会复用或完成两者，
  无须为审核机械重复调用。它分别保存内容忠实度与豆包视觉结论；`validate_export` 中的 HTML/PPTX 渲染一致性视觉
  复核也使用豆包。修改 HTML 后旧预览、评审和导出结论均不能沿用。
- `export_editable_pptx` 不代表交付通过。正式交付前按需要执行 `render_pptx`、`validate_export` 和
  `validate_delivery`；PPTX 必须包含可编辑文字、独立图片和受支持的简单形状，不能以整页截图冒充。
- 主模型与审核模型独立配置。审核报告只提供质量证据和建议，不得直接改写页面；由你决定是否采纳、
  修改并复核。审核调用失败、未完成或无法判断时，不能据此声明页面或导出通过。
- 用户只要求一页或阶段性草稿时可以只完成该范围，并明确未检查/未导出的部分。不要把开发验收顺序
  写成运行时固定 DAG，也不要无故重做未受影响页面。

反馈、恢复与结束：
- 工具返回参数错误、对象不存在、超时或报告无效时，先根据具体字段和原因修正；不要原样重复确定会
  失败的调用。缺少决定性输入时向用户说明所缺内容并暂停，不要空转。
- 用户没有明确表示恢复旧任务时，不要遍历其他会话或把工作区中的历史产物猜作当前对象。同一
  revision 上刚成功取得的只读验证结果也不要无故重复调用。
- 内容需要修复不是工具执行失败。无法继续时保留正确资产和成功批次，登记或报告未解决问题。
- 在最终答复中给出 manifest/report/资产引用、处理范围、当前 revision、状态与限制。结束当前回答
  不等于整个 PPT 任务完成。默认使用中文，结论应有可核查依据。"""

PDF_TOOL_RISK = {
    "parse_pdf": "write",
    "view_pdf_page": "read",
    "review_pdf_assets": "write",
    "crop_pdf_asset": "write",
    "update_asset_mapping": "write",
    "register_pdf_asset_issue": "write",
    "re_recognize_pdf_region": "write",
    "validate_pdf_asset_manifest": "read",
    "prepare_pdf_assets": "write",
}

PRESENTATION_TOOL_RISK = {
    "get_paper_markdown": "read",
    "get_paper_context": "read",
    "get_task_state": "read",
    "get_evidence": "read",
    "get_evidence_bundle": "read",
    "query_assets": "read",
    "get_document_overview": "read",
    "get_asset": "read",
    "get_theme": "read",
    "inspect_image": "write",
    "save_brief": "write",
    "save_theme": "write",
    "save_outline": "write",
    "save_slide_plan": "write",
    "save_asset_mapping": "write",
    "save_slide_binding": "write",
    "render_html_slide": "write",
    "inspect_html_layout": "write",
    "review_slide": "write",
    "export_editable_pptx": "write",
    "render_pptx": "write",
    "validate_export": "write",
    "validate_delivery": "write",
}

# Experimental fixed-input profile, explicitly chosen by the product caller.
# Full remains the default. No automatic capability escalation is implemented.
# Production retains all evidence readers, review, source-page viewing and
# delivery guards, but cannot mutate upstream PDF assets or fixed slide plans.
PRODUCTION_TOOLS = (set(PRESENTATION_TOOL_RISK) - {
    'save_brief', 'save_theme', 'save_outline', 'save_slide_plan', 'save_asset_mapping',
}) | {'view_pdf_page', 'validate_pdf_asset_manifest'}


def build_ppt_agent_harness(
    *,
    workspace: str | Path,
    project_root: str | Path | None = None,
    model: BaseChatModel | str | None = None,
    pdf_asset_config: PdfAssetConfig | None = None,
    presentation_config: PresentationConfig | None = None,
    permission_mode: str = "accept_edits",
    enable_bash: bool = False,
    max_turns: int = 40,
    max_context_tokens: int = 120_000,
    tool_profile: Literal['full','production'] = 'full',
) -> Harness:
    """Build the formal Harness. ``production`` is a fixed-input experiment;
    upstream recovery currently requires the full profile, never a silent grant.
    """

    if tool_profile not in {'full', 'production'}:
        raise ValueError('tool_profile must be full or production')
    root = (
        Path(project_root).expanduser().resolve()
        if project_root is not None
        else Path(__file__).resolve().parents[5]
    )
    run_workspace = Path(workspace).expanduser().resolve()
    run_workspace.mkdir(parents=True, exist_ok=True)
    pdf_config = pdf_asset_config or PdfAssetConfig(
        workspace=run_workspace / "pdf_assets"
    )
    ppt_config = presentation_config or PresentationConfig(
        workspace=run_workspace / "ppt_tasks"
    )
    tool_risk = dict(PDF_TOOL_RISK)
    tool_risk.update(PRESENTATION_TOOL_RISK)
    if model is None:
        from ppt_agent_domain.presentation.planning_config import PlanningConfig
        model = PlanningConfig().create_model('planning')
    extra_tools = [*make_pdf_asset_tools(pdf_config), *make_presentation_tools(ppt_config)]
    if tool_profile == 'production':
        extra_tools = [t for t in extra_tools if t.name in PRODUCTION_TOOLS]
    return Harness(
        HarnessConfig(
            model=model,
            workspace=str(run_workspace),
            system_prompt=PPT_AGENT_SYSTEM_PROMPT + ('\n当前tool_profile=production，使用已有规划和正式资产；上游修改需交还主Agent，不猜测可调用未暴露工具。' if tool_profile == 'production' else ''),
            permission_mode=permission_mode,
            tool_risk=tool_risk,
            skills_dir=str(root / "skills"),
            extra_tools=extra_tools,
            # PPT/PDF write tools update versioned task or manifest indexes.
            # Keep those model-issued calls serial even when one response asks
            # for several tools; internal batch review concurrency is unchanged.
            serial_tools=tuple(
                name
                for name, risk in tool_risk.items()
                if risk == "write" and name != "inspect_image"
            ),
            session_root=str(run_workspace / "sessions"),
            max_turns=max_turns,
            # The PPT product exposes many rich Pydantic tool schemas.  Their
            # static provider-side token cost is much larger than the generic
            # Harness examples, so 60K would compact almost every turn.
            max_context_tokens=max_context_tokens,
            enable_bash=enable_bash,
        )
    )
