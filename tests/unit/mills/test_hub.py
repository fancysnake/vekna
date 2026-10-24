from datetime import UTC, datetime
from typing import Literal
from typing import cast as as_type

import pytest
from pydantic import BaseModel

from vekna.mills.hub import Hub
from vekna.pacts.routing import Routed, Surface
from vekna.wire import (
    AwaitEnded,
    AwaitRequested,
    AwaitWithdrawn,
    CastCancelRequested,
    CastGoodbye,
    CastHello,
    CastMessage,
    CastQueued,
    CastRefused,
    CastRequested,
    CodingSlotRequested,
    DecideClaimed,
    DecideRequested,
    DecideResolved,
    DecideWithdrawn,
    EnqueueRequested,
    GrimoireBegin,
    GrimoireEnd,
    LockGranted,
    RiteDelta,
    RiteFinished,
    RiteStarted,
    TreeBlocked,
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


def _hello(cast_id: str = "c1", *, wired: bool = False) -> CastHello:
    return CastHello(
        cast_id=cast_id,
        project_root="/proj",
        project="/proj/.git",
        ritual="fix_demo",
        components={"bound": 3},
        started_at=_WHEN,
        wired=wired,
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

        finished = RiteFinished(
            cast_id="c1", rite_id="r1", status="error", finished_at=_WHEN, error="boom"
        )

        hub.apply(finished)

        rite = hub.casts["c1"].rites["r1"]
        assert rite.status == "error"
        assert rite.finished == finished

    @staticmethod
    def test_an_empty_delta_is_kept_as_a_blank_line():
        hub = Hub()
        hub.apply(_hello())
        hub.apply(_started())

        hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta=""))

        assert list(hub.casts["c1"].rites["r1"].deltas) == [""]


class TestPrompts:
    @staticmethod
    def test_a_request_is_held_until_it_is_resolved():
        hub = Hub()
        hub.apply(_hello())
        hub.apply(_started())

        hub.apply(_asked())
        held = dict(hub.casts["c1"].waiting)
        hub.apply(DecideResolved(cast_id="c1", request_id="q1", answer="yes"))

        assert held["q1"].request == _asked()
        assert hub.casts["c1"].waiting == {}

    @staticmethod
    def test_a_withdrawn_request_is_no_longer_held():
        hub = Hub()
        hub.apply(_hello())
        hub.apply(_started())
        hub.apply(_asked())

        hub.apply(DecideWithdrawn(cast_id="c1", request_id="q1"))

        assert hub.casts["c1"].waiting == {}


class TestReplayRule:
    @staticmethod
    def test_grimoire_begin_wipes_what_the_replay_is_about_to_rebuild():
        hub = Hub()
        hub.apply(_hello())
        hub.apply(_started())
        hub.apply(_asked())

        hub.apply(GrimoireBegin(cast_id="c1"))

        assert hub.casts["c1"].rites == {}
        assert hub.casts["c1"].waiting == {}


class TestDrops:
    @staticmethod
    def test_an_event_for_a_cast_that_has_gone_is_dropped_not_applied():
        seen: list[Routed] = []
        hub = Hub(on_routed=seen.append)

        hub.apply(_started(cast_id="gone"))

        assert seen == [
            Routed(
                kind="rite_started",
                cast_id="gone",
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

        with pytest.raises(AssertionError, match="kind='unknown', cast_id='c1'"):
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
        assert seen[-1].reason == "locks are not built yet"


class TestRouted:
    @staticmethod
    def test_an_applied_message_says_what_and_whose():
        seen: list[Routed] = []
        hub = Hub(on_routed=seen.append)

        hub.apply(_hello())

        assert seen == [Routed(kind="cast_hello", cast_id="c1", action="applied")]

    @staticmethod
    def test_a_surface_coming_and_going_is_said():
        seen: list[Routed] = []
        hub = Hub(on_routed=seen.append)
        surface = _Surface()

        hub.attach_surface(surface)
        hub.detach_surface(surface)

        assert seen == [
            Routed(kind="surface_hello", cast_id=None, action="attached"),
            Routed(kind="surface_hello", cast_id=None, action="detached"),
        ]


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
    def test_a_failed_rite_replays_its_output_and_its_error():
        hub = Hub()
        hub.apply(_hello())
        hub.apply(_started())
        hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta="one\ntwo"))
        failed = RiteFinished(
            cast_id="c1", rite_id="r1", status="error", finished_at=_WHEN, error="boom"
        )
        hub.apply(failed)
        surface = _Surface()

        hub.attach_surface(surface)

        assert surface.sent == [
            _hello(),
            GrimoireBegin(cast_id="c1"),
            _started(),
            RiteDelta(cast_id="c1", rite_id="r1", delta="one\ntwo"),
            failed,
            GrimoireEnd(cast_id="c1"),
        ]

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
    @pytest.mark.parametrize("status", ["ok", "error", "disconnected"])
    def test_a_cast_that_already_ended_replays_its_ending(
        status: Literal["ok", "error", "disconnected"],
    ):
        hub = Hub()
        hub.apply(_hello())
        hub.apply(CastGoodbye(cast_id="c1", status=status, detail="why"))
        surface = _Surface()

        hub.attach_surface(surface)

        assert surface.sent[-1] == CastGoodbye(
            cast_id="c1", status=status, detail="why"
        )

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


class TestQueued:
    @staticmethod
    def test_a_queued_cast_shows_queued_and_replays_so():
        hub = Hub()
        hub.apply(_hello())
        hub.apply(CastQueued(cast_id="c1"))
        late = _Surface()

        hub.attach_surface(late)

        assert hub.casts["c1"].status == "queued"
        assert late.sent == [
            _hello(),
            GrimoireBegin(cast_id="c1"),
            GrimoireEnd(cast_id="c1"),
            CastQueued(cast_id="c1"),
        ]

    # The spawned cast says its own hello under the queued id, and that is what
    # makes it running.
    @staticmethod
    def test_the_cast_s_own_hello_makes_it_running():
        hub = Hub()
        hub.apply(_hello())
        hub.apply(CastQueued(cast_id="c1"))

        hub.apply(_hello())

        assert hub.casts["c1"].status == "running"


class TestAwaiting:
    @staticmethod
    def test_an_await_is_held_on_the_parent_and_replayed_inside_its_grimoire():
        hub = Hub()
        hub.apply(_hello())
        awaited = AwaitRequested(cast_id="c1", request_id="w1", child="c2")

        hub.apply(awaited)
        late = _Surface()
        hub.attach_surface(late)

        assert hub.casts["c1"].on_children == {"w1": awaited}
        assert late.sent == [
            _hello(),
            GrimoireBegin(cast_id="c1"),
            awaited,
            GrimoireEnd(cast_id="c1"),
        ]

    @staticmethod
    def test_an_ended_or_withdrawn_await_is_let_go():
        hub = Hub()
        hub.apply(_hello())
        hub.apply(AwaitRequested(cast_id="c1", request_id="w1", child="c2"))
        hub.apply(AwaitRequested(cast_id="c1", request_id="w2", child="c3"))

        hub.apply(AwaitEnded(cast_id="c1", request_id="w1", child="c2", status="ok"))
        hub.apply(AwaitWithdrawn(cast_id="c1", request_id="w2"))

        assert hub.casts["c1"].on_children == {}

    @staticmethod
    def test_ending_an_await_never_made_is_dropped():
        seen: list[Routed] = []
        hub = Hub(on_routed=seen.append)
        hub.apply(_hello())

        hub.apply(AwaitWithdrawn(cast_id="c1", request_id="w1"))

        assert (seen[-1].action, seen[-1].reason) == ("dropped", "no such await")

    @staticmethod
    def test_a_cast_that_ends_awaits_nothing():
        hub = Hub()
        hub.apply(_hello())
        hub.apply(AwaitRequested(cast_id="c1", request_id="w1", child="c2"))

        hub.apply(CastGoodbye(cast_id="c1", status="error"))

        assert hub.casts["c1"].on_children == {}

    @staticmethod
    def test_an_enqueue_is_the_circle_s_and_not_the_view_s():
        seen: list[Routed] = []
        hub = Hub(on_routed=seen.append)
        hub.apply(_hello())

        hub.apply(EnqueueRequested(cast_id="c1", request_id="q1", hello=_hello("c2")))

        assert (seen[-1].action, seen[-1].reason) == (
            "dropped",
            "the queue is the circle's",
        )
        assert "c2" not in hub.casts


class TestTreeBlocked:
    # Said after the cast is gone, so it is replayed after its goodbye.
    @staticmethod
    def test_a_blocked_tree_is_held_on_its_cast_and_replayed_last():
        hub = Hub()
        hub.apply(_hello())
        hub.apply(CastGoodbye(cast_id="c1", status="ok"))
        blocked = TreeBlocked(
            cast_id="c1", path="/pool/1", reason="a merge in progress"
        )

        hub.apply(blocked)
        late = _Surface()
        hub.attach_surface(late)

        assert hub.casts["c1"].blocked == blocked
        assert late.sent[-2:] == [CastGoodbye(cast_id="c1", status="ok"), blocked]


class TestPeers:
    @staticmethod
    def test_an_answer_to_an_open_prompt_goes_to_the_cast_and_not_the_view():
        routed: list[Routed] = []
        hub = Hub(on_routed=routed.append)
        hub.apply(_hello(wired=True))
        hub.apply(_asked())
        peer = _Surface()
        hub.open_cast("c1", peer)
        answer = DecideResolved(cast_id="c1", request_id="q1", answer="yes")

        hub.answer(_Surface(), answer)

        assert peer.sent == [answer]
        assert "q1" in hub.casts["c1"].waiting
        assert routed[-1] == Routed(
            kind="decide_resolved", cast_id="c1", action="applied"
        )

    @staticmethod
    def test_an_answer_to_no_open_prompt_goes_nowhere():
        routed: list[Routed] = []
        hub = Hub(on_routed=routed.append)
        hub.apply(_hello(wired=True))
        peer = _Surface()
        hub.open_cast("c1", peer)

        hub.answer(
            _Surface(), DecideResolved(cast_id="c1", request_id="q1", answer="yes")
        )

        assert not peer.sent
        assert routed[-1] == Routed(
            kind="decide_resolved",
            cast_id="c1",
            action="dropped",
            reason="no such prompt",
        )

    @staticmethod
    def test_an_answer_for_a_cast_with_no_connection_is_dropped():
        routed: list[Routed] = []
        hub = Hub(on_routed=routed.append)
        hub.apply(_hello(wired=True))
        hub.apply(_asked())

        hub.answer(
            _Surface(), DecideResolved(cast_id="c1", request_id="q1", answer="yes")
        )

        assert routed[-1].reason == "the cast is not connected"

    @staticmethod
    def test_a_cancel_goes_to_a_running_cast_s_connection():
        routed: list[Routed] = []
        hub = Hub(on_routed=routed.append)
        hub.apply(_hello(wired=True))
        peer = _Surface()
        hub.open_cast("c1", peer)
        cancel = CastCancelRequested(cast_id="c1")

        forwarded = hub.cancel(_Surface(), cancel)

        assert forwarded
        assert peer.sent == [cancel]
        assert routed[-1] == Routed(
            kind="cast_cancel_requested", cast_id="c1", action="applied"
        )

    # Not forwarded is not cut either: the daemon signals only a cast it asked.
    @staticmethod
    def test_a_cancel_for_a_queued_cast_says_it_was_not_forwarded():
        hub = Hub()
        hub.apply(_hello(wired=True))
        hub.apply(CastQueued(cast_id="c1"))
        peer, asker = _Surface(), _Surface()
        hub.open_cast("c1", peer)

        forwarded = hub.cancel(asker, CastCancelRequested(cast_id="c1"))

        assert not forwarded
        assert not peer.sent
        assert asker.sent == [
            CastRefused(reason="not cancelled c1: no such running cast")
        ]

    # Told rather than left believing the cast was asked: with no connection
    # there is no ask, and no cut after it either.
    @staticmethod
    def test_a_cancel_for_a_cast_not_connected_tells_the_asker():
        hub = Hub()
        hub.apply(_hello(wired=True))
        asker = _Surface()

        forwarded = hub.cancel(asker, CastCancelRequested(cast_id="c1"))

        assert not forwarded
        assert asker.sent == [
            CastRefused(reason="not cancelled c1: the cast is not connected")
        ]

    @staticmethod
    def test_a_cancel_for_a_cast_that_ended_goes_nowhere():
        routed: list[Routed] = []
        hub = Hub(on_routed=routed.append)
        hub.apply(_hello(wired=True))
        hub.apply(CastGoodbye(cast_id="c1", status="ok"))
        peer = _Surface()
        hub.open_cast("c1", peer)

        hub.cancel(_Surface(), CastCancelRequested(cast_id="c1"))

        assert not peer.sent
        assert routed[-1] == Routed(
            kind="cast_cancel_requested",
            cast_id="c1",
            action="dropped",
            reason="no such running cast",
        )

    # A cast that reattached is on its new connection before the old one has
    # finished closing.
    @staticmethod
    def test_the_old_connection_closing_keeps_the_new_one():
        hub = Hub()
        old, new = _Surface(), _Surface()
        hub.open_cast("c1", old)
        hub.open_cast("c1", new)

        hub.close_cast("c1", old)

        assert hub.tell("c1", CastQueued(cast_id="c1"))
        assert new.sent == [CastQueued(cast_id="c1")]

    @staticmethod
    def test_a_closed_connection_is_told_nothing():
        hub = Hub()
        peer = _Surface()
        hub.open_cast("c1", peer)

        hub.close_cast("c1", peer)

        assert not hub.tell("c1", CastQueued(cast_id="c1"))
        assert not peer.sent

    @staticmethod
    def test_a_peer_that_has_gone_is_told_nothing_more():
        hub = Hub()
        gone = _Gone()
        hub.open_cast("c1", gone)

        assert not hub.tell("c1", CastQueued(cast_id="c1"))
        assert not hub.tell("c1", CastQueued(cast_id="c1"))
        assert len(gone.tried) == 1

    @staticmethod
    def test_a_hub_alone_starts_nothing():
        surface = _Surface()

        Hub().request(
            surface, CastRequested(project_root="/proj", ritual="nap", components={})
        )

        assert surface.sent == [CastRefused(reason="this daemon starts no casts")]

    @staticmethod
    def test_a_slot_message_is_the_circle_s_not_the_hub_s():
        routed: list[Routed] = []
        hub = Hub(on_routed=routed.append)
        hub.apply(_hello())

        hub.apply(CodingSlotRequested(cast_id="c1", request_id="s1"))

        assert routed[-1].reason == "coding slots are the circle's"


def _claim(claim_id: str | None = "k1") -> DecideClaimed:
    return DecideClaimed(cast_id="c1", request_id="q1", claim_id=claim_id)


def _yes() -> DecideResolved:
    return DecideResolved(cast_id="c1", request_id="q1", answer="yes")


class TestClaims:
    @staticmethod
    def test_an_unclaimed_prompt_of_a_hand_cast_takes_any_surface_s_answer():
        hub = Hub()
        hub.apply(_hello())
        hub.apply(_asked())
        peer = _Surface()
        hub.open_cast("c1", peer)

        hub.answer(_Surface(), _yes())

        assert peer.sent == [_yes()]

    @staticmethod
    def test_a_claim_reaches_the_cast_and_every_surface_and_the_claimer_answers():
        hub = Hub()
        hub.apply(_hello())
        hub.apply(_asked())
        peer, window, other = _Surface(), _Surface(), _Surface()
        hub.open_cast("c1", peer)
        hub.attach_surface(other)
        other.sent.clear()

        hub.claim(window, _claim())
        hub.answer(window, _yes())

        assert peer.sent == [_claim(), _yes()]
        assert other.sent == [_claim()]
        assert hub.casts["c1"].waiting["q1"].claim_id == "k1"

    @staticmethod
    def test_a_claimed_prompt_refuses_everybody_else_s_answer():
        routed: list[Routed] = []
        hub = Hub(on_routed=routed.append)
        hub.apply(_hello(wired=True))
        hub.apply(_asked())
        peer = _Surface()
        hub.open_cast("c1", peer)
        hub.claim(_Surface(), _claim())

        hub.answer(_Surface(), _yes())

        assert peer.sent == [_claim()]
        assert routed[-1].reason == "another surface has claimed the prompt"

    @staticmethod
    def test_a_claim_on_no_open_prompt_or_with_no_id_is_dropped():
        routed: list[Routed] = []
        hub = Hub(on_routed=routed.append)
        hub.apply(_hello())
        hub.claim(_Surface(), _claim())
        hub.apply(_asked())

        hub.claim(_Surface(), _claim(None))

        assert hub.casts["c1"].waiting["q1"].claim_id is None
        assert [route.reason for route in routed[-3:]] == [
            "no such prompt",
            None,
            "the claim is not this surface's",
        ]

    @staticmethod
    def test_the_claimer_leaving_lets_go_of_its_claims_and_says_so():
        hub = Hub()
        hub.apply(_hello())
        hub.apply(_asked())
        peer, window, other = _Surface(), _Surface(), _Surface()
        hub.open_cast("c1", peer)
        hub.attach_surface(window)
        hub.attach_surface(other)
        hub.claim(window, _claim())
        other.sent.clear()

        hub.detach_surface(window)

        assert hub.casts["c1"].waiting["q1"].claim_id is None
        assert peer.sent == [_claim(), _claim(None)]
        assert other.sent == [_claim(None)]

    @staticmethod
    def test_a_claim_ends_with_its_prompt_and_is_not_let_go_after():
        hub = Hub()
        hub.apply(_hello())
        hub.apply(_asked())
        peer, window = _Surface(), _Surface()
        hub.open_cast("c1", peer)
        hub.claim(window, _claim())

        hub.apply(_yes())
        hub.detach_surface(window)

        assert not hub.casts["c1"].waiting
        assert peer.sent == [_claim()]

    # The replay asks the prompt again, unclaimed: the window that held it has
    # to claim it afresh, and leaving no longer lets go of the old claim.
    @staticmethod
    def test_a_replay_ends_the_claim_on_a_prompt_it_asks_again():
        hub = Hub()
        hub.apply(_hello())
        hub.apply(_asked())
        peer, window = _Surface(), _Surface()
        hub.open_cast("c1", peer)
        hub.claim(window, _claim())

        hub.apply(GrimoireBegin(cast_id="c1"))
        hub.apply(_asked())
        hub.detach_surface(window)

        assert hub.casts["c1"].waiting["q1"].claim_id is None
        assert peer.sent == [_claim()]

    @staticmethod
    def test_a_late_surface_hears_the_claim_after_the_prompt():
        hub = Hub()
        hub.apply(_hello())
        hub.apply(_asked())
        hub.claim(_Surface(), _claim())
        late = _Surface()

        hub.attach_surface(late)

        assert late.sent[2:5] == [_asked(), _claim(), GrimoireEnd(cast_id="c1")]

    @staticmethod
    def test_the_claimer_lets_go_by_saying_so():
        hub = Hub()
        hub.apply(_hello())
        hub.apply(_asked())
        peer, window = _Surface(), _Surface()
        hub.open_cast("c1", peer)
        hub.claim(window, _claim())

        hub.claim(window, _claim(None))

        assert hub.casts["c1"].waiting["q1"].claim_id is None
        assert peer.sent == [_claim(), _claim(None)]
