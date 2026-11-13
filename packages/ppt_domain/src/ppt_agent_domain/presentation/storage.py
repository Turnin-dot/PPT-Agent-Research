from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TASK_SCHEMA = "ppt-task-prototype/v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_id(value: str, *, kind: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise ValueError(f"invalid {kind}: use 1-128 letters, numbers, dot, underscore or hyphen")
    return value


def task_path(root: Path, task_id: str) -> Path:
    return root / safe_id(task_id, kind="task_id") / "task.json"


def new_task(task_id: str) -> dict[str, Any]:
    now = utc_now()
    return {
        "schema_version": TASK_SCHEMA,
        "task_id": task_id,
        "revision": 0,
        "created_at": now,
        "updated_at": now,
        "brief": None,
        "theme": None,
        "outline": None,
        "slide_plans": {},
        "asset_mappings": {},
        "slides": {},
        "exports": [],
        "delivery": {
            "completion_state": "in_progress",
            "turn_state": "active",
            "latest_validation": None,
        },
        "issues": [],
        "change_log": [],
    }


def load_task(root: Path, task_id: str, *, create: bool = False) -> tuple[Path, dict[str, Any]]:
    path = task_path(root, task_id)
    if not path.is_file():
        if not create:
            raise FileNotFoundError(f"PPT task not found: {task_id}")
        task = new_task(task_id)
        write_json(path, task)
        return path, task
    task = read_json(path)
    if task.get("schema_version") != TASK_SCHEMA:
        raise ValueError(f"unsupported PPT task schema: {task.get('schema_version')!r}")
    return path, task


def begin_mutation(
    path: Path,
    task: dict[str, Any],
    *,
    operation: str,
    targets: list[str],
    expected_revision: int | None,
) -> int:
    current = int(task.get("revision", 0))
    if expected_revision is not None and expected_revision != current:
        raise ValueError(
            f"task revision conflict: expected {expected_revision}, current {current}; "
            "read get_task_state and reapply the change"
        )
    task["revision"] = current + 1
    task["updated_at"] = utc_now()
    task.setdefault("change_log", []).append(
        {
            "at": task["updated_at"],
            "operation": operation,
            "targets": targets,
            "from_revision": current,
            "to_revision": task["revision"],
        }
    )
    write_json(path, task)
    return int(task["revision"])


def next_version(current: dict[str, Any] | None) -> int:
    return int((current or {}).get("version", 0)) + 1


def make_ref(*, object_id: str, version: int, path: Path) -> dict[str, Any]:
    return {"object_id": object_id, "version": version, "path": str(path.resolve())}


def mark_slide_reports_stale(task: dict[str, Any], slide_id: str) -> None:
    slide = task.setdefault("slides", {}).setdefault(slide_id, {})
    for key in ("layout_report", "review", "content_review", "visual_review"):
        ref = slide.get(key)
        if not ref:
            continue
        ref["applicability"] = "stale"
        report_path = Path(ref.get("path", ""))
        if report_path.is_file():
            report = read_json(report_path)
            report["applicability"] = "stale"
            report["is_verified"] = False
            write_json(report_path, report)
    for export in task.get("exports", []):
        if slide_id in export.get("slide_ids", []):
            export["applicability"] = "stale"
