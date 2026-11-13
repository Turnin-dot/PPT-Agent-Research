from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from agent_harness.core.models import BaseChatModel, init_chat_model
from ..pdf_assets.config import PDF_REVIEW_MODEL_SPEC

DOUBAO_REVIEW_MODEL_SPEC = "doubao:doubao-seed-2-1-turbo-260628"
DOUBAO_IMAGE_MODEL_SPEC = "doubao-image:doubao-seedream-5-0-pro-260628"
ASSET_INSPECTION_MODEL_SPEC = PDF_REVIEW_MODEL_SPEC


def default_model_factory() -> BaseChatModel:
    """Return an unbound Doubao instance for HTML/PPT visual review."""

    spec = (
        os.environ.get("PPT_AGENT_PAGE_REVIEW_MODEL", "").strip()
        or os.environ.get("PPT_AGENT_REVIEW_MODEL", "").strip()
        or DOUBAO_REVIEW_MODEL_SPEC
    )
    timeout = float(
        os.environ.get(
            "PPT_AGENT_PAGE_REVIEW_MODEL_TIMEOUT",
            os.environ.get("PPT_AGENT_REVIEW_MODEL_TIMEOUT", "300"),
        )
    )
    max_retries = int(
        os.environ.get(
            "PPT_AGENT_PAGE_REVIEW_MODEL_MAX_RETRIES",
            os.environ.get("PPT_AGENT_REVIEW_MODEL_MAX_RETRIES", "2"),
        )
    )
    return init_chat_model(
        spec,
        timeout=timeout,
        max_retries=max_retries,
        max_completion_tokens=4096,
        extra_body={"thinking": {"type": "disabled"}},
    )


def asset_inspection_model_spec() -> str:
    """Source-asset vision uses the approved PDF evidence role; reject stale overrides."""
    spec = os.environ.get("PPT_AGENT_ASSET_INSPECTION_MODEL", "").strip() or ASSET_INSPECTION_MODEL_SPEC
    if spec != ASSET_INSPECTION_MODEL_SPEC:
        # Do not echo an invalid environment value: it may contain pasted credentials.
        raise ValueError(
            "Source asset inspection must use deepseek:deepseek-flash. "
            "Update PPT_AGENT_ASSET_INSPECTION_MODEL in the environment/.env; "
            "unapproved model overrides are not used."
        )
    return spec


def default_asset_inspection_model_factory() -> BaseChatModel:
    """Use DeepSeek Flash for original figures and scoped table-cell verification."""
    spec = asset_inspection_model_spec()
    timeout = float(os.environ.get("PPT_AGENT_ASSET_INSPECTION_MODEL_TIMEOUT", "300"))
    max_retries = int(os.environ.get("PPT_AGENT_ASSET_INSPECTION_MODEL_MAX_RETRIES", "2"))
    return init_chat_model(
        spec, timeout=timeout, max_retries=max_retries,
        reasoning_effort=os.environ.get("PPT_AGENT_PDF_REVIEW_REASONING_EFFORT", "low"),
        max_tokens=int(os.environ.get("PPT_AGENT_PDF_REVIEW_MAX_COMPLETION_TOKENS", "8192")),
        extra_body={"thinking": {"type": "enabled"}},
    )


def default_content_review_model_factory() -> BaseChatModel:
    """Reuse the existing Qwen evidence-review role for slide fidelity."""
    from .planning_config import PlanningConfig
    config = PlanningConfig()
    return init_chat_model(config.spec('review'), **config.parameters('review'),
                           response_format={"type": "json_object"})


def _first_existing(*values: str | Path | None) -> Path | None:
    for value in values:
        if value and Path(value).is_file():
            return Path(value).resolve()
    return None


def _default_node() -> Path:
    configured = os.environ.get("PPT_AGENT_NODE")
    found = _first_existing(
        configured,
        shutil.which("node"),
    )
    return found or Path("node")


def _default_node_modules() -> Path | None:
    configured = os.environ.get("PPT_AGENT_NODE_MODULES")
    candidates = [
        Path(configured) if configured else None,
        *(parent / "node_modules" for parent in Path(__file__).resolve().parents),
    ]
    return next((item.resolve() for item in candidates if item and item.is_dir()), None)


def _default_chromium() -> Path | None:
    return _first_existing(
        os.environ.get("PPT_AGENT_CHROMIUM"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        shutil.which("chrome"),
        shutil.which("msedge"),
        shutil.which("chromium"),
    )


@dataclass
class PresentationConfig:
    workspace: Path
    # Only HTML/PPT page review and export visual comparison use this factory.
    model_factory: Callable[[], BaseChatModel] = default_model_factory
    content_review_model_factory: Callable[[], BaseChatModel] = default_content_review_model_factory
    # Source-image/table inspection shares the approved DeepSeek evidence role.
    asset_inspection_model_factory: Callable[
        [], BaseChatModel
    ] = default_asset_inspection_model_factory
    node_executable: Path = field(default_factory=_default_node)
    node_modules: Path | None = field(default_factory=_default_node_modules)
    chromium_executable: Path | None = field(default_factory=_default_chromium)
    render_width: int = 1600
    render_height: int = 900
    browser_timeout_seconds: int = 90
    export_timeout_seconds: int = 180
    powerpoint_timeout_seconds: int = 180
    max_evidence_chars: int = 24_000
    # Image generation is registered separately from chat review.  The first
    # release records the configured capability but does not make it a
    # mandatory production step or expose an unverified generation tool.
    image_model_spec: str = field(
        default_factory=lambda: os.environ.get("PPT_AGENT_IMAGE_MODEL", "").strip()
        or DOUBAO_IMAGE_MODEL_SPEC
    )
    export_visual_review_enabled: bool = True
    export_visual_review_batch_size: int = 3
    # Append to preserve existing positional construction. Explicit A/B baseline
    # never changes the default or delivery protection.
    review_contract: Literal['classified-v1', 'legacy-v1'] = 'classified-v1'
