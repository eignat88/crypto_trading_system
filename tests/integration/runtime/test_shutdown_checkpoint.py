import pytest

from app.runtime.lifecycle import RuntimeState
from app.runtime.paper_application import PaperApplication
from tests.integration.runtime.test_paper_application_start import Repository, dependencies

pytestmark = pytest.mark.asyncio


async def test_shutdown_persists_checkpoint() -> None:
    repository = Repository()
    app = PaperApplication(dependencies(repository))
    await app.start()
    await app.stop()
    assert repository.saved >= 1
    assert app.lifecycle.state is RuntimeState.STOPPED
