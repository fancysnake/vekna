import asyncio
from collections.abc import Callable, Sequence

import pytest
from pydantic import BaseModel

from vekna.lexicon._pacts import (
    AskFn,
    CodingCall,
    FocusReply,
    GateFn,
    ShellCall,
    ShellReply,
)
from vekna.trial import CodingDouble, DecideDouble, ShellDouble, TrialScriptError
from vekna.trial._mills import Script


class Judgement(BaseModel):
    verdict: str


# What `Trial` builds. A double is handed its script rather than making one, so
# these say the same thing the harness does.
def _coding() -> CodingDouble:
    return CodingDouble(Script(kind="coding"))


def _shell() -> ShellDouble:
    return ShellDouble(Script(kind="shell"))


def _decide() -> DecideDouble:
    return DecideDouble(Script(kind="decide"))


def _call(prompt: str, *, resume: str | None = None) -> CodingCall:
    return CodingCall(
        prompt=prompt,
        model=None,
        system=None,
        cwd=None,
        output_schema=None,
        focus_options=None,
        resume=resume,
    )


# The three the medium hands a focus. `gate` is None whenever the call declared
# no `gate_tools`, which is the case a plain `coding(...)` makes.
def _answered(
    *,
    double: CodingDouble,
    call: CodingCall,
    gate: GateFn | None = None,
    ask: AskFn | None = None,
    on_delta: Callable[[str], None] = lambda _: None,
) -> FocusReply:
    async def refuse(question: str, options: Sequence[str] | None) -> str:
        await asyncio.sleep(0)
        raise AssertionError(question, options)

    return asyncio.run(
        double.run(call, on_delta=on_delta, gate=gate, ask=ask or refuse)
    )


# The two the shell medium hands its focus.
def _replied(
    *, double: ShellDouble, command: str, on_line: Callable[[str], None] | None = None
) -> ShellReply:
    return asyncio.run(double.run(ShellCall(command=command), on_line=on_line))


class TestCodingDouble:
    @staticmethod
    def test_the_scripted_text_comes_back():
        double = _coding()
        double.replies("fixed the long line")

        reply = _answered(double=double, call=_call("make it green"))

        assert reply.text == "fixed the long line"

    @staticmethod
    def test_a_model_reply_is_serialised_for_the_medium_to_validate():
        double = _coding()
        double.replies(Judgement(verdict="ship"))

        assert (
            _answered(double=double, call=_call("review")).text == '{"verdict":"ship"}'
        )

    @staticmethod
    def test_calls_are_recorded_whole_and_prompts_read_off_them():
        double = _coding()
        double.replies("done", always=True)

        _answered(double=double, call=_call("first"))
        _answered(double=double, call=_call("second", resume="s1"))

        assert double.prompts == ["first", "second"]
        assert double.calls[1].resume == "s1"

    @staticmethod
    def test_a_fresh_call_is_handed_a_new_session_id():
        double = _coding()
        double.replies("done", always=True)

        first = _answered(double=double, call=_call("first"))
        second = _answered(double=double, call=_call("second"))

        assert [first.session_id, second.session_id] == ["s1", "s2"]

    @staticmethod
    def test_a_resuming_call_stays_on_its_session():
        double = _coding()
        double.replies("done", always=True)
        _answered(double=double, call=_call("first"))

        assert (
            _answered(double=double, call=_call("again", resume="s1")).session_id
            == "s1"
        )

    @staticmethod
    def test_the_reply_streams_the_way_an_agent_s_output_does():
        double = _coding()
        double.replies("thinking out loud")
        deltas: list[str] = []

        _answered(double=double, call=_call("work"), on_delta=deltas.append)

        assert deltas == ["thinking out loud"]

    @staticmethod
    def test_an_empty_reply_streams_nothing():
        double = _coding()
        double.replies()
        deltas: list[str] = []

        _answered(double=double, call=_call("work"), on_delta=deltas.append)

        assert not deltas

    @staticmethod
    def test_a_scripted_tool_meets_the_gate_the_call_declared():
        double = _coding()
        double.replies("ran it", uses=["Bash"])

        async def gate(tool: str) -> bool:
            await asyncio.sleep(0)
            return tool != "Bash"

        _answered(double=double, call=_call("work"), gate=gate)

        assert double.gated == [("Bash", False)]

    @staticmethod
    def test_an_ungated_call_allows_the_tool_it_used():
        double = _coding()
        double.replies("ran it", uses=["Bash"])

        _answered(double=double, call=_call("work"))

        assert double.gated == [("Bash", True)]

    @staticmethod
    def test_a_scripted_question_reaches_the_human_and_the_answer_is_kept():
        double = _coding()
        double.replies("asked first", asks=["which port?"])

        async def ask(question: str, _options: Sequence[str] | None) -> str:
            await asyncio.sleep(0)
            return f"answered {question}"

        _answered(double=double, call=_call("work"), ask=ask)

        assert double.answered == ["answered which port?"]


class TestShellDouble:
    @staticmethod
    def test_the_scripted_reply_comes_back_and_the_command_is_recorded():
        double = _shell()
        double.replies(when="mise run lint:py", exit_code=1, stdout="E501")

        reply = _replied(double=double, command="mise run lint:py")

        assert (reply.exit_code, reply.stdout) == (1, "E501")
        assert double.commands == ["mise run lint:py"]

    @staticmethod
    def test_output_reaches_on_line_the_way_bash_output_does():
        double = _shell()
        double.replies(stdout="first\nsecond\n", stderr="oops\n")
        lines: list[str] = []

        _replied(double=double, command="anything", on_line=lines.append)

        assert lines == ["first", "second", "oops"]

    @staticmethod
    def test_nothing_streams_when_the_medium_asked_for_silence():
        double = _shell()
        double.replies(stdout="quiet\n")

        reply = _replied(double=double, command="anything")

        assert reply.stdout == "quiet\n"


class TestDecideDouble:
    @staticmethod
    def test_a_true_answer_reads_as_the_channel_s_yes():
        double = _decide()
        double.answers(answer=True, when="*hand it to the agent?*")

        answer = asyncio.run(double.decide(prompt="red — hand it to the agent?"))

        assert answer == "yes"

    @staticmethod
    def test_an_offered_option_passes_through():
        double = _decide()
        double.answers(answer="file")

        answer = asyncio.run(
            double.decide(prompt="what now?", options=["fix", "file", "ignore"])
        )

        assert answer == "file"

    @staticmethod
    def test_an_answer_outside_the_options_is_refused():
        double = _decide()
        double.answers(answer="repair")

        with pytest.raises(TrialScriptError, match="not one of the offered answers"):
            asyncio.run(double.decide(prompt="what now?", options=["fix", "stop"]))

    @staticmethod
    def test_a_yes_no_prompt_refuses_an_answer_that_is_neither():
        double = _decide()
        double.answers(answer="maybe")

        with pytest.raises(TrialScriptError, match="not one of the offered answers"):
            asyncio.run(double.decide(prompt="spend the agent?"))

    @staticmethod
    def test_free_text_is_whatever_was_scripted():
        double = _decide()
        double.answers(answer="the port is 9000")

        answer = asyncio.run(double.decide(prompt="which port?", free=True))

        assert answer == "the port is 9000"

    @staticmethod
    def test_suggested_options_do_not_refuse_an_answer_past_them():
        double = _decide()
        double.answers(answer="rewrite the parser")

        answer = asyncio.run(
            double.decide(prompt="what now?", options=["fix", "stop"], free=True)
        )

        assert answer == "rewrite the parser"

    @staticmethod
    def test_what_was_offered_is_recorded_as_it_was_offered():
        double = _decide()
        double.answers(answer="fix")

        asyncio.run(double.decide(prompt="what now?", options=["fix", "stop"]))

        assert double.asked[0].options == ("fix", "stop")
        assert double.prompts == ["what now?"]

    @staticmethod
    def test_the_caller_s_own_list_is_no_longer_theirs_to_change():
        double = _decide()
        double.answers(answer="fix")
        options = ["fix", "stop"]

        asyncio.run(double.decide(prompt="what now?", options=options))
        options.append("burn it down")

        assert double.asked[0].options == ("fix", "stop")
