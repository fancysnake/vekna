import io
import textwrap

from vekna.lexicon._inits import main

# A fixture of its own: the project's rituals.py drives a coding agent, which
# an acceptance test must not.
_RITUALS = textwrap.dedent("""
    from pydantic import BaseModel

    from vekna.folio.flow import decide
    from vekna.folio.shell import shell
    from vekna.lexicon import Done, ritual, step


    class FixDemo(BaseModel):
        bound: int


    class Attempt(BaseModel):
        budget: int


    class Fixing(BaseModel):
        budget: int


    class Report(BaseModel):
        fixed: bool
        remaining: int


    @ritual("fix_demo")
    async def fix_demo(components: FixDemo) -> Attempt:
        return Attempt(budget=components.bound)


    @step
    async def check(attempt: Attempt) -> Attempt | Done[Report]:
        result = await shell("test -f .fixed")
        if result.exit_code == 0:
            return Done(Report(fixed=True, remaining=attempt.budget))
        if attempt.budget == 0:
            return Done(Report(fixed=False, remaining=0))
        choice = await decide(
            f"not fixed yet ({attempt.budget} attempts left) — apply a fix?",
            options=["fix", "stop"],
        )
        if choice == "stop":
            return Done(Report(fixed=False, remaining=attempt.budget))
        return Fixing(budget=attempt.budget)


    @step
    async def apply_fix(attempt: Fixing) -> Attempt:
        await shell("touch .fixed")
        return Attempt(budget=attempt.budget - 1)
    """)


class TestAcceptance:
    @staticmethod
    def test_fix_demo_runs_to_completion(tmp_path, monkeypatch, capsys):
        (tmp_path / "rituals.py").write_text(_RITUALS)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sys.stdin", io.StringIO("fix\n"))

        exit_code = main(["fix_demo", "--bound", "3"])

        assert not exit_code
        output = capsys.readouterr().out
        assert "check" in output
        # The result is the model `check` declared in its `Done[Report]`.
        assert 'result: {"fixed":true,"remaining":2}' in output
        assert (tmp_path / ".fixed").is_file()
