import asyncio
import io
import sys
import textwrap
import types
from dataclasses import dataclass

import pytest

from vekna.lexicon import main, reset_foci

_USAGE_EXIT = 2
_CAST_FAILED_EXIT = 1
_MAX_TURNS = 2

_RITUALS = textwrap.dedent("""
    from pydantic import BaseModel

    from vekna.folio.coding import coding
    from vekna.lexicon import Transition, done, goto, ritual, step


    class Task(BaseModel):
        text: str


    @step
    async def work(task: Task) -> Transition:
        result = await coding(task.text)
        return done(result.text)


    @ritual("write_haiku")
    async def write_haiku(text: str) -> Transition:
        return goto(work, Task(text=text))
    """)

_GATED_RITUALS = textwrap.dedent("""
    from pydantic import BaseModel

    from vekna.folio.coding import coding
    from vekna.lexicon import Transition, done, goto, ritual, step


    class Task(BaseModel):
        text: str


    @step
    async def work(task: Task) -> Transition:
        result = await coding(task.text, gate_tools=["Bash"])
        return done(result.text)


    @ritual("gated")
    async def gated(text: str) -> Transition:
        return goto(work, Task(text=text))
    """)

_TYPED_RITUALS = textwrap.dedent("""
    from pydantic import BaseModel

    from vekna.folio.coding import coding
    from vekna.folio.coding_claude import ClaudeOptions
    from vekna.lexicon import Transition, done, goto, ritual, step


    class Task(BaseModel):
        text: str


    class Plan(BaseModel):
        steps: int


    @step
    async def work(task: Task) -> Transition:
        plan = await coding(
            task.text,
            output=Plan,
            focus_options=ClaudeOptions(
                permission_mode="plan",
                allowed_tools=["Read"],
                max_turns=2,
                effort="high",
            ),
        )
        return done(plan.steps)


    @ritual("planned")
    async def planned(text: str) -> Transition:
        return goto(work, Task(text=text))
    """)


_SYSTEM_RITUALS = textwrap.dedent("""
    from pydantic import BaseModel

    from vekna.folio.coding import coding, CodingOpts
    from vekna.lexicon import Transition, done, goto, ritual, step


    class Task(BaseModel):
        text: str


    @step
    async def work(task: Task) -> Transition:
        result = await coding(task.text, opts=CodingOpts(system="you are a poet"))
        return done(result.text)


    @ritual("poet")
    async def poet(text: str) -> Transition:
        return goto(work, Task(text=text))
    """)


def _sdk_stub(captured, *, result="haiku done", tools=(), questions=()):
    stub = types.ModuleType("claude_agent_sdk")

    @dataclass
    class TextBlock:
        text: str

    @dataclass
    class ToolUseBlock:
        name: str

    @dataclass
    class SystemMessage:
        subtype: str

    @dataclass
    class AssistantMessage:
        content: list
        model: str = "stub-model"

    @dataclass
    class ResultMessage:
        session_id: str
        total_cost_usd: float
        num_turns: int
        result: str | None = None

    class ClaudeAgentOptions:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    @dataclass
    class PermissionResultAllow:
        updated_input: dict | None = None

    @dataclass
    class PermissionResultDeny:
        message: str = ""

    def tool(name, description, input_schema):
        # Mirrors the SDK decorator: it returns the tool, it does not call it.
        def register(handler):
            return {
                "name": name,
                "description": description,
                "input_schema": input_schema,
                "handler": handler,
            }

        return register

    def create_sdk_mcp_server(name, version="1.0.0", tools=None):
        return {"name": name, "version": version, "tools": list(tools or [])}

    async def _ask(options, args):
        # The CLI calls back into the host process; the agent waits here.
        handler = options.mcp_servers["vekna"]["tools"][0]["handler"]
        reply = await handler(args)
        return reply["content"][0]["text"]

    async def query(*, prompt, options=None):
        await asyncio.sleep(0)
        captured["prompt"] = prompt
        captured["options"] = options
        yield SystemMessage(subtype="init")
        yield AssistantMessage(
            content=[TextBlock(text="drafting the haiku"), ToolUseBlock(name="Write")]
        )
        if tools:
            captured["permissions"] = [
                await options.can_use_tool(tool, {"tool": tool}, None) for tool in tools
            ]
        if questions:
            captured["answers"] = [await _ask(options, args) for args in questions]
        yield ResultMessage(
            session_id="s-stub", total_cost_usd=0.25, num_turns=3, result=result
        )

    stub.TextBlock = TextBlock
    stub.ToolUseBlock = ToolUseBlock
    stub.SystemMessage = SystemMessage
    stub.AssistantMessage = AssistantMessage
    stub.ResultMessage = ResultMessage
    stub.ClaudeAgentOptions = ClaudeAgentOptions
    stub.PermissionResultAllow = PermissionResultAllow
    stub.PermissionResultDeny = PermissionResultDeny
    stub.create_sdk_mcp_server = create_sdk_mcp_server
    stub.tool = tool
    stub.query = query
    return stub


# _links binds the SDK's names at import time, and every test installs its own
# claude_agent_sdk stub — so the folio has to be re-imported per test. This is
# about rebinding the stub, not about registration, which is now an explicit
# call the cast makes.
def _purge_coding_claude():
    for name in [
        module
        for module in list(sys.modules)
        if module.startswith("vekna.folio.coding_claude")
    ]:
        del sys.modules[name]


@pytest.fixture(autouse=True)
def _isolated():
    reset_foci()
    _purge_coding_claude()
    yield
    reset_foci()
    _purge_coding_claude()


class TestCastWithClaudeFocus:
    @staticmethod
    def test_streams_deltas_and_returns_result(tmp_path, monkeypatch, capsys):
        captured = {}
        monkeypatch.setitem(sys.modules, "claude_agent_sdk", _sdk_stub(captured))
        (tmp_path / "rituals.py").write_text(_RITUALS)
        monkeypatch.chdir(tmp_path)

        exit_code = main(["write_haiku", "--text", "write a haiku"])

        out = capsys.readouterr().out
        assert exit_code == 0
        assert "drafting the haiku" in out
        assert "haiku done" in out
        assert captured["prompt"] == "write a haiku"
        options = captured["options"]
        assert options.permission_mode == "bypassPermissions"
        assert options.can_use_tool is None
        assert options.model is None
        assert options.output_format is None

    @staticmethod
    def test_missing_focus_reports_install_hint(tmp_path, monkeypatch, capsys):
        monkeypatch.setattr("vekna.lexicon._gates._OPTIONAL_FOLIOS", ())
        (tmp_path / "rituals.py").write_text(_RITUALS)
        monkeypatch.chdir(tmp_path)

        exit_code = main(["write_haiku", "--text", "write a haiku"])

        assert exit_code == _USAGE_EXIT
        assert "claude-agent-sdk" in capsys.readouterr().err


class TestToolGate:
    @staticmethod
    def test_watched_tool_is_denied_when_the_human_says_no(
        tmp_path, monkeypatch, capsys
    ):
        captured = {}
        stub = _sdk_stub(captured, tools=("Bash", "Read"))
        monkeypatch.setitem(sys.modules, "claude_agent_sdk", stub)
        monkeypatch.setattr(sys, "stdin", io.StringIO("n\n"))
        (tmp_path / "rituals.py").write_text(_GATED_RITUALS)
        monkeypatch.chdir(tmp_path)

        exit_code = main(["gated", "--text", "edit files"])

        assert exit_code == 0
        assert captured["options"].permission_mode == "default"
        denied, allowed = captured["permissions"]
        assert isinstance(denied, stub.PermissionResultDeny)
        assert denied.message == "denied by the vekna decide gate"
        assert isinstance(allowed, stub.PermissionResultAllow)
        assert allowed.updated_input == {"tool": "Read"}
        assert "allow tool 'Bash'?" in capsys.readouterr().out

    @staticmethod
    def test_watched_tool_is_allowed_when_the_human_says_yes(
        tmp_path, monkeypatch, capsys
    ):
        captured = {}
        stub = _sdk_stub(captured, tools=("Bash",))
        monkeypatch.setitem(sys.modules, "claude_agent_sdk", stub)
        monkeypatch.setattr(sys, "stdin", io.StringIO("y\n"))
        (tmp_path / "rituals.py").write_text(_GATED_RITUALS)
        monkeypatch.chdir(tmp_path)

        exit_code = main(["gated", "--text", "edit files"])

        assert exit_code == 0
        (allowed,) = captured["permissions"]
        assert isinstance(allowed, stub.PermissionResultAllow)
        assert allowed.updated_input == {"tool": "Bash"}
        assert "haiku done" in capsys.readouterr().out


class TestAgentQuestions:
    @staticmethod
    def test_agent_asks_mid_rite_and_waits_for_the_answer(
        tmp_path, monkeypatch, capsys
    ):
        captured = {}
        stub = _sdk_stub(
            captured,
            questions=(
                {
                    "question": "unit or integration?",
                    "options": ["unit", "integration"],
                },
                {"question": "which fixture?"},
            ),
        )
        monkeypatch.setitem(sys.modules, "claude_agent_sdk", stub)
        monkeypatch.setattr(
            sys, "stdin", io.StringIO("integration\nthe tmp_path one\n")
        )
        (tmp_path / "rituals.py").write_text(_RITUALS)
        monkeypatch.chdir(tmp_path)

        exit_code = main(["write_haiku", "--text", "write a haiku"])

        assert exit_code == 0
        assert captured["answers"] == ["integration", "the tmp_path one"]
        out = capsys.readouterr().out
        assert "unit or integration?" in out
        assert "which fixture?" in out

    @staticmethod
    def test_ask_tool_is_offered_on_every_call(tmp_path, monkeypatch):
        captured = {}
        monkeypatch.setitem(sys.modules, "claude_agent_sdk", _sdk_stub(captured))
        (tmp_path / "rituals.py").write_text(_RITUALS)
        monkeypatch.chdir(tmp_path)

        exit_code = main(["write_haiku", "--text", "write a haiku"])

        assert exit_code == 0
        options = captured["options"]
        assert options.allowed_tools == ["mcp__vekna__ask_human"]
        assert options.mcp_servers["vekna"]["tools"][0]["name"] == "ask_human"
        # The preset is appended to, not replaced.
        assert options.system_prompt["type"] == "preset"
        assert "ask_human" in options.system_prompt["append"]

    @staticmethod
    def test_custom_system_prompt_still_carries_the_ask_instruction(
        tmp_path, monkeypatch, capsys
    ):
        captured = {}
        monkeypatch.setitem(sys.modules, "claude_agent_sdk", _sdk_stub(captured))
        (tmp_path / "rituals.py").write_text(_SYSTEM_RITUALS)
        monkeypatch.chdir(tmp_path)

        exit_code = main(["poet", "--text", "write a haiku"])

        assert exit_code == 0
        assert "haiku done" in capsys.readouterr().out
        system_prompt = captured["options"].system_prompt
        assert system_prompt.startswith("you are a poet")
        assert "ask_human" in system_prompt


class TestFocusOptions:
    @staticmethod
    def test_knobs_and_output_schema_reach_the_sdk(tmp_path, monkeypatch, capsys):
        captured = {}
        stub = _sdk_stub(captured, result='{"steps": 3}')
        monkeypatch.setitem(sys.modules, "claude_agent_sdk", stub)
        (tmp_path / "rituals.py").write_text(_TYPED_RITUALS)
        monkeypatch.chdir(tmp_path)

        exit_code = main(["planned", "--text", "plan the work"])

        assert exit_code == 0
        assert "result: 3" in capsys.readouterr().out
        options = captured["options"]
        assert options.permission_mode == "plan"
        assert options.allowed_tools == ["Read", "mcp__vekna__ask_human"]
        assert options.max_turns == _MAX_TURNS
        assert options.effort == "high"
        assert options.output_format["type"] == "json_schema"
        assert options.output_format["schema"]["properties"]["steps"]

    @staticmethod
    def test_unparsable_structured_reply_fails_the_cast(tmp_path, monkeypatch, capsys):
        captured = {}
        stub = _sdk_stub(captured, result="not json at all")
        monkeypatch.setitem(sys.modules, "claude_agent_sdk", stub)
        (tmp_path / "rituals.py").write_text(_TYPED_RITUALS)
        monkeypatch.chdir(tmp_path)

        exit_code = main(["planned", "--text", "plan the work"])

        assert exit_code == _CAST_FAILED_EXIT
        assert "cast failed: agent output does not validate" in capsys.readouterr().err


class TestPromptSugar:
    @staticmethod
    def test_casts_one_step_ritual_without_rituals_file(tmp_path, monkeypatch, capsys):
        captured = {}
        monkeypatch.setitem(sys.modules, "claude_agent_sdk", _sdk_stub(captured))
        monkeypatch.chdir(tmp_path)

        exit_code = main(["--prompt", "write a haiku"])

        out = capsys.readouterr().out
        assert exit_code == 0
        assert "drafting the haiku" in out
        assert "result: haiku done" in out
        assert captured["prompt"] == "write a haiku"

    @staticmethod
    def test_short_flag_is_equivalent(tmp_path, monkeypatch, capsys):
        captured = {}
        monkeypatch.setitem(sys.modules, "claude_agent_sdk", _sdk_stub(captured))
        monkeypatch.chdir(tmp_path)

        exit_code = main(["-p", "write a haiku"])

        assert exit_code == 0
        assert captured["prompt"] == "write a haiku"
        assert "result: haiku done" in capsys.readouterr().out

    @staticmethod
    def test_inline_prompt_form_is_equivalent(tmp_path, monkeypatch, capsys):
        captured = {}
        monkeypatch.setitem(sys.modules, "claude_agent_sdk", _sdk_stub(captured))
        monkeypatch.chdir(tmp_path)

        exit_code = main(["--prompt=write a haiku"])

        assert exit_code == 0
        assert captured["prompt"] == "write a haiku"
        assert "result: haiku done" in capsys.readouterr().out

    @staticmethod
    def test_inline_prompt_with_trailing_words_is_a_usage_error(
        tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)

        exit_code = main(["--prompt=write", "a haiku"])

        assert exit_code == _USAGE_EXIT
        assert "usage:" in capsys.readouterr().err

    @staticmethod
    def test_empty_prompt_is_a_usage_error(tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)

        exit_code = main(["--prompt"])

        assert exit_code == _USAGE_EXIT
        assert "usage:" in capsys.readouterr().err

    @staticmethod
    def test_positional_arg_stays_a_ritual_name(tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)

        exit_code = main(["write a haiku"])

        assert exit_code == _USAGE_EXIT
        assert "no ritual named" in capsys.readouterr().err
