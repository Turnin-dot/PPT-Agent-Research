from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from agent_harness.core.models import BaseChatModel, init_chat_model

PDF_REVIEW_MODEL_SPEC = "deepseek:deepseek-flash"


@dataclass(frozen=True)
class MinerUConfig:
    """The locally installed MinerU 2.6.4 pipeline described by the project docs."""

    executable: Path = field(default_factory=lambda: Path(os.environ.get("PPT_AGENT_MINERU") or shutil.which("mineru") or "mineru"))
    modelscope_cache: Path = field(default_factory=lambda: Path(os.environ.get("MODELSCOPE_CACHE", str(Path.home() / ".cache/modelscope"))))
    hf_home: Path = field(default_factory=lambda: Path(os.environ.get("HF_HOME", str(Path.home() / ".cache/huggingface"))))
    hf_hub_cache: Path = field(default_factory=lambda: Path(os.environ.get("HF_HUB_CACHE", str(Path.home() / ".cache/huggingface/hub"))))
    device: str = field(default_factory=lambda: os.environ.get("PPT_AGENT_MINERU_DEVICE", "cpu"))
    language: str = "en"
    timeout_seconds: int = 900

    def environment(self) -> dict[str, str]:
        env = dict(os.environ)
        env.update(
            {
                "MODELSCOPE_CACHE": str(self.modelscope_cache),
                "HF_HOME": str(self.hf_home),
                "HF_HUB_CACHE": str(self.hf_hub_cache),
            }
        )
        return env


def default_model_factory() -> BaseChatModel:
    """Create the configured DeepSeek Flash reviewer for PDF evidence operations.

    A new instance is intentional: ``bind_tools`` mutates Harness model instances.
    """

    spec = (
        os.environ.get("PPT_AGENT_PDF_REVIEW_MODEL", "").strip()
        or PDF_REVIEW_MODEL_SPEC
    )
    if spec != PDF_REVIEW_MODEL_SPEC:
        raise ValueError(
            "PDF asset review must use "
            f"{PDF_REVIEW_MODEL_SPEC!r}; got {spec!r}"
        )
    timeout = float(os.environ.get("PPT_AGENT_PDF_REVIEW_MODEL_TIMEOUT", "300"))
    # The review engine owns bounded retries; avoid multiplying them in the SDK.
    max_retries = int(os.environ.get("PPT_AGENT_PDF_REVIEW_MODEL_MAX_RETRIES", "0"))
    return init_chat_model(
        spec,
        timeout=timeout,
        max_retries=max_retries,
        reasoning_effort=os.environ.get("PPT_AGENT_PDF_REVIEW_REASONING_EFFORT", "low"),
        max_tokens=int(os.environ.get("PPT_AGENT_PDF_REVIEW_MAX_COMPLETION_TOKENS", "8192")),
        extra_body={"thinking": {"type": "enabled"}},
    )


@dataclass
class PdfAssetConfig:
    workspace: Path
    # Optional OFFLINE cache only. Never launches a full VLM parse or API job.
    vlm_result_dir: str = ''
    mineru: MinerUConfig = field(default_factory=MinerUConfig)
    model_factory: Callable[[], BaseChatModel] = default_model_factory
    render_dpi: int = 144
    # ``max_assets_per_review`` is retained for compatibility with the first
    # prototype.  The batched reviewer does not use it as a coverage limit.
    max_assets_per_review: int = 8
    # The service does not assume that the model actually exposes 128K tokens;
    # this is a configurable planning reference.  Output and safety reserves
    # are removed before page batches are planned.
    review_input_limit_tokens: int = 128_000
    review_output_reserve_tokens: int = 8_192
    review_safety_margin_tokens: int = 8_192
    # Operational soft limit for the complete locally estimated request.  It is
    # distinct from the provider/context reference above, so output and safety
    # reserves are not subtracted from this value a second time.
    review_batch_estimated_token_budget: int = 35_000
    # Keep requests predictable even when several visually light pages would
    # fit under the token budget.  Split units from one oversized page may still
    # share a batch because they count as one source page.
    review_max_pages_per_batch: int = 2
    review_text_chars_per_token: float = 2.0
    review_image_token_safety_factor: float = 1.35
    review_max_image_dimension: int = 2200
    review_adjacent_context_pages: int = 1
    review_max_retries: int = 2
    review_concurrency: int = field(default_factory=lambda: int(os.environ.get("PPT_AGENT_PDF_REVIEW_CONCURRENCY", "3")))
    review_retry_delay_seconds: float = 0.25
    max_repair_attempts: int = 2
    prepare_timeout_seconds: int = 1200
