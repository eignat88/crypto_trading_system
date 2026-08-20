import asyncio

from scripts.run_paper_soak import completed_runtime_error


def test_soak_runner_handles_empty_event_stream():
    async def scenario():
        async def empty_event_stream():
            return None

        task = asyncio.create_task(empty_event_stream())
        await task
        return completed_runtime_error(task)

    assert asyncio.run(scenario()) is None


def test_soak_runner_distinguishes_runtime_crash():
    async def scenario():
        async def crashed_event_stream():
            raise RuntimeError("market source crashed")

        task = asyncio.create_task(crashed_event_stream())
        try:
            await task
        except RuntimeError:
            pass
        return completed_runtime_error(task)

    error = asyncio.run(scenario())
    assert isinstance(error, RuntimeError)
    assert str(error) == "market source crashed"
