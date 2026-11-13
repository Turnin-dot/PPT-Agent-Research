"""Offline structured supplements. Pipeline identity, text and pixels stay canonical.

This module never submits a PDF to a parser. Cached VLM content_list records are
matched by type, physical page and geometry; captions are not trusted as keys.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from pathlib import Path
import re

from .storage import read_json, sha256_file

POLICY = 'pipeline-primary/vlm-structured-preferred/v1'


def supplement_identity(result_dir: str) -> dict:
    if not result_dir:
        return dict(policy=POLICY, content_sha256=None)
    files = sorted(Path(result_dir).resolve().glob('*_content_list.json'))
    if len(files) != 1:
        raise ValueError('VLM cache must contain exactly one *_content_list.json')
    return dict(policy=POLICY, content_sha256=sha256_file(files[0]))


def _source_identity(source: Path, directory: Path) -> dict:
    origins = sorted(directory.glob('*_origin.pdf'))
    if len(origins) != 1:
        raise ValueError('VLM cache requires one origin PDF for source verification')
    origin = origins[0]
    result = dict(source_sha256=sha256_file(source), origin_sha256=sha256_file(origin),
                  origin_path=str(origin), method='byte_sha256')
    if result['source_sha256'] != result['origin_sha256']:
        # MinerU API can reserialize the upload. Verify EVERY page, retaining
        # both byte hashes and the deliberately limited raster equivalence claim.
        import fitz
        import hashlib
        with fitz.open(source) as left, fitz.open(origin) as right:
            if len(left) != len(right):
                raise ValueError('VLM source page count mismatch')
            pages = []
            for a, b in zip(left, right):
                if tuple(a.rect) != tuple(b.rect):
                    raise ValueError('VLM source page dimensions mismatch')
                pa, pb = a.get_pixmap(alpha=False), b.get_pixmap(alpha=False)
                if pa.samples != pb.samples:
                    raise ValueError('VLM source raster mismatch; no supplement applied')
                pages.append(hashlib.sha256(pa.samples).hexdigest())
        result.update(method='all_pages_72dpi_raster_equal', page_pixel_sha256=pages,
                      limitation='Raster equivalence is not upload-byte identity or OCR correctness.')
    return result


def _box(record):
    value = record.get('bbox')
    if not isinstance(value, list) or len(value) != 4:
        return None
    x0, y0, x1, y1 = map(float, value)
    if not (0 <= x0 < x1 <= 1000 and 0 <= y0 < y1 <= 1000):
        return None
    return x0, y0, x1, y1


def _overlap(a, b):
    intersection = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
    aa, bb = (a[2]-a[0])*(a[3]-a[1]), (b[2]-b[0])*(b[3]-b[1])
    return intersection / min(aa, bb), intersection / (aa+bb-intersection)


def structured_value(asset: dict) -> str:
    supplement = asset.get('structured_content') or {}
    if supplement.get('status') == 'selected_unverified':
        return str(supplement.get('value') or '')
    return str((asset.get('table_body') if asset.get('type') == 'table' else asset.get('text') or asset.get('equation')) or '')


def merge_structured(manifest: dict, result_dir: str = '') -> dict:
    """Return a new Manifest; no file writes, no replacement of Pipeline fields."""
    result = deepcopy(manifest)
    identity = supplement_identity(result_dir)
    report = dict(**identity, primary_backend='pipeline', supplement_scope=['equation', 'table'],
                  matching='type + page + normalized original bbox; exclusive candidates', decisions=[])
    candidates = []; raw = []
    if result_dir:
        directory = Path(result_dir).resolve()
        files = list(directory.glob('*_content_list.json'))
        raw = read_json(files[0])
        if not isinstance(raw, list):
            raise ValueError('VLM structured cache must be a content_list array')
        report.update(content_list_path=str(files[0]), source_verification=_source_identity(Path(manifest['source']['pdf_path']), directory))
        candidates = [(i, r, _box(r)) for i, r in enumerate(raw) if r.get('type') in {'equation', 'table'} and _box(r)]
    targets = [a for a in result['assets'] if a['type'] in {'equation', 'table'}]
    owners = {}
    for index, record, box in candidates:
        matches = []
        for target in targets:
            # Recropped assets can have PDF-points geometry. Original parser
            # geometry remains in source_record and is the correct matching key.
            original = target.get('source_record') or target
            bounds = _box(original)
            if not bounds or record.get('page_idx') != target['source_page']-1 or record['type'] != target['type']:
                continue
            overlap, iou = _overlap(bounds, box)
            if overlap >= .72 and (target['type'] == 'equation' or iou >= .60):
                matches.append(target['asset_id'])
        owners[index] = matches
    for asset in targets:
        aid = asset['asset_id']
        selected = [(i, r, box) for i, r, box in candidates if owners[i] == [aid]]
        ambiguous = any(aid in matches and len(matches) != 1 for matches in owners.values())
        reason = 'vlm_unavailable' if not result_dir else 'no_unique_geometry_match'
        value = ''
        if selected and not ambiguous:
            selected.sort(key=lambda x: (x[2][1], x[2][0]))
            if asset['type'] == 'table' and len(selected) == 1:
                value = str(selected[0][1].get('table_body') or '')
                if not value.strip().startswith('<table') or '</table>' not in value:
                    value = ''; reason = 'invalid_table_representation'
            elif asset['type'] == 'equation':
                box = _box(asset.get('source_record') or asset)
                height = max(x[2][3] for x in selected)-min(x[2][1] for x in selected)
                if height/(box[3]-box[1]) < .78:
                    reason = 'partial_formula_coverage'
                else:
                    value = '\n'.join(str(r.get('text') or '') for _, r, _ in selected)
                    if not value.strip():reason = 'empty_formula'
            else:
                reason = 'multiple_table_candidates'
        if ambiguous:
            value = ''; reason = 'ambiguous_geometry'
        state = 'selected_unverified' if value else 'pipeline_fallback'
        numbers = re.findall(r'\\tag\s*\{\s*(\d+)\s*\}', value)
        if asset['type']=='equation' and not numbers and selected:
            bounds=_box(asset.get('source_record') or asset)
            for record in raw:
                box=_box(record);match=re.fullmatch(r'\s*\((\d+)\)\s*', record.get('text',''))
                if match and box and record.get('page_idx')==asset['source_page']-1 and bounds[1]<=box[1]<=bounds[3] and 0<=box[0]-bounds[2]<180:
                    numbers.append(match.group(1))
        asset['structured_content'] = dict(status=state, backend='vlm' if value else 'pipeline',
            value=value, reason='' if value else reason, source_indices=[i for i, _, _ in selected],
            source_records=[deepcopy(r) for _, r, _ in selected],
            content_list_path=report.get('content_list_path'), content_sha256=identity['content_sha256'],
            equation_numbers=numbers, verified=False,
            note='Geometry correspondence only. OCR/math/cell semantics are unverified; original Pipeline fields remain available.')
        report['decisions'].append(dict(asset_id=aid, status=state, reason='' if value else reason,
                                       source_indices=[i for i, _, _ in selected], equation_numbers=numbers))
    report['counts'] = dict(Counter(x['status'] for x in report['decisions']))
    result['structured_supplement'] = report
    return result
