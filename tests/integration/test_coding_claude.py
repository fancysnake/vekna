import asyncio
import sys
import textwrap
import types
from dataclasses import dataclass

import pytest

from vekna.lexicon import main

_USAGE_EXIT = 2

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


def _sdk_stub(captured):
    stub = types.ModuleType("claude_agent_sdk")

    @dataclass
    class TextBlock:
        text: str

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

    async def query(*, prompt, options=None):
        await asyncio.sleep(0)
        captured["prompt"] = prompt
        captured["options"] = options
        yield AssistantMessage(content=[TextBlock(text="drafting the haiku")])
        yield ResultMessage(
            session_id="s-stub", total_cost_usd=0.25, num_turns=3, result="haiku done"
        )

    stub.TextBlock = TextBlock
    stub.AssistantMessage = AssistantMessage
    stub.ResultMessage = ResultMessage
    stub.ClaudeAgentOptions = ClaudeAgentOptions
    stub.PermissionResultAllow = PermissionResultAllow
    stub.PermissionResultDeny = PermissionResultDeny
    stub.query = query
    return stub


def _purge_coding_claude():
    for name in [
        module
        for module in list(sys.modules)
        if module.startswith("vekna.folio.coding_claude")
    ]:
        del sys.modules[name]


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setattr("vekna.lexicon._mills._foci", {})
    _purge_coding_claude()
    yield
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
