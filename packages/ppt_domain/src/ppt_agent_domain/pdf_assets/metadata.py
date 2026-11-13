"""Small, versioned metadata shared by ingestion, review and read-only access."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt


class AssetDescription(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    asset_id: str
    asset_version: Annotated[StrictInt, Field(ge=1)]
    status: Literal["pass", "needs_repair", "uncertain"]
    semantic_description: Annotated[str, Field(min_length=1, max_length=600)]
    structure_description: Annotated[str, Field(min_length=1, max_length=600)]
    visual_type: Annotated[str, Field(min_length=1, max_length=80)]
    layout_hint: Annotated[str, Field(max_length=300)] = ""


def image_geometry(path: str) -> dict:
    if not path or not Path(path).is_file():
        return {}
    import fitz

    pixmap = fitz.Pixmap(path)
    width, height = int(pixmap.width), int(pixmap.height)
    return {"pixel_width": width, "pixel_height": height,
            "aspect_ratio": round(width / height, 6),
            "orientation": "square" if width == height else "landscape" if width > height else "portrait"}


def table_footnotes(asset: dict) -> list[str]:
    """Keep source footnotes visible, separate from captions and table cells."""
    values = []
    sources = [asset, asset.get('source_record') or {}]
    supplement = asset.get('structured_content') or {}
    if supplement.get('status') == 'selected_unverified':
        sources += supplement.get('source_records') or []
    for record in sources:
        notes = record.get('table_footnote') or []
        if isinstance(notes, str):notes = [notes]
        for note in notes:
            if note and str(note) not in values:values.append(str(note))
    return values


def evidence_text(asset: dict) -> str:
    """Prefer explicit corrected text; retain original table/formula/caption evidence."""
    from .hybrid import structured_value
    structured = structured_value(asset) if asset.get('type') in {'table','equation'} else ''
    body = str(asset.get("recognized_text") or structured or asset.get("text") or asset.get("table_body")
               or asset.get("equation") or "")
    captions = asset.get("captions") or []
    if isinstance(captions, str):
        captions = [captions]
    caption = str(asset.get("caption") or "\n".join(str(c) for c in captions))
    notes = table_footnotes(asset)
    return "\n".join(part for part in (body, caption if caption != body else "",
        '表格脚注（原始来源）：\n'+'\n'.join(notes) if notes else '') if part)


def invalidate_description(asset: dict) -> None:
    if asset.get("description_provenance"):
        asset["description_provenance"]["applicability"] = "stale"
    asset["description_status"] = "stale"
