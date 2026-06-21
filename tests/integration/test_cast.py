import textwrap

from vekna.lexicon import main

_USAGE_EXIT = 2

_RITUALS = textwrap.dedent("""
    from pydantic import BaseModel

    from vekna.lexicon import Transition, done, goto, ritual, step


    class Tick(BaseModel):
        left: int


    @step
    async def tick(state: Tick) -> Transition:
        if not state.left:
            return done(state)
        return goto(tick, Tick(left=state.left - 1))


    @ritual("countdown")
    async def countdown(start: int) -> Transition:
        return goto(tick, Tick(left=start))
    """)


_EXTRA = textwrap.dedent("""
    from vekna.lexicon import Transition, done, ritual


    @ritual("ping")
    async def ping() -> Transition:
        return done("pong")
    """)


class TestCast:
    @staticmethod
    def test_runs_ritual_end_to_end(tmp_path, monkeypatch, capsys):
        (tmp_path / "rituals.py").write_text(_RITUALS)
        monkeypatch.chdir(tmp_path)

        exit_code = main(["countdown", "--start", "2"])

        assert exit_code == 0
        assert "tick" in capsys.readouterr().out

    @staticmethod
    def test_unknown_ritual_exits_nonzero(tmp_path, monkeypatch):
        (tmp_path / "rituals.py").write_text(_RITUALS)
        monkeypatch.chdir(tmp_path)

        assert main(["nope"]) == _USAGE_EXIT

    @staticmethod
    def test_missing_rituals_file_exits_nonzero(tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        assert main(["countdown"]) == _USAGE_EXIT

    @staticmethod
    def test_loads_ritual_from_vekna_toml(tmp_path, monkeypatch):
        (tmp_path / "extra.py").write_text(_EXTRA)
        (tmp_path / ".vekna.toml").write_text('[rituals]\nfiles = ["extra.py"]\n')
        monkeypatch.chdir(tmp_path)

        assert main(["ping"]) == 0
