"""Application loop lifecycle: one persistent loop, clean shutdown."""

from __future__ import annotations

import asyncio
import io
from typing import Any

from bitchat.app.application import Application
from bitchat.storage.config import InMemoryStorage


def make_app(**kwargs: Any) -> Application:
    return Application(
        storage=InMemoryStorage(), stdin=io.StringIO(), stdout=io.StringIO(), **kwargs
    )


async def _current_loop() -> asyncio.AbstractEventLoop:
    return asyncio.get_running_loop()


def test_run_async_reuses_one_persistent_loop_across_calls() -> None:
    app = make_app()
    app.startup()

    first = app._run_async(_current_loop())
    second = app._run_async(_current_loop())

    assert first is second
    assert not first.is_closed()

    app.shutdown()
    assert first.is_closed()
    assert app._loop is None


async def test_run_async_inside_running_loop_schedules_a_task() -> None:
    app = make_app()

    task = app._run_async(_current_loop())

    assert isinstance(task, asyncio.Task)
    assert await task is asyncio.get_running_loop()
    assert app._loop is None


class _FakeCoordinator:
    """Coordinator whose start never completed (is_running stays False)."""

    is_running = False

    def __init__(self) -> None:
        self.stop_calls = 0
        self.leftover: asyncio.Task[None] | None = None

    async def stop(self) -> None:
        self.stop_calls += 1


def test_shutdown_stops_coordinator_even_after_failed_start() -> None:
    coordinator = _FakeCoordinator()
    app = make_app(coordinator=coordinator)  # type: ignore[arg-type]
    app.startup()

    app.shutdown()

    assert coordinator.stop_calls == 1


def test_shutdown_cancels_leftover_tasks_and_is_idempotent() -> None:
    app = make_app()
    app.startup()

    async def spawn_forever() -> asyncio.Task[None]:
        return asyncio.create_task(asyncio.Event().wait())  # type: ignore[arg-type]

    leftover = app._run_async(spawn_forever())
    assert not leftover.done()

    app.shutdown()
    app.shutdown()

    assert leftover.cancelled()
    assert app._loop is None
