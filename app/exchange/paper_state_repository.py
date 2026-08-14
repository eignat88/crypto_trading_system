from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.paper_state import PaperRuntimeState


class PaperStateRepository(ABC):
    """Persistence contract for paper trading runtime state."""

    @abstractmethod
    async def save_state(self, state: PaperRuntimeState) -> None:
        """Persist current paper runtime state."""

    @abstractmethod
    async def load_state(self) -> PaperRuntimeState | None:
        """Load previously persisted paper runtime state."""
