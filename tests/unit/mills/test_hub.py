from datetime import UTC, datetime
from typing import Literal
from typing import cast as as_type

import pytest
from pydantic import BaseModel

from vekna.mills.hub import Hub
from vekna.pacts.routing import Routed, Surface
from vekna.wire import (
    CastGoodbye,
    CastHello,
    CastMessage,
    CastStatus,
    DecideRequested,
    DecideResolved,
    GrimoireBegin,
    GrimoireEnd,
    LockGranted,
    RiteDelta,
    RiteFinished,
    RiteStarted,
    WireMessage,
)

_WHEN = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


class _Surface(Surface):
    def __init__(self) -> None:
        self.sent: list[WireMessage] = []

    def send(self, message: WireMessage) -> None:
        self.sent.append(message)


# A viewer whose socket has closed under it: the write is what finds out.
class _Gone(Surface):
    def __init__(self) -> None:
        self.tried: list[WireMessage] = []

    def send(self, message: WireMessage) -> None:
        self.tried.append(message)
        raise BrokenPipeError(32, "Broken pipe")


# A wire type the hub was never taught — what a message added to the protocol
# and not to the match would look like arriving here.
class _Unknown(BaseModel):
    kind: Literal["unknown"] = "unknown"
    cast_id: str


def _hello(cast_id: str = "c1") -> CastHello:
    return CastHello(
        cast_id=cast_id,
        project_root="/proj",
        ritual="fix_demo",
        components={"bound": 3},
        started_at=_WHEN,
    )


def _started(rite_id: str = "r1", *, cast_id: str = "c1") -> RiteStarted:
    return RiteStarted(
        cast_id=cast_id,
        rite_id=rite_id,
        parent_id=None,
        name="run_tests",
        category="step",
        started_at=_WHEN,
    )


def _said(text: str) -> CastStatus:
    return CastStatus(cast_id="c1", text=text, at=_WHEN)


def _asked(request_id: str = "q1") -> DecideRequested:
    return DecideRequested(
        cast_id="c1", rite_id="r1", request_id=request_id, prompt="ok?"
    )


class TestCastLifecycle:
    @staticmethod
    def test_hello_opens_a_cast():
        hub = Hub()

        hub.apply(_hello())

        assert hub.casts["c1"].hello.ritual == "fix_demo"
        assert hub.casts["c1"].status == "running"

    @staticmethod
    def test_goodbye_carries_its_status_into_the_view():
        hub = Hub()
        hub.apply(_hello())

        hub.apply(CastGoodbye(cast_id="c1", status="disconnected", detail="socket eof"))

        assert hub.casts["c1"].status == "disconnected"
        assert hub.casts["c1"].detail == "socket eof"

    @staticmethod
    def test_ending_a_cast_closes_what_it_was_asking():
        hub = Hub()
        hub.apply(_hello())
        hub.apply(_started())
        hub.apply(_asked())

        hub.apply(CastGoodbye(cast_id="c1", status="disconnected"))

        assert hub.casts["c1"].waiting == {}


class TestRites:
    @staticmethod
    def test_deltas_are_kept_as_lines():
        hub = Hub()
        hub.apply(_hello())
        hub.apply(_started())

        hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta="one\ntwo"))

        assert list(hub.casts["c1"].rites["r1"].deltas) == ["one", "two"]

    @staticmethod
    def test_finishing_records_status_and_time():
        hub = Hub()
        hub.apply(_hello())
        hub.apply(_started())

        hub.apply(
            RiteFinished(cast_id="c1", rite_id="r1", status="error", finished_at=_WHEN)
        )

        rite = hub.casts["c1"].rites["r1"]
        assert rite.status == "error"
        assert rite.finished_at == _WHEN


class TestPrompts:
    @staticmethod
    def test_a_request_is_held_until_it_is_resolved():
        hub = Hub()
        hub.apply(_hello())
        hub.apply(_started())

        hub.apply(_asked())
        held = dict(hub.casts["c1"].waiting)
        hub.apply(DecideResolved(cast_id="c1", request_id="q1", answer="yes"))

        assert held["q1"].prompt == "ok?"
        assert hub.casts["c1"].waiting == {}


class TestStatus:
    @staticmethod
    def test_the_latest_line_is_what_the_view_holds():
        hub = Hub()
        hub.apply(_hello())

        hub.apply(_said("main · lint"))
        hub.apply(_said("main · tests"))

        said = hub.casts["c1"].said
        assert said is not None
        assert said.text == "main · tests"

    @staticmethod
    def test_a_cleared_line_is_kept_as_an_empty_one():
        hub = Hub()
        hub.apply(_hello())
        hub.apply(_said("main · lint"))

        hub.apply(_said(""))

        said = hub.casts["c1"].said
        assert said is not None
        assert not said.text

    @staticmethod
    def test_a_late_surface_is_told_what_the_ritual_is_working_on():
        hub = Hub()
        hub.apply(_hello())
        hub.apply(_said("main · tests"))
        surface = _Surface()

        hub.attach_surface(surface)

        assert _said("main · tests") in surface.sent


class TestReplayRule:
    @staticmethod
    def test_grimoire_begin_wipes_what_the_replay_is_about_to_rebuild():
        hub = Hub()
        hub.apply(_hello())
        hub.apply(_started())
        hub.apply(_asked())
        hub.apply(_said("main · lint"))

        hub.apply(GrimoireBegin(cast_id="c1"))

        assert hub.casts["c1"].rites == {}
        assert hub.casts["c1"].waiting == {}
        assert hub.casts["c1"].said is None


class TestDrops:
    @staticmethod
    def test_an_event_for_a_cast_that_has_gone_is_dropped_not_applied():
        seen: list[Routed] = []
        hub = Hub(on_routed=seen.append)

        hub.apply(_started(cast_id="gone"))

        assert seen == [
            Routed(
                kind="rite_started",
                subject="gone",
                action="dropped",
                reason="no such cast",
            )
        ]

    @staticmethod
    def test_a_delta_for_an_unknown_rite_is_dropped():
        seen: list[Routed] = []
        hub = Hub(on_routed=seen.append)
        hub.apply(_hello())

        hub.apply(RiteDelta(cast_id="c1", rite_id="r9", delta="x"))

        assert seen[-1].action == "dropped"
        assert seen[-1].reason == "no such rite"

    @staticmethod
    def test_an_answer_to_no_question_is_dropped():
        seen: list[Routed] = []
        hub = Hub(on_routed=seen.append)
        hub.apply(_hello())

        hub.apply(DecideResolved(cast_id="c1", request_id="q9", answer="yes"))

        assert seen[-1].action == "dropped"
        assert seen[-1].reason == "no such prompt"

    @staticmethod
    def test_a_message_the_hub_cannot_read_is_not_silently_applied():
        hub = Hub()
        hub.apply(_hello())
        surface = _Surface()
        hub.attach_surface(surface)
        surface.sent.clear()

        with pytest.raises(AssertionError):
            hub.apply(as_type("CastMessage", _Unknown(cast_id="c1")))

        assert not surface.sent

    @staticmethod
    def test_a_lock_message_says_when_it_will_mean_something():
        seen: list[Routed] = []
        hub = Hub(on_routed=seen.append)
        hub.apply(_hello())

        hub.apply(
            LockGranted(cast_id="c1", request_id="q1", key="project:edit", token="t1")
        )

        assert seen[-1].action == "dropped"
        assert seen[-1].reason == "locks arrive at 0.7.0"


class TestFanOut:
    @staticmethod
    def test_applied_messages_reach_every_surface_and_the_journal():
        journaled: list[WireMessage] = []
        hub = Hub(on_journal=journaled.append)
        first, second = _Surface(), _Surface()
        hub.attach_surface(first)
        hub.attach_surface(second)

        hub.apply(_hello())

        assert journaled == [_hello()]
        assert first.sent == [_hello()]
        assert second.sent == [_hello()]

    @staticmethod
    def test_a_journal_that_cannot_write_keeps_the_cast_running():
        seen: list[Routed] = []

        def full_disk(_: CastMessage) -> None:
            raise OSError(28, "No space left on device")

        hub = Hub(on_routed=seen.append, on_journal=full_disk)
        surface = _Surface()
        hub.attach_surface(surface)

        hub.apply(_hello())

        assert surface.sent == [_hello()]
        assert seen[-2].reason == "not journaled: [Errno 28] No space left on device"
        assert seen[-1].action == "applied"

    @staticmethod
    def test_a_surface_that_has_gone_is_dropped_and_the_rest_are_sent_to():
        seen: list[Routed] = []
        hub = Hub(on_routed=seen.append)
        gone, healthy = _Gone(), _Surface()
        hub.attach_surface(gone)
        hub.attach_surface(healthy)

        hub.apply(_hello())
        hub.apply(_started())

        assert healthy.sent == [_hello(), _started()]
        assert gone.tried == [_hello()]
        assert [line.reason for line in seen if line.reason is not None] == [
            "surface gone: [Errno 32] Broken pipe"
        ]
        assert seen[-1].action == "applied"

    @staticmethod
    def test_a_dropped_message_reaches_neither():
        journaled: list[WireMessage] = []
        hub = Hub(on_journal=journaled.append)
        surface = _Surface()
        hub.attach_surface(surface)

        hub.apply(_started(cast_id="gone"))

        assert not journaled
        assert not surface.sent

    @staticmethod
    def test_a_detached_surface_stops_receiving():
        hub = Hub()
        surface = _Surface()
        hub.attach_surface(surface)

        hub.detach_surface(surface)
        hub.apply(_hello())

        assert not surface.sent

    @staticmethod
    def test_detaching_one_that_never_attached_is_not_an_error():
        hub = Hub()
        attached = _Surface()
        hub.attach_surface(attached)

        hub.detach_surface(_Surface())
        hub.apply(_hello())

        assert attached.sent == [_hello()]


class TestLateSurface:
    @staticmethod
    def test_it_is_caught_up_on_every_live_cast():
        hub = Hub()
        hub.apply(_hello())
        hub.apply(_started())
        hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta="one\ntwo"))
        hub.apply(
            RiteFinished(cast_id="c1", rite_id="r1", status="ok", finished_at=_WHEN)
        )
        hub.apply(_asked())
        surface = _Surface()

        hub.attach_surface(surface)

        assert [message.kind for message in surface.sent] == [
            "cast_hello",
            "grimoire_begin",
            "rite_started",
            "rite_delta",
            "rite_finished",
            "decide_requested",
            "grimoire_end",
        ]

    @staticmethod
    def test_the_replay_rebuilds_the_same_view():
        hub = Hub()
        hub.apply(_hello())
        hub.apply(_started())
        hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta="one"))
        hub.apply(_asked())
        surface = _Surface()
        hub.attach_surface(surface)

        peer = Hub()
        for message in surface.sent:
            peer.apply(message)

        assert peer.casts == hub.casts

    @staticmethod
    def test_a_rite_that_has_said_nothing_replays_no_output():
        hub = Hub()
        hub.apply(_hello())
        hub.apply(_started())
        surface = _Surface()

        hub.attach_surface(surface)

        assert [message.kind for message in surface.sent] == [
            "cast_hello",
            "grimoire_begin",
            "rite_started",
            "grimoire_end",
        ]

    @staticmethod
    def test_a_cast_that_already_ended_replays_its_ending():
        hub = Hub()
        hub.apply(_hello())
        hub.apply(CastGoodbye(cast_id="c1", status="ok"))
        surface = _Surface()

        hub.attach_surface(surface)

        assert surface.sent[-1] == CastGoodbye(cast_id="c1", status="ok", detail=None)

    @staticmethod
    def test_a_replay_is_not_journaled_twice():
        journaled: list[WireMessage] = []
        hub = Hub(on_journal=journaled.append)
        hub.apply(_hello())

        hub.attach_surface(_Surface())

        assert journaled == [_hello()]


class TestGrimoireBrackets:
    @staticmethod
    def test_begin_and_end_pass_through_to_surfaces():
        hub = Hub()
        hub.apply(_hello())
        surface = _Surface()
        hub.attach_surface(surface)
        surface.sent.clear()

        hub.apply(GrimoireBegin(cast_id="c1"))
        hub.apply(GrimoireEnd(cast_id="c1"))

        assert [message.kind for message in surface.sent] == [
            "grimoire_begin",
            "grimoire_end",
        ]
