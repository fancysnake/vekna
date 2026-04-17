import asyncio
from unittest.mock import AsyncMock, call

import pytest

from vekna.mills.bus import EventBus
from vekna.pacts.notify import Event


def _event(app: str = "claude", hook: str = "Notification") -> Event:
    return Event(app=app, hook=hook, payload="", meta={})


class TestRegisterAndPublish:
    @staticmethod
    @pytest.mark.asyncio
    async def test_dispatches_to_registered_handler() -> None:
        bus = EventBus()
        handler = AsyncMock()
        bus.register("claude", "Notification", handler)
        event = _event()

        bus.publish(event)
        await asyncio.gather(
            *asyncio.all_tasks() - {asyncio.current_task()}, return_exceptions=True
        )

        handler.assert_called_once_with(event)

    @staticmethod
    @pytest.mark.asyncio
    async def test_dispatches_to_all_handlers_for_same_key() -> None:
        bus = EventBus()
        handler_a = AsyncMock()
        handler_b = AsyncMock()
        bus.register("claude", "Notification", handler_a)
        bus.register("claude", "Notification", handler_b)
        event = _event()

        bus.publish(event)
        await asyncio.gather(
            *asyncio.all_tasks() - {asyncio.current_task()}, return_exceptions=True
        )

        handler_a.assert_called_once_with(event)
        handler_b.assert_called_once_with(event)

    @staticmethod
    @pytest.mark.asyncio
    async def test_does_not_dispatch_to_handler_for_different_hook() -> None:
        bus = EventBus()
        handler = AsyncMock()
        bus.register("claude", "Stop", handler)

        bus.publish(_event("claude", "Notification"))
        await asyncio.gather(
            *asyncio.all_tasks() - {asyncio.current_task()}, return_exceptions=True
        )

        handler.assert_not_called()

    @staticmethod
    @pytest.mark.asyncio
    async def test_does_not_dispatch_to_handler_for_different_app() -> None:
        bus = EventBus()
        handler = AsyncMock()
        bus.register("vekna", "Notification", handler)

        bus.publish(_event("claude", "Notification"))
        await asyncio.gather(
            *asyncio.all_tasks() - {asyncio.current_task()}, return_exceptions=True
        )

        handler.assert_not_called()

    @staticmethod
    @pytest.mark.asyncio
    async def test_drops_event_with_no_registered_handlers() -> None:
        bus = EventBus()

        bus.publish(_event())
        await asyncio.gather(
            *asyncio.all_tasks() - {asyncio.current_task()}, return_exceptions=True
        )

        # no error raised — just dropped silently

    @staticmethod
    @pytest.mark.asyncio
    async def test_handler_exception_does_not_crash_bus() -> None:
        bus = EventBus()
        bad_handler = AsyncMock(side_effect=RuntimeError("boom"))
        good_handler = AsyncMock()
        bus.register("claude", "Notification", bad_handler)
        bus.register("claude", "Notification", good_handler)
        event = _event()

        bus.publish(event)
        await asyncio.gather(
            *asyncio.all_tasks() - {asyncio.current_task()}, return_exceptions=True
        )

        good_handler.assert_called_once_with(event)

    @staticmethod
    @pytest.mark.asyncio
    async def test_cancelled_handler_does_not_propagate_error() -> None:
        bus = EventBus()

        async def slow_handler(_: Event) -> None:
            await asyncio.sleep(100)

        bus.register("claude", "Notification", slow_handler)
        bus.publish(_event())

        tasks = asyncio.all_tasks() - {asyncio.current_task()}
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    @staticmethod
    @pytest.mark.asyncio
    async def test_publish_multiple_events() -> None:
        bus = EventBus()
        handler = AsyncMock()
        bus.register("claude", "Notification", handler)
        event_a = _event()
        event_b = Event(app="claude", hook="Notification", payload="x", meta={})

        bus.publish(event_a)
        bus.publish(event_b)
        await asyncio.gather(
            *asyncio.all_tasks() - {asyncio.current_task()}, return_exceptions=True
        )

        assert handler.call_args_list == [call(event_a), call(event_b)]
