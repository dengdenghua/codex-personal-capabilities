"""
SolidWorks Automation Python helper package.
"""

from .sw_connect import (
    connect_solidworks,
    deg,
    mm,
    new_document,
    open_document,
    rebuild_document,
    save_document,
)
from .sw_macro_guard import build_prompt, generate_macro_with_guard, validate_vba_macro
from .sw_preflight import run_preflight
from .sw_resource_guard import assert_can_start, evaluate_launch
from .sw_evidence import EvidenceRecorder
from .sw_agent_loop import Stage, WorkflowJournal
from .sw_session import SolidWorksSession, session

__all__ = [
    "SolidWorksSession",
    "EvidenceRecorder",
    "Stage",
    "WorkflowJournal",
    "assert_can_start",
    "build_prompt",
    "connect_solidworks",
    "deg",
    "evaluate_launch",
    "generate_macro_with_guard",
    "mm",
    "new_document",
    "open_document",
    "rebuild_document",
    "run_preflight",
    "save_document",
    "session",
    "validate_vba_macro",
]
