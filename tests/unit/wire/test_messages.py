from datetime import datetime, timezone

from vekna.wire import (
    CastHello,
    DecideRequested,
    DecideResolved,
    LockGranted,
    RiteStarted,
    decode_frame,
    encode_frame,
)


class TestRoundTrip:
    @staticmethod
    def test_cast_hello_round_trips():
        message = CastHello(
            cast_id="c1",
            project_root="/proj",
            ritual="fix_demo",
            components={"bound": 3, "path": "x.py"},
            started_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
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
            started_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        )

        restored = decode_frame(encode_frame(message))

        assert isinstance(restored, RiteStarted)
        assert restored == message


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
        assert isinstance(decided, DecideResolved)
        assert decided.answer == "yes"

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
