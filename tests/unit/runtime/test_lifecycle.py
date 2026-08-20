import pytest

from app.runtime.lifecycle import RuntimeLifecycle, RuntimeState


def test_lifecycle_happy_path() -> None:
    lifecycle = RuntimeLifecycle()
    for state in list(RuntimeState)[1:]:
        lifecycle.transition(state)
    assert lifecycle.state is RuntimeState.STOPPED


def test_lifecycle_rejects_skipped_state() -> None:
    with pytest.raises(RuntimeError, match="Invalid runtime transition"):
        RuntimeLifecycle().transition(RuntimeState.RUNNING)
