"""Bounded full-text Markdown access, with explicit provenance and coverage."""
from pathlib import Path
import hashlib
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from ..pdf_assets.storage import load_manifest, read_json, sha256_file


class MarkdownInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    manifest_path: str
    offset: int = Field(default=0, ge=0)
    max_chars: int = Field(default=24000, ge=500, le=200000)
    pdf_pages: list[int] | None = None


class MarkdownResult(BaseModel):
    execution_status: str = 'succeeded'
    read_only: bool = True
    available: bool
    manifest_path: str
    path: str
    sha256: str
    text: str
    offset: int
    total_chars: int
    next_offset: int | None
    pages: list[dict[str, Any]] | None = None
    unresolved_records: list[dict[str, Any]] | None = None
    policy: str = 'Auxiliary parser Markdown, not independent ground truth; structured Manifest is authoritative for object identity. Conflicts require PDF evidence.'


def read_markdown(manifest_path: str, *, offset: int = 0, max_chars: int = 24000,
                  pdf_pages: list[int] | None = None) -> dict:
    resolved, manifest = load_manifest(manifest_path)
    if pdf_pages is not None:
        if not pdf_pages or len(pdf_pages)>4 or any(type(p) is not int or p<1 for p in pdf_pages):
            raise ValueError('pdf_pages must contain 1 to 4 positive physical PDF page numbers')
        if len(set(pdf_pages))!=len(pdf_pages) or sorted(pdf_pages)!=list(range(min(pdf_pages),max(pdf_pages)+1)):
            raise ValueError('pdf_pages must be distinct consecutive physical PDF pages')
        index_path=Path((manifest.get('reading_material') or {}).get('page_index_path') or '')
        if not index_path.is_file(): raise FileNotFoundError('Page Markdown index unavailable for this Manifest')
        index=read_json(index_path)
        by_page={p['pdf_page']:p for p in index['pages']}
        missing=[p for p in pdf_pages if p not in by_page]
        if missing: raise ValueError(f'PDF physical page does not exist: {missing}')
        selected=[];unresolved_ids=set()
        for p in pdf_pages:
            entry=by_page[p];path=Path(entry['path'])
            if sha256_file(path)!=entry['sha256']: raise ValueError(f'Page Markdown changed: {path}')
            selected.append(dict(pdf_page=p,text=path.read_text(encoding='utf-8'),path=str(path),
                source_record_indices=entry['source_record_indices'],asset_ids=entry['asset_ids'],
                content_counts=entry['content_counts'],alignment_status=entry['alignment_status'],
                unresolved_asset_ids=entry['unresolved_asset_ids']))
            unresolved_ids.update(entry['unresolved_asset_ids'])
        unresolved=[r for r in index['unresolved_records'] if r.get('asset_id') in unresolved_ids]
        return MarkdownResult(available=True,manifest_path=str(resolved),path=str(index_path),
            sha256=sha256_file(index_path),text='',offset=0,total_chars=0,next_offset=None,
            pages=selected,unresolved_records=unresolved,
            policy='Rebuilt from source content_list page_idx; cross-page merged records are listed separately, not forced into a page. Original full Markdown remains independent.').model_dump(mode='json')
    value = (manifest.get('reading_material') or {}).get('markdown_path') or manifest.get('mineru', {}).get('markdown_path')
    path = Path(value) if value else None
    raw = path.read_bytes() if path and path.is_file() else b''
    text = raw.decode('utf-8-sig')
    if offset < 0 or offset > len(text) or max_chars < 1:
        raise ValueError('Invalid Markdown character range')
    end = min(offset+max_chars, len(text))
    return MarkdownResult(available=bool(raw), manifest_path=str(resolved), path=str(path) if path else '',
        sha256=hashlib.sha256(raw).hexdigest() if raw else '', text=text[offset:end], offset=offset,
        total_chars=len(text), next_offset=end if end < len(text) else None).model_dump(mode='json')


def reading_packet(manifest_path: str) -> dict:
    """Deliver Markdown ONCE per independent phase and a compact JSON index.

    JSON bodies remain available through the native evidence tools; they are
    deliberately not duplicated beside the entire continuous Markdown.
    """
    from .assets import asset_view, ordered_assets
    path, manifest = load_manifest(manifest_path)
    markdown = read_markdown(str(path), max_chars=2**31-1)
    if not markdown['available']:
        # Legacy assets remain usable; explicitly fall back to the established
        # losslessly segmented JSON package, never silently pretend MD was read.
        from .paper_context import build_paper_context, select_segment
        package = build_paper_context(str(path))
        return dict(markdown=markdown, paper_context=select_segment(package, 0),
                    pending_segments=list(range(1, len(package['segments']))), mode='legacy_json_fallback')
    index = []
    for asset in ordered_assets(manifest):
        view = asset_view(asset, manifest, str(path))
        keys = ('asset_id','version','type','source_page','source_pages','bbox','bbox_coordinate_space',
                'captions','figure_number','path','table_footnotes','equation_numbers','associations','structured_source')
        row = {k:view[k] for k in keys if view.get(k) not in (None, '', [], {})}
        if asset.get('type')=='image':
            width,height=asset.get('pixel_width'),asset.get('pixel_height')
            if type(width) is int and type(height) is int and width>0 and height>0:
                row.update(pixel_width=width,pixel_height=height,aspect_ratio=round(width/height,4))
        # The source pointer/hash/decision suffices here; bulk alternate OCR is
        # fetched on demand and never repeated alongside the same source text.
        if row.get('structured_source'):
            row['structured_source']={k:v for k,v in row['structured_source'].items()
                if k in ('status','backend','reason','source_indices','verified')}
        index.append(row)
    return dict(mode='markdown_once_with_json_index', markdown=markdown,
        manifest_path=str(path), manifest_revision=manifest['revision'], source=manifest['source'],
        source_notes=manifest.get('source_ambiguities', []), asset_index=index,
        pending_segments=[], full_markdown_delivered=True,
        structured_evidence_policy='Query get_evidence_bundle/get_asset for VLM-preferred formula/table representations. Markdown may retain Pipeline OCR. Read the actual source evidence before accepting a conflict.')
