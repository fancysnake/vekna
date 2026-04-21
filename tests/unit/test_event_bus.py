import asyncio
from unittest.mock import AsyncMock, call

import pytest

from vekna.mills.bus import EventBus
from vekna.pacts.bus import App, Hook
from vekna.pacts.notify import Event


def _event(app: App = App.CLAUDE, hook: Hook = Hook.NOTIFICATION) -> Event:
    return Event(app=app, hook=hook, payload="", meta={})


class TestRegisterAndPublish:
    @staticmethod
    @pytest.mark.asyncio
    async def test_dispatches_to_registered_handler() -> None:
        bus = EventBus()
        handler = AsyncMock()
        bus.register(App.CLAUDE, Hook.NOTIFICATION, handler)
        event = _event()

        bus.publish(event)
        await bus.drain()

        handler.assert_called_once_with(event)

    @staticmethod
    @pytest.mark.asyncio
    async def test_dispatches_to_all_handlers_for_same_key() -> None:
        bus = EventBus()
        handler_a = AsyncMock()
        handler_b = AsyncMock()
        bus.register(App.CLAUDE, Hook.NOTIFICATION, handler_a)
        bus.register(App.CLAUDE, Hook.NOTIFICATION, handler_b)
        event = _event()

        bus.publish(event)
        await bus.drain()

        handler_a.assert_called_once_with(event)
        handler_b.assert_called_once_with(event)

    @staticmethod
    @pytest.mark.asyncio
    async def test_does_not_dispatch_to_handler_for_different_hook() -> None:
        bus = EventBus()
        handler = AsyncMock()
        bus.register(App.CLAUDE, Hook.ERROR, handler)

        bus.publish(_event(App.CLAUDE, Hook.NOTIFICATION))
        await bus.drain()

        handler.assert_not_called()

    @staticmethod
    @pytest.mark.asyncio
    async def test_does_not_dispatch_to_handler_for_different_app() -> None:
        bus = EventBus()
        handler = AsyncMock()
        bus.register(App.VEKNA, Hook.NOTIFICATION, handler)

        bus.publish(_event(App.CLAUDE, Hook.NOTIFICATION))
        await bus.drain()

        handler.assert_not_called()

    @staticmethod
    @pytest.mark.asyncio
    async def test_drops_event_with_no_registered_handlers() -> None:
        bus = EventBus()

        bus.publish(_event())
        await bus.drain()

        # no error raised — just dropped silently

    @staticmethod
    @pytest.mark.asyncio
    async def test_handler_exception_does_not_crash_bus() -> None:
        bus = EventBus()
        bad_handler = AsyncMock(side_effect=RuntimeError("boom"))
        good_handler = AsyncMock()
        bus.register(App.CLAUDE, Hook.NOTIFICATION, bad_handler)
        bus.register(App.CLAUDE, Hook.NOTIFICATION, good_handler)
        event = _event()

        bus.publish(event)
        await bus.drain()

        good_handler.assert_called_once_with(event)

    @staticmethod
    @pytest.mark.asyncio
    async def test_cancelled_handler_does_not_propagate_error() -> None:
        bus = EventBus()

        async def slow_handler(_: Event) -> None:
            await asyncio.sleep(100)

        bus.register(App.CLAUDE, Hook.NOTIFICATION, slow_handler)
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
        bus.register(App.CLAUDE, Hook.NOTIFICATION, handler)
        event_a = _event()
        event_b = Event(app=App.CLAUDE, hook=Hook.NOTIFICATION, payload="x", meta={})

        bus.publish(event_a)
        bus.publish(event_b)
        await bus.drain()

        assert handler.call_args_list == [call(event_a), call(event_b)]


class TestDrain:
    @staticmethod
    @pytest.mark.asyncio
    async def test_drain_awaits_pending_tasks() -> None:
        bus = EventBus()
        results: list[str] = []

        async def slow_handler(_: Event) -> None:
            await asyncio.sleep(0)
            results.append("done")

        bus.register(App.CLAUDE, Hook.NOTIFICATION, slow_handler)
        bus.publish(_event())

        await bus.drain()

        assert results == ["done"]

    @staticmethod
    @pytest.mark.asyncio
    async def test_drain_is_safe_when_no_tasks() -> None:
        bus = EventBus()
        await bus.drain()  # must not raise
