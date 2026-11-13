from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from functools import wraps
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


def manifest_locked(function):
    """Serialize in-process manifest commits and domain mutations (reentrant)."""
    @wraps(function)
    def wrapped(self, manifest_path, *args, **kwargs):
        key = str(Path(manifest_path).resolve())
        with _locks_guard:
            lock = _locks.setdefault(key, threading.RLock())
        with lock:
            return function(self, manifest_path, *args, **kwargs)
    return wrapped


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> Path:
    """Atomically replace a JSON file so interrupted writes keep the old version."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise
    return path


def load_manifest(path: str | Path) -> tuple[Path, dict[str, Any]]:
    manifest_path = Path(path).expanduser().resolve()
    if not manifest_path.is_file():
        raise FileNotFoundError(f"asset manifest not found: {manifest_path}")
    manifest = read_json(manifest_path)
    if manifest.get("schema_version") != "pdf-assets-prototype/v1":
        raise ValueError(f"unsupported manifest schema: {manifest.get('schema_version')!r}")
    return manifest_path, manifest


def stale_reviews(manifest_path: Path, manifest: dict[str, Any]) -> None:
    """Make old positive/negative conclusions explicitly inapplicable after mutation."""

    for review in manifest.get("reviews", []):
        review["applicability"] = "stale"
        report_path = Path(review.get("report_path", ""))
        if report_path.is_file():
            report = read_json(report_path)
            report["applicability"] = "stale"
            report["is_verified"] = False
            write_json(report_path, report)
    write_json(manifest_path, manifest)


def begin_manifest_mutation(
    manifest_path: Path, manifest: dict[str, Any], *, operation: str, targets: list[str]
) -> int:
    old_revision = int(manifest.get("revision", 1))
    stale_reviews(manifest_path, manifest)
    manifest["revision"] = old_revision + 1
    manifest["updated_at"] = utc_now()
    manifest.setdefault("change_log", []).append(
        {
            "at": manifest["updated_at"],
            "operation": operation,
            "targets": targets,
            "from_revision": old_revision,
            "to_revision": manifest["revision"],
        }
    )
    return int(manifest["revision"])
