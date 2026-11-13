"""Read-only PDF -> presentation projection. Original evidence stays authoritative."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..pdf_assets.metadata import evidence_text, image_geometry, table_footnotes
from ..pdf_assets.hybrid import structured_value
from ..pdf_assets.storage import load_manifest
from ..pdf_assets.reliability import quality_summary
from ..pdf_assets.provenance import source_mapping


def ordered_assets(manifest: dict) -> list[dict]:
    """Use stored page/reading order, keeping manifest order as a stable fallback."""
    indexed = enumerate(manifest.get('assets', []))
    return [asset for _, asset in sorted(indexed, key=lambda item: (
        int(item[1].get('source_page', 0)),
        item[1]['reading_order'] if isinstance(item[1].get('reading_order'), (int, float)) else item[0],
        item[0],
    ))]


def asset_view(asset: dict, manifest: dict, manifest_path: str, *, geometry: bool = False) -> dict:
    version = int(asset.get('version', 1))
    captions = asset.get('captions') or ([asset['caption']] if asset.get('caption') else [])
    if isinstance(captions, str):
        captions = [captions]
    provenance = dict(asset.get('description_provenance') or {})
    description_status = asset.get('description_status', 'not_reviewed')
    if provenance.get('asset_version', version) != version or provenance.get('applicability') == 'stale':
        description_status = 'stale'
    if provenance.get('source_sha256') and provenance['source_sha256'] != manifest.get('source', {}).get('sha256'):
        description_status = 'stale'
    if description_status == 'current' and provenance.get('asset_version') != version:
        description_status = 'unverified'
    reports = []
    for report in manifest.get('reviews', []):
        scope = report.get('scope') or {}
        if scope.get('asset_ids') and asset['asset_id'] not in scope['asset_ids']:
            continue
        if scope.get('pages') and asset.get('source_page') not in scope['pages']:
            continue
        current = (report.get('applicability') == 'current'
                   and report.get('manifest_revision') == manifest.get('revision'))
        reports.append({k: report.get(k) for k in ('report_id','report_path','manifest_revision','review_verdict')} |
                       {'applicability': 'current' if current else 'stale',
                        'is_verified': bool(current and report.get('is_verified') and report.get('review_verdict') == 'pass')})
    current_reports = [r for r in reports if r['applicability'] == 'current']
    verified = any(r['is_verified'] for r in current_reports)
    status = asset.get('review_status', 'not_reviewed')
    review = {'asset_status': status, 'applicability': 'current' if current_reports else 'stale' if reports else 'unknown',
              'is_verified': bool(verified and status == 'pass'), 'report_refs': reports}
    path = str(asset.get('path') or '')
    number = str(asset.get('figure_number') or '')
    if not number:
        match = re.search(r'\b(?:Fig(?:ure)?\.?|Table)\s*[A-Za-z0-9IVX]+', ' '.join(captions), re.I)
        number = match.group(0) if match else ''
    result = {k: asset.get(k) for k in ('asset_id','type','source_page','bbox','bbox_coordinate_space',
               'pixel_width','pixel_height','aspect_ratio','orientation','visual_type','layout_hint','reading_order')}
    primary=evidence_text(dict(asset,caption='',captions=captions))
    table_body=structured_value(asset) if asset.get('type')=='table' else ''
    if table_body and table_body not in primary:
        primary+='\n原始表格提取内容：\n'+table_body
    result.update(version=version, path=path, file_exists=bool(path and Path(path).is_file()),
                  captions=captions, figure_number=number, text=primary,
                  table_body=table_body, table_footnotes=table_footnotes(asset),
                  semantic_description=str(asset.get('semantic_description') or '') if description_status == 'current' else '',
                  structure_description=str(asset.get('structure_description') or '') if description_status == 'current' else '',
                  description_status=description_status, description_provenance=provenance,
                  stale_description_available=bool(description_status != 'current' and
                      (asset.get('semantic_description') or asset.get('structure_description'))),
                  review_status=status, review=review, is_verified=review['is_verified'],
                  source_ref={'object_id':asset['asset_id'],'version':version,'manifest_path':str(manifest_path)},
                  source_pdf_path=manifest.get('source',{}).get('pdf_path'),
                  source_sha256=manifest.get('source',{}).get('sha256'))
    supplement = asset.get('structured_content') or {}
    result['structured_source'] = {k:v for k,v in supplement.items() if k not in {'value','source_records'}}
    result['equation_numbers'] = supplement.get('equation_numbers', [])
    result['associations'] = {k:asset.get(k, (asset.get('source_record') or {}).get(k))
        for k in ('parent_id','group_id','subfigures','children') if k in asset or k in (asset.get('source_record') or {})}
    mappings, _ = source_mapping(manifest)
    location = mappings.get(asset['asset_id'])
    result['source_pages'] = location['source_pages'] if location else [asset['source_page']]
    result['source_provenance'] = ({k:v for k,v in location.items() if k!='source_spans'} if location else
        dict(stored_page=asset['source_page'],source_pages=result['source_pages'],mapping_status='stored_page_only'))
    result['reliability'] = quality_summary(asset,manifest,manifest_path,visual_verified=review['is_verified'])
    result['is_verified_scope'] = 'visual_crop_only'
    if geometry and result['file_exists'] and asset.get('type') in {'image','table'} and not result.get('pixel_width'):
        try:
            result.update(image_geometry(path))
        except (ValueError, RuntimeError):
            pass
    return result


def search_text(asset: dict, view: dict) -> str:
    return '\n'.join(str(x or '') for x in (view['text'],view['table_body'],
        asset.get('semantic_description'),asset.get('structure_description'),view['figure_number']))


def context_text(view: dict) -> str:
    """Labels keep auxiliary descriptions distinct from original evidence."""
    return '\n'.join(filter(None, [view['text'],
        '辅助语义（非原始证据）：'+view['semantic_description'] if view['semantic_description'] else '',
        '辅助结构：'+view['structure_description'] if view['structure_description'] else '',
        f"核对：{view['review']['asset_status']} / {view['review']['applicability']}；描述：{view['description_status']}"]))


def reference_health(task: dict) -> dict:
    """Read existing plans/bindings, no global graph and no state writes."""
    import json
    cache: dict[str, Any] = {}
    issues = []
    sources = [(sid,ref,'plan') for sid,ref in task.get('slide_plans',{}).items()]
    sources += [(sid,s['binding'],'binding') for sid,s in task.get('slides',{}).items() if s.get('binding')]
    seen = set()
    for sid, obj, kind in sources:
        try:
            record = json.loads(Path(obj['path']).read_text(encoding='utf-8'))
            parts = [record.get('plan',{})] if kind == 'plan' else record.get('elements',[])
            for part in parts:
                for ref in part.get('asset_refs',[]) + part.get('evidence_refs',[]):
                    path=ref.get('manifest_path')
                    if not path: continue
                    key=(sid,path,ref['object_id'],ref['version'])
                    if key in seen: continue
                    seen.add(key)
                    if path not in cache:
                        cache[path]=load_manifest(path)[1]
                    current=next((a for a in cache[path]['assets'] if a['asset_id']==ref['object_id']),None)
                    if current is None or int(current.get('version',1)) != ref['version']:
                        issues.append(dict(slide_id=sid,object_id=ref['object_id'],manifest_path=path,
                            expected_version=ref['version'],current_version=current.get('version',1) if current else None,
                            reason='asset_version_changed' if current else 'asset_missing'))
        except (OSError,ValueError,KeyError) as exc:
            issues.append(dict(slide_id=sid,reason='reference_unreadable',detail=str(exc)))
    return dict(status='stale' if issues else 'current',issues=issues,
                affected_slide_ids=sorted({i['slide_id'] for i in issues}))
