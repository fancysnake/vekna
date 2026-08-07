import pytest

pytest_plugins = ["pytester"]

# Subprocess rather than in-process: an inner pytest run re-initialises
# pytest-cov and takes the outer run's coverage data with it. It is also the
# stricter check — the subprocess inherits no plugin from here, so the fixture
# arrives through the entry point or not at all.

_A_RITUAL_TEST = """
from pydantic import BaseModel

from vekna.folio.shell import shell
from vekna.lexicon import Transition, done, step
from vekna.trial import Trial


class State(BaseModel):
    pass


@step
async def check(_state: State) -> Transition:
    return done(await shell("mise run test:py"))


def test_the_fixture_is_installed_and_scripted(trial: Trial) -> None:
    trial.shell.replies(when="mise run test:py", exit_code=0, stdout="green")

    transition = trial.walk(check, State())

    assert transition.result.stdout == "green"
    assert trial.shell.commands == ["mise run test:py"]


def test_each_test_gets_its_own_script(trial: Trial) -> None:
    assert not trial.shell.commands
"""


class TestPytestPlugin:
    @staticmethod
    def test_the_fixture_arrives_without_a_conftest(pytester: pytest.Pytester) -> None:
        pytester.makepyfile(_A_RITUAL_TEST)

        run = pytester.runpytest_subprocess()

        run.assert_outcomes(passed=2)

    @staticmethod
    def test_a_suite_that_never_asks_for_it_is_untouched(
        pytester: pytest.Pytester,
    ) -> None:
        pytester.makepyfile(
            "from vekna.lexicon import SHELL_FOCUS\n"
            "\n"
            "def test_nothing_is_installed():\n"
            "    assert SHELL_FOCUS.resolve(default='bash') == 'bash'\n"
        )

        run = pytester.runpytest_subprocess()

        run.assert_outcomes(passed=1)
