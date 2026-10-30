"""Workflow validation.

Two levels:
  1. STATIC — structural validation of the API-format graph (link integrity,
     required inputs present, no cycles). Always runs before submission.
  2. LIVE — when the engine is online, every class_type is checked against
     the engine's /object_info, which is the authoritative list of nodes the
     running ComfyUI (including custom nodes) actually exposes. This catches
     missing custom nodes and version drift with real evidence, not guesses.
"""
from __future__ import annotations

from typing import Any

from ..logging_config import get_logger
from .errors import ErrorCode, NovaError
from .workflow_builder import REQUIRED_NODES

log = get_logger(__name__)


def validate_static(workflow: dict[str, Any]) -> None:
    """Raise NovaError(WORKFLOW_INVALID) on any structural problem."""
    if not workflow or not isinstance(workflow, dict):
        raise NovaError(ErrorCode.WORKFLOW_INVALID, "Workflow is empty or malformed.")

    node_ids = set(workflow.keys())
    for node_id, node in workflow.items():
        if not isinstance(node, dict) or "class_type" not in node or "inputs" not in node:
            raise NovaError(
                ErrorCode.WORKFLOW_INVALID,
                f"Node '{node_id}' is missing class_type/inputs.",
            )
        inputs = node["inputs"]
        if not isinstance(inputs, dict):
            raise NovaError(ErrorCode.WORKFLOW_INVALID, f"Node '{node_id}' inputs must be an object.")
        for key, value in inputs.items():
            if isinstance(value, list):
                if len(value) != 2:
                    raise NovaError(
                        ErrorCode.WORKFLOW_INVALID,
                        f"Node '{node_id}' input '{key}': link must be [node_id, slot].",
                    )
                src, slot = value
                if str(src) not in node_ids:
                    raise NovaError(
                        ErrorCode.WORKFLOW_INVALID,
                        f"Node '{node_id}' input '{key}' links to missing node '{src}'.",
                    )
                if not isinstance(slot, int) or slot < 0:
                    raise NovaError(
                        ErrorCode.WORKFLOW_INVALID,
                        f"Node '{node_id}' input '{key}' has an invalid output slot.",
                    )

    # cycle check (topological sort)
    deps = {
        nid: {str(v[0]) for v in node["inputs"].values() if isinstance(v, list)}
        for nid, node in workflow.items()
    }
    seen: set[str] = set()
    stack: set[str] = set()

    def visit(nid: str) -> None:
        if nid in stack:
            raise NovaError(ErrorCode.WORKFLOW_INVALID, f"Workflow contains a cycle at node '{nid}'.")
        if nid in seen:
            return
        stack.add(nid)
        for dep in deps.get(nid, ()):
            visit(dep)
        stack.discard(nid)
        seen.add(nid)

    for nid in deps:
        visit(nid)


def validate_required_nodes(workflow_id: str, available_classes: set[str]) -> list[str]:
    """Return the list of REQUIRED node classes missing from the engine."""
    required = REQUIRED_NODES.get(workflow_id, [])
    return [cls for cls in required if cls not in available_classes]


async def validate_live(engine: Any, workflow_id: str) -> None:
    """Validate against the running engine's /object_info. Raises on problems."""
    object_info = await engine.fetch_object_info()
    available = set(object_info.keys())
    missing = validate_required_nodes(workflow_id, available)
    if missing:
        raise NovaError(
            ErrorCode.CUSTOM_NODE_MISSING,
            f"The engine is missing required node(s): {', '.join(missing)}.",
            recovery="Run scripts/Repair-Environment.ps1 (reinstalls custom nodes), then restart the engine.",
            http_status=409,
        )
    log.info("Live workflow validation passed for %s (%d node classes available)",
             workflow_id, len(available))
