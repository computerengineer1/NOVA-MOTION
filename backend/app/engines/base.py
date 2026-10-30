"""Engine adapter interface.

The application talks to *this* interface only. Swapping ComfyUI for another
local runtime (or adding a second one) means adding an adapter, not touching
the UI, API, job manager, or services.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine


@dataclass
class EngineStatus:
    online: bool = False
    base_url: str | None = None
    comfyui_version: str | None = None
    torch_version: str | None = None
    python_version: str | None = None
    devices: list[dict[str, Any]] = field(default_factory=list)
    queue_remaining: int | None = None
    last_error: str | None = None
    checked_at: str | None = None
    managed_process_running: bool = False


@dataclass
class SubmitResult:
    prompt_id: str
    queue_number: int | None = None


@dataclass
class EngineJobResult:
    """Terminal view of one engine prompt execution."""
    prompt_id: str
    status: str                     # success | error | interrupted | running | unknown
    error_message: str | None = None
    error_node_id: str | None = None
    outputs: dict[str, Any] = field(default_factory=dict)   # raw history outputs


ProgressCallback = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class EngineAdapter(ABC):
    """Abstract local inference engine."""

    name: str = "abstract"

    @abstractmethod
    async def get_status(self, *, force: bool = False) -> EngineStatus:
        """Cheap, non-throwing status probe (caches allowed)."""

    @abstractmethod
    async def fetch_object_info(self) -> dict[str, Any]:
        """Authoritative node registry of the running engine."""

    @abstractmethod
    async def submit(self, workflow: dict[str, Any], client_id: str) -> SubmitResult:
        """Queue a workflow. Raises NovaError(ENGINE_EXECUTION_ERROR) on 4xx."""

    @abstractmethod
    async def fetch_result(self, prompt_id: str) -> EngineJobResult | None:
        """Poll history for a prompt id; None while still unknown/running."""

    @abstractmethod
    async def interrupt(self) -> bool:
        """Request interruption of the running prompt. True if accepted."""

    @abstractmethod
    async def delete_queued(self, queue_number: int) -> bool:
        """Remove a pending (not yet running) prompt from the queue."""

    @abstractmethod
    async def free_memory(self) -> bool:
        """Ask the engine to unload models and free VRAM/RAM caches."""

    async def shutdown(self) -> None:  # optional override
        """Release client resources."""
