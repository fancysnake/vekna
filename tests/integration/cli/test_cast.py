import sys
import textwrap

import pytest

from tests.conftest import Tty
from vekna.lexicon import _inits
from vekna.lexicon._inits import main

_USAGE_EXIT = 2
_CAST_FAILED_EXIT = 1
_CASTS = 2

_RITUALS = textwrap.dedent("""
    from pydantic import BaseModel

    from vekna.lexicon import Transition, done, goto, ritual, step


    class Tick(BaseModel):
        left: int


    class Countdown(BaseModel):
        start: int


    @step
    async def tick(state: Tick) -> Transition:
        if not state.left:
            return done(state)
        return goto(tick, Tick(left=state.left - 1))


    @ritual("countdown")
    async def countdown(components: Countdown) -> Transition:
        return goto(tick, Tick(left=components.start))
    """)


_EXTRA = textwrap.dedent("""
    from pydantic import BaseModel

    from vekna.lexicon import NoComponents, Transition, done, ritual


    class Pong(BaseModel):
        said: str


    @ritual("ping")
    async def ping(_: NoComponents) -> Transition:
        return done(Pong(said="pong"))
    """)

_BROKEN = "import a_module_that_does_not_exist\n"

_DASHED = textwrap.dedent("""
    from pydantic import BaseModel

    from vekna.lexicon import Transition, done, ritual


    class Echo(BaseModel):
        text: str


    @ritual("echo")
    async def echo(components: Echo) -> Transition:
        return done(components)
    """)

_BUDGET = textwrap.dedent("""
    from pydantic import BaseModel

    from vekna.lexicon import NoComponents, Transition, goto, ritual, step


    class Spin(BaseModel):
        pass


    @step
    async def spin(state: Spin) -> Transition:
        return goto(spin, state)


    @ritual("spinner", max_steps=2)
    async def spinner(_: NoComponents) -> Transition:
        return goto(spin, Spin())
    """)

# The ordinary way a rituals.py under development dies: not a RitualError, and
# not the ritual saying anything about it.
_BOOM = textwrap.dedent("""
    from pydantic import BaseModel

    from vekna.lexicon import NoComponents, Transition, goto, ritual, step


    class Bang(BaseModel):
        pass


    @step
    async def blow(state: Bang) -> Transition:
        raise ValueError("the ritual body itself raised")


    @ritual("boom")
    async def boom(_: NoComponents) -> Transition:
        return goto(blow, Bang())
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

    @staticmethod
    def test_no_arguments_prints_usage(capsys):
        exit_code = main([])

        assert exit_code == _USAGE_EXIT
        assert "usage:" in capsys.readouterr().err

    @staticmethod
    def test_bare_word_after_ritual_name_is_a_usage_error(
        tmp_path, monkeypatch, capsys
    ):
        (tmp_path / "rituals.py").write_text(_RITUALS)
        monkeypatch.chdir(tmp_path)

        exit_code = main(["countdown", "2"])

        assert exit_code == _USAGE_EXIT
        assert "unexpected argument: '2'" in capsys.readouterr().err

    @staticmethod
    def test_a_flag_cannot_swallow_the_next_flag_as_its_value(
        tmp_path, monkeypatch, capsys
    ):
        (tmp_path / "rituals.py").write_text(_RITUALS)
        monkeypatch.chdir(tmp_path)

        exit_code = main(["countdown", "--start", "--label"])

        assert exit_code == _USAGE_EXIT
        assert "--start is missing a value" in capsys.readouterr().err

    @staticmethod
    def test_a_trailing_flag_with_no_value_is_a_usage_error(
        tmp_path, monkeypatch, capsys
    ):
        (tmp_path / "rituals.py").write_text(_DASHED)
        monkeypatch.chdir(tmp_path)

        exit_code = main(["echo", "--text"])

        assert exit_code == _USAGE_EXIT
        assert "--text is missing a value" in capsys.readouterr().err

    @staticmethod
    def test_an_explicitly_empty_value_is_still_a_value(tmp_path, monkeypatch, capsys):
        (tmp_path / "rituals.py").write_text(_DASHED)
        monkeypatch.chdir(tmp_path)

        exit_code = main(["echo", "--text="])

        assert exit_code == 0
        assert 'result: {"text":""}' in capsys.readouterr().out

    @staticmethod
    def test_a_value_starting_with_dashes_is_passed_with_equals(
        tmp_path, monkeypatch, capsys
    ):
        (tmp_path / "rituals.py").write_text(_DASHED)
        monkeypatch.chdir(tmp_path)

        exit_code = main(["echo", "--text=--verbatim"])

        assert exit_code == 0
        assert 'result: {"text":"--verbatim"}' in capsys.readouterr().out

    @staticmethod
    def test_ritual_error_exits_one(tmp_path, monkeypatch, capsys):
        (tmp_path / "rituals.py").write_text(_BUDGET)
        monkeypatch.chdir(tmp_path)

        exit_code = main(["spinner"])

        assert exit_code == _CAST_FAILED_EXIT
        assert "cast failed: " in capsys.readouterr().err


class TestCastId:
    @staticmethod
    def test_two_casts_of_one_ritual_get_distinct_ids(tmp_path, monkeypatch):
        (tmp_path / "rituals.py").write_text(_RITUALS)
        monkeypatch.chdir(tmp_path)
        seen: list[str] = []
        real = _inits.Grimoire

        def _record(*, cast_id: str, **kwargs):
            seen.append(cast_id)
            return real(cast_id=cast_id, **kwargs)

        monkeypatch.setattr(_inits, "Grimoire", _record)

        assert main(["countdown", "--start", "0"]) == 0
        assert main(["countdown", "--start", "0"]) == 0
        assert len(set(seen)) == len(seen) == _CASTS
        assert "countdown" not in seen


class TestCastHelp:
    @staticmethod
    def test_reports_that_rituals_could_not_be_loaded(tmp_path, monkeypatch, capsys):
        (tmp_path / "rituals.py").write_text(_BROKEN)
        monkeypatch.chdir(tmp_path)

        exit_code = main(["--help"])

        assert exit_code == 0
        assert "could not load rituals" in capsys.readouterr().out

    @staticmethod
    def test_reports_when_no_rituals_are_found(tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.chdir(tmp_path)

        exit_code = main(["--help"])

        assert exit_code == 0
        assert "no rituals found" in capsys.readouterr().out

    @staticmethod
    def test_lists_available_rituals_with_their_options(tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "rituals.py").write_text(_RITUALS)
        monkeypatch.chdir(tmp_path)

        exit_code = main(["--help"])

        out = capsys.readouterr().out
        assert exit_code == 0
        assert "available rituals:\n" in out
        assert "  countdown  --start <int>\n" in out


class TestCastConfig:
    @staticmethod
    def test_loads_ritual_from_global_config(tmp_path, monkeypatch):
        config = tmp_path / "home" / ".config" / "vekna"
        config.mkdir(parents=True)
        (config / "config.toml").write_text('[rituals]\nfiles = ["extra.py"]\n')
        (config / "extra.py").write_text(_EXTRA)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        project = tmp_path / "project"
        project.mkdir()
        monkeypatch.chdir(project)

        assert main(["ping"]) == 0

    @staticmethod
    def test_config_files_resolve_against_the_config_not_the_cwd(tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "extra.py").write_text(_EXTRA)
        (tmp_path / ".vekna.toml").write_text('[rituals]\nfiles = ["extra.py"]\n')
        nested = tmp_path / "src" / "deep"
        nested.mkdir(parents=True)
        monkeypatch.chdir(nested)

        assert main(["ping"]) == 0

    @staticmethod
    def test_loads_ritual_from_configured_module(tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "vekna_test_pingmod.py").write_text(_EXTRA)
        (tmp_path / ".vekna.toml").write_text(
            '[rituals]\nmodules = ["vekna_test_pingmod"]\n'
        )
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.chdir(tmp_path)

        assert main(["ping"]) == 0

    @staticmethod
    def test_a_rituals_key_that_is_not_a_table_stops_the_cast(
        tmp_path, monkeypatch, capsys
    ):
        # The rituals.py beside it is loadable, and deliberately does not save
        # the cast: a config that cannot be read is not a fallback situation.
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "rituals.py").write_text(_RITUALS)
        (tmp_path / ".vekna.toml").write_text('rituals = "nope"\n')
        monkeypatch.chdir(tmp_path)

        exit_code = main(["countdown", "--start", "1"])

        assert exit_code == _USAGE_EXIT
        assert ".vekna.toml" in capsys.readouterr().err

    @staticmethod
    def test_unimportable_rituals_file_is_a_usage_error(tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "extra.txt").write_text(_EXTRA)
        (tmp_path / ".vekna.toml").write_text('[rituals]\nfiles = ["extra.txt"]\n')
        monkeypatch.chdir(tmp_path)

        exit_code = main(["ping"])

        assert exit_code == _USAGE_EXIT
        assert "cannot import rituals from" in capsys.readouterr().err


# stdout as the terminal it is in real use: the notification is an escape
# sequence written only to a tty, and pytest's capture is not one.
def _cast_on_a_tty(argv: list[str], monkeypatch) -> Tty:
    tty = Tty()
    monkeypatch.setattr(sys, "stdout", tty)
    main(argv)
    return tty


class TestCastNotify:
    @staticmethod
    def test_a_finished_cast_raises_a_notification(tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "rituals.py").write_text(_RITUALS)
        monkeypatch.chdir(tmp_path)

        tty = _cast_on_a_tty(["countdown", "--start", "1"], monkeypatch)

        assert "\x1b]777;notify;vekna finished;countdown\x07" in tty.getvalue()

    @staticmethod
    def test_a_failed_cast_says_which_ritual_failed(tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "rituals.py").write_text(_BUDGET)
        monkeypatch.chdir(tmp_path)

        tty = _cast_on_a_tty(["spinner"], monkeypatch)

        assert "\x1b]777;notify;vekna failed;spinner: " in tty.getvalue()

    @staticmethod
    def test_a_step_raising_anything_else_notifies_and_keeps_the_traceback(
        tmp_path, monkeypatch
    ):
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "rituals.py").write_text(_BOOM)
        monkeypatch.chdir(tmp_path)
        tty = Tty()
        monkeypatch.setattr(sys, "stdout", tty)

        with pytest.raises(ValueError, match="the ritual body itself raised"):
            main(["boom"])

        assert (
            "\x1b]777;notify;vekna failed;boom: the ritual body itself raised\x07"
            in tty.getvalue()
        )

    @staticmethod
    def test_a_redirected_cast_collects_no_escape_codes(tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "rituals.py").write_text(_RITUALS)
        monkeypatch.chdir(tmp_path)

        main(["countdown", "--start", "1"])

        assert "\x1b]777" not in capsys.readouterr().out
