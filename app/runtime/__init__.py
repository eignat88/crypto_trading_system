"""Production composition root for the fail-closed paper application."""

from app.runtime.lifecycle import RuntimeLifecycle, RuntimeState
from app.runtime.paper_application import PaperApplication
from app.runtime.preflight import PreflightResult, StartupPreflight

__all__ = [
    "PaperApplication",
    "PreflightResult",
    "RuntimeLifecycle",
    "RuntimeState",
    "StartupPreflight",
]
