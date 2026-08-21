from datetime import UTC, datetime, timedelta

from vekna.mills.station import PROMPT, Station, ritual_of
from vekna.wire import CastRequested

_WHEN = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _asked(*argv: str) -> CastRequested:
    return CastRequested(lich="hollow-vesper", argv=list(argv))


def _standing() -> Station:
    return Station(name="hollow-vesper", root="/proj")


class TestTheSlot:
    @staticmethod
    def test_an_idle_lich_refuses_nothing():
        station = _standing()

        assert station.idle
        assert station.refusal(_asked("fix_demo")) is None

    # One cast, never two. A second is refused rather than queued: nothing
    # queued means no backlog to reason about and nothing lost when the process
    # dies.
    @staticmethod
    def test_a_second_cast_is_refused_and_says_what_runs():
        station = _standing()
        station.began(_asked("fix_demo", "--bound=3"), at=_WHEN)

        refused = station.refusal(_asked("pr_triage"))

        assert refused is not None
        assert (refused.lich, refused.ritual, refused.since) == (
            "hollow-vesper",
            "fix_demo",
            _WHEN,
        )

    @staticmethod
    def test_the_slot_comes_back_when_the_cast_ends():
        station = _standing()
        station.began(_asked("fix_demo"), at=_WHEN)

        status = station.ended()

        assert station.idle
        assert (status.ritual, status.since, status.cast_id) == (None, None, None)

    # The slot is taken by the request, not by the process: a second `cast` a
    # moment later has to be refused before any cast has said its id.
    @staticmethod
    def test_what_it_says_about_itself_while_casting():
        station = _standing()

        status = station.began(_asked("fix_demo"), at=_WHEN - timedelta(minutes=4))

        assert status.lich == "hollow-vesper"
        assert status.ritual == "fix_demo"
        assert status.cast_id is None


class TestRitualOf:
    @staticmethod
    def test_the_first_argument_is_the_ritual():
        assert ritual_of(["fix_demo", "--bound=3"]) == "fix_demo"

    # `casting --prompt for four minutes` is not a status line, and there is no
    # ritual name to show where one would go.
    @staticmethod
    def test_a_bare_prompt_is_called_a_prompt():
        assert ritual_of(["--prompt", "explain this"]) == PROMPT
        assert ritual_of(["-p", "explain this"]) == PROMPT
        assert ritual_of(["--prompt=explain this"]) == PROMPT

    @staticmethod
    def test_nothing_at_all_is_a_prompt_too():
        assert ritual_of([]) == PROMPT
