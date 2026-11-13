"""Structured, atomic evidence recording for CAD automation runs."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def atomic_write_json(path: str | os.PathLike[str], payload: dict[str, Any]) -> Path:
    """Write valid JSON to a temporary file and atomically replace the destination."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(_json_value(payload), ensure_ascii=True, indent=2)
    json.loads(serialized)
    handle, temporary = tempfile.mkstemp(
        prefix=destination.name + ".",
        suffix=".tmp",
        dir=str(destination.parent),
        text=True,
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(serialized)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return destination


@dataclass
class EvidenceRecorder:
    run_id: str
    output_path: str | os.PathLike[str]
    request: dict[str, Any] = field(default_factory=dict)
    status: str = "running"
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    events: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)

    def _flush(self) -> Path:
        self.updated_at = _utc_now()
        return atomic_write_json(self.output_path, asdict(self))

    def event(
        self,
        stage: str,
        status: str,
        message: str,
        **data: Any,
    ) -> Path:
        self.events.append(
            {
                "timestamp": _utc_now(),
                "stage": stage,
                "status": status,
                "message": message,
                "data": data,
            }
        )
        return self._flush()

    def artifact(self, kind: str, path: str | os.PathLike[str], required: bool = True) -> Path:
        artifact_path = Path(path)
        self.artifacts.append(
            {
                "kind": kind,
                "path": str(artifact_path),
                "required": bool(required),
                "exists": artifact_path.exists(),
                "size_bytes": artifact_path.stat().st_size if artifact_path.exists() else 0,
            }
        )
        return self._flush()

    def check(
        self,
        name: str,
        passed: bool,
        expected: Any = None,
        actual: Any = None,
        details: str | None = None,
        required: bool = True,
    ) -> Path:
        self.checks.append(
            {
                "name": name,
                "passed": bool(passed),
                "expected": expected,
                "actual": actual,
                "details": details,
                "required": bool(required),
            }
        )
        return self._flush()

    def finalize(self, status: str) -> Path:
        if status not in {"accepted", "failed", "blocked", "cancelled"}:
            raise ValueError(f"invalid final status: {status}")
        if status == "accepted":
            missing_artifacts = [
                item for item in self.artifacts if item.get("required") and not item.get("exists")
            ]
            failed_checks = [
                item for item in self.checks if item.get("required", True) and not item.get("passed")
            ]
            if missing_artifacts or failed_checks:
                raise ValueError(
                    "cannot accept run with missing required artifacts or failed required checks"
                )
        self.status = status
        return self._flush()
