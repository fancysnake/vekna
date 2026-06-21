from datetime import datetime, timezone

from vekna.wire import (
    ApprovalResolved,
    CastHello,
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
        decided = decode_frame(
            encode_frame(DecideResolved(cast_id="c1", request_id="q1", choice="yes"))
        )
        approved = decode_frame(
            encode_frame(ApprovalResolved(cast_id="c1", request_id="q2", approved=True))
        )

        assert isinstance(decided, DecideResolved)
        assert decided.choice == "yes"
        assert isinstance(approved, ApprovalResolved)
        assert approved.approved is True

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
