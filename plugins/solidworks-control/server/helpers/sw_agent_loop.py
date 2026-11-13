"""Small workflow state machine for reproducible SolidWorks agent runs."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

try:
    from .sw_evidence import atomic_write_json
except ImportError:
    from sw_evidence import atomic_write_json


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Stage(str, Enum):
    REQUESTED = "requested"
    PLANNED = "planned"
    EXECUTING = "executing"
    REVIEWING = "reviewing"
    RECOVERING = "recovering"
    ACCEPTED = "accepted"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


ALLOWED_TRANSITIONS = {
    Stage.REQUESTED: {Stage.PLANNED, Stage.BLOCKED, Stage.CANCELLED},
    Stage.PLANNED: {Stage.EXECUTING, Stage.BLOCKED, Stage.CANCELLED},
    Stage.EXECUTING: {Stage.REVIEWING, Stage.RECOVERING, Stage.BLOCKED, Stage.CANCELLED},
    Stage.REVIEWING: {Stage.ACCEPTED, Stage.RECOVERING, Stage.BLOCKED, Stage.CANCELLED},
    Stage.RECOVERING: {Stage.EXECUTING, Stage.BLOCKED, Stage.CANCELLED},
    Stage.ACCEPTED: set(),
    Stage.BLOCKED: set(),
    Stage.CANCELLED: set(),
}


@dataclass
class WorkflowJournal:
    run_id: str
    request: dict[str, Any]
    stage: Stage = Stage.REQUESTED
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    history: list[dict[str, Any]] = field(default_factory=list)

    def transition(self, target: Stage | str, note: str, **details: Any) -> None:
        target = Stage(target)
        if target not in ALLOWED_TRANSITIONS[self.stage]:
            raise ValueError(f"invalid workflow transition: {self.stage.value} -> {target.value}")
        previous = self.stage
        self.stage = target
        self.updated_at = _utc_now()
        self.history.append(
            {
                "timestamp": self.updated_at,
                "from": previous.value,
                "to": target.value,
                "note": note,
                "details": details,
            }
        )

    def save(self, path: str | Path) -> Path:
        payload = asdict(self)
        payload["stage"] = self.stage.value
        return atomic_write_json(path, payload)

    @classmethod
    def load(cls, path: str | Path) -> "WorkflowJournal":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        payload["stage"] = Stage(payload["stage"])
        return cls(**payload)
