"""Scoped content evidence, separate from legacy crop acceptance.

Raw MinerU output and Manifest are never rewritten. Sidecar records are bound to
source, asset version, evidence bytes and descriptions, not a global task stage.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from .storage import load_manifest, read_json, write_json, sha256_file

State = Literal['verified', 'unverified', 'conflict', 'uncertain', 'stale']


class QualityStates(BaseModel):
    model_config = ConfigDict(extra='forbid',strict=True)
    visual: State
    text: State
    structure: State
    semantic: State


class EvidenceQuality(BaseModel):
    model_config = ConfigDict(extra='forbid',strict=True)
    states: QualityStates
    state_basis: Literal['raw_extraction']
    legacy_is_verified_scope: Literal['visual_crop_only']
    verified_scope: Literal['specified_cells_only','none']
    preferred_evidence: Literal['current_scoped_visual_values','raw_unverified_material']
    report_refs: list[dict]
    has_current_corrections: bool
    needs_visual_check: bool


class CellTarget(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    row: int = Field(ge=1, description='1-based data row, excluding table_header_rows.')
    column: int = Field(ge=1, description='1-based logical column after expanding rowspan/colspan.')


class VisibleCell(CellTarget):
    visual_value: str | None = Field(description='Visible cell text/symbol, empty string for a clearly empty cell; null if unreadable.')
    readability: Literal['clear', 'uncertain']
    note: str = Field(default='', max_length=300)


class CellResponse(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    cells: list[VisibleCell]


class CellFinding(CellTarget):
    original_value: str
    visual_value: str | None
    state: Literal['verified', 'conflict', 'uncertain']
    note: str
    visual_state: Literal['verified','uncertain'] | None = None
    comparison_state: Literal['consistent','conflict','uncertain'] | None = None

    @model_validator(mode='after')
    def separate_observation_and_comparison(self):
        visual='uncertain' if self.state=='uncertain' or self.visual_value is None else 'verified'
        comparison='consistent' if self.state=='verified' else self.state
        if self.visual_state not in (None,visual) or self.comparison_state not in (None,comparison):
            raise ValueError('Observation quality and raw-extraction comparison must remain distinct and consistent')
        self.visual_state=visual;self.comparison_state=comparison
        return self


class TableVerification(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    schema_version: Literal['table-cell-evidence/v1'] = 'table-cell-evidence/v1'
    report_id: str
    asset_id: str
    asset_version: StrictInt
    source_sha256: str
    input_fingerprint: str
    image_sha256: str
    image_path: str
    header_rows: StrictInt
    cells: list[CellFinding]
    model: str
    created_at: str
    scope: Literal['specified_cells_only'] = 'specified_cells_only'


def fingerprint(asset: dict, manifest: dict) -> str:
    path = Path(asset.get('path') or '__missing__')
    record = {k: asset.get(k) for k in ('asset_id', 'version', 'type', 'text', 'recognized_text',
        'table_body', 'captions', 'caption', 'semantic_description', 'structure_description')}
    if asset.get('structured_content'):record['structured_content']=asset['structured_content']
    record.update(source_sha256=manifest.get('source', {}).get('sha256'),
                  image_sha256=sha256_file(path) if path.is_file() else None)
    return hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def sidecar_dir(manifest_path: str | Path) -> Path:
    p = Path(manifest_path).resolve()
    return p.with_name(p.name + '.evidence')


def records_for(manifest_path, asset, manifest):
    index = sidecar_dir(manifest_path) / 'index.json'
    if not index.is_file():
        return []
    result = []
    for entry in read_json(index).get('records', []):
        if entry['asset_id'] != asset['asset_id']:
            continue
        current = (entry['asset_version'] == asset.get('version', 1)
                   and entry['input_fingerprint'] == fingerprint(asset, manifest))
        result.append(dict(entry, applicability='current' if current else 'stale'))
    return result


def quality_summary(asset, manifest, manifest_path, *, visual_verified=False):
    states = dict(visual='verified' if visual_verified and asset.get('type') in {'image','table'} else 'unverified',
                  text='unverified', structure='unverified', semantic='unverified')
    if visual_verified and not Path(asset.get('path') or '__missing__').is_file():
        states['visual']='uncertain'
    refs = records_for(manifest_path, asset, manifest)
    active = [r for r in refs if r['applicability'] == 'current']
    # Cell verification never certifies an entire table or its interpretation.
    if any(r['conflict_count'] for r in active):
        states.update(text='conflict', structure='conflict')
    elif any(r['uncertain_count'] for r in active):
        states.update(text='uncertain', structure='uncertain')
    elif refs and not active:
        states.update(text='stale', structure='stale')
    return EvidenceQuality(states=states, state_basis='raw_extraction',legacy_is_verified_scope='visual_crop_only',
                verified_scope='specified_cells_only' if active else 'none',
                preferred_evidence='current_scoped_visual_values' if any(r['uncertain_count']==0 for r in active) else 'raw_unverified_material',
                report_refs=refs, has_current_corrections=any(r['conflict_count'] for r in active),
                needs_visual_check=asset.get('type') == 'table' and states['structure'] != 'verified').model_dump(mode='json')


def verification_details(manifest_path, asset, manifest):
    details = []
    for ref in records_for(manifest_path, asset, manifest):
        report = TableVerification.model_validate(read_json(Path(ref['report_path']))).model_dump(mode='json')
        details.append(dict(report, applicability=ref['applicability']))
    return details


def save_verification(manifest_path, report):
    """Commit only a report whose inspected evidence still matches the asset."""
    with _COMMIT_LOCK:
        _, manifest = load_manifest(manifest_path)
        asset = next(a for a in manifest['assets'] if a['asset_id'] == report.asset_id)
        if fingerprint(asset, manifest) != report.input_fingerprint:
            raise ValueError('Asset evidence changed during inspection; report cannot certify the new version')
        directory = sidecar_dir(manifest_path)
        target = directory / (report.report_id + '.json')
        index_path = directory / 'index.json'
        index = read_json(index_path) if index_path.is_file() else dict(schema_version='evidence-index/v1', records=[])
        value = report.model_dump(mode='json')
        write_json(target, value)
        states = [c.state for c in report.cells]
        index['records'].append(dict(report_id=report.report_id, report_path=str(target), asset_id=report.asset_id,
            asset_version=report.asset_version, input_fingerprint=report.input_fingerprint,
            conflict_count=states.count('conflict'), uncertain_count=states.count('uncertain'),
            checked_cell_count=len(states), created_at=report.created_at))
        write_json(index_path, index)
        return str(target)


import threading
_COMMIT_LOCK = threading.RLock()


def logical_table(html):
    """Expand ordinary HTML table spans; do not guess the number of header rows."""
    from html.parser import HTMLParser
    class Parser(HTMLParser):
        def __init__(self):
            super().__init__(); self.rows=[]; self.row=None; self.cell=None
        def handle_starttag(self, tag, attrs):
            if tag=='tr': self.row=[]
            if tag in {'td','th'}:
                a=dict(attrs); self.cell=dict(text=[], rowspan=int(a.get('rowspan',1)), colspan=int(a.get('colspan',1)))
        def handle_data(self, data):
            if self.cell is not None: self.cell['text'].append(data)
        def handle_endtag(self, tag):
            if tag in {'td','th'} and self.cell is not None:
                self.row.append(self.cell); self.cell=None
            if tag=='tr' and self.row is not None: self.rows.append(self.row); self.row=None
    p=Parser(); p.feed(html); grid={}
    for y,row in enumerate(p.rows):
        x=0
        for cell in row:
            while (y,x) in grid:x+=1
            h,w=cell['rowspan'],cell['colspan']
            if not 1<=h<=1000 or not 1<=w<=1000: raise ValueError('Invalid or excessive HTML table span')
            if h*w>10000: raise ValueError('Excessive HTML merged cell')
            for dy in range(h):
                for dx in range(w): grid[y+dy,x+dx]=''.join(cell['text']).strip()
            x+=w
    return grid


def cell_equivalent(a, b):
    # Empty means visibly empty, never an assumed false configuration.
    marks={'✓','✔','√',r'\checkmark'}
    return a.strip()==b.strip() or a.strip() in marks and b.strip() in marks
