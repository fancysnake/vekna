from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from vekna.wire import (
    CastHello,
    DecideReleased,
    DecideRequested,
    DecideResolved,
    LockGranted,
    RiteStarted,
    SurfaceHello,
    decode_frame,
    encode_frame,
)


class TestRoundTrip:
    @staticmethod
    def test_cast_hello_round_trips():
        message = CastHello(
            cast_id="c1",
            project_root="/proj",
            project="/proj/.git",
            ritual="fix_demo",
            components={"bound": 3, "path": "x.py"},
            started_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        )

        restored = decode_frame(encode_frame(message))

        assert isinstance(restored, CastHello)
        assert restored == message

    @staticmethod
    def test_rite_started_round_trips():
        message = RiteStarted(
            cast_id="c1",
            rite_id="r1",
            parent_id=None,
            name="run_tests",
            category="step",
            started_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        )

        restored = decode_frame(encode_frame(message))

        assert isinstance(restored, RiteStarted)
        assert restored == message

    @staticmethod
    def test_decide_released_round_trips():
        message = DecideReleased(cast_id="c1", request_id="q1")

        restored = decode_frame(encode_frame(message))

        assert isinstance(restored, DecideReleased)
        assert restored == message

    @staticmethod
    def test_a_claim_with_no_id_is_refused():
        frame = (
            '{"kind":"decide_claimed","cast_id":"c1","request_id":"q1","claim_id":null}'
        )

        with pytest.raises(ValidationError, match="claim_id"):
            decode_frame(frame)


class TestDiscriminator:
    @staticmethod
    def test_kind_selects_concrete_class():
        requested = decode_frame(
            encode_frame(
                DecideRequested(
                    cast_id="c1", rite_id="r1", request_id="q1", prompt="ok?"
                )
            )
        )
        decided = decode_frame(
            encode_frame(DecideResolved(cast_id="c1", request_id="q1", answer="yes"))
        )

        assert isinstance(requested, DecideRequested)
        assert requested.options is None
        assert requested.free is False
        assert requested.reactions is None
        assert isinstance(decided, DecideResolved)
        assert decided.answer == "yes"

    @staticmethod
    def test_surface_hello_needs_no_fields():
        restored = decode_frame(encode_frame(SurfaceHello()))

        assert isinstance(restored, SurfaceHello)

    @staticmethod
    def test_lock_granted_carries_token():
        restored = decode_frame(
            encode_frame(
                LockGranted(cast_id="c1", request_id="q1", key="proj:build", token="t1")
            )
        )

        assert isinstance(restored, LockGranted)
        assert restored.key == "proj:build"
        assert restored.token == "t1"
