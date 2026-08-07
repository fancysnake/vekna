from datetime import UTC, datetime

import pytest

from vekna.lexicon._pacts import RiteBegan, RiteEnded, RiteStreamed
from vekna.trial import TrialScriptError
from vekna.trial._mills import Recorder, Script
from vekna.trial._pacts import Answer


def _script(*answers: Answer[str]) -> Script[str]:
    script: Script[str] = Script(kind="shell")
    for answer in answers:
        script.add(answer)
    return script


def _began(name: str, *, category="step") -> RiteBegan:
    return RiteBegan(
        rite_id="r1",
        parent_id=None,
        name=name,
        category=category,
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


class TestScriptMatching:
    @staticmethod
    def test_a_pattern_answers_the_call_it_matches():
        script = _script(Answer(value="linted", when="mise run lint:*"))

        assert script.take("mise run lint:py") == "linted"

    @staticmethod
    def test_a_pattern_beats_the_queue_whatever_the_order():
        script = _script(
            Answer(value="whoever asks"), Answer(value="the suite", when="*test:py")
        )

        assert script.take("mise run test:py") == "the suite"
        assert script.take("mise run lint:py") == "whoever asks"

    # Two gates in one TaskGroup arrive in whichever order the scheduler picks.
    # Taken here in the opposite order to which they were added, so a `Script`
    # that ever started consulting arrival order fails this outright rather than
    # making a ritual test flaky.
    @staticmethod
    def test_two_patterns_answer_their_own_calls_in_either_order():
        script = _script(
            Answer(value="linted", when="*lint:py"),
            Answer(value="the suite", when="*test:py"),
        )

        assert script.take("mise run test:py") == "the suite"
        assert script.take("mise run lint:py") == "linted"

    @staticmethod
    def test_two_answers_for_one_pattern_are_taken_in_order():
        script = _script(
            Answer(value="red", when="lint"), Answer(value="green", when="lint")
        )

        assert [script.take("lint"), script.take("lint")] == ["red", "green"]

    @staticmethod
    def test_an_unpatterned_answer_falls_back_to_arrival_order():
        script = _script(Answer(value="first"), Answer(value="second"))

        assert [script.take("a"), script.take("b")] == ["first", "second"]

    @staticmethod
    def test_an_always_answer_is_never_consumed():
        script = _script(Answer(value="green", when="test:py", always=True))

        assert [script.take("test:py") for _ in range(3)] == ["green"] * 3


class TestScriptExhaustion:
    @staticmethod
    def test_an_unscripted_call_names_itself_and_what_is_left():
        script = _script(Answer(value="green", when="mise run test:py"))

        with pytest.raises(TrialScriptError) as raised:
            script.take("rm -rf /")

        assert "'rm -rf /'" in str(raised.value)
        assert "when='mise run test:py'" in str(raised.value)

    @staticmethod
    def test_an_empty_script_says_so():
        script = _script()

        with pytest.raises(TrialScriptError, match="the script is empty"):
            script.take("mise run test:py")

    @staticmethod
    def test_a_consumed_answer_does_not_answer_twice():
        script = _script(Answer(value="once", when="lint"))
        script.take("lint")

        with pytest.raises(TrialScriptError, match="the script is empty"):
            script.take("lint")


class TestRecorder:
    @staticmethod
    def test_steps_are_the_rites_that_began_as_steps():
        recorder = Recorder()

        recorder.record(_began("gates"))
        recorder.record(_began("shell", category="medium"))
        recorder.record(_began("repair"))

        assert recorder.steps == ["gates", "repair"]

    @staticmethod
    def test_deltas_are_kept_in_arrival_order():
        recorder = Recorder()

        recorder.record(RiteStreamed(rite_id="r1", delta="E501"))
        recorder.record(RiteStreamed(rite_id="r2", delta="fixed"))

        assert recorder.deltas == ["E501", "fixed"]

    @staticmethod
    def test_every_event_is_kept_whole():
        recorder = Recorder()
        ended = RiteEnded(
            rite_id="r1",
            status="ok",
            result=None,
            finished_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

        recorder.record(ended)

        assert recorder.events == [ended]
