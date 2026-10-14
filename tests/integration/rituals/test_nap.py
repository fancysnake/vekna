import pytest

from rituals.nap import Asleep, Nap, Slept, nap, sleep
from vekna.lexicon import RitualError
from vekna.trial import Trial


class TestNap:
    @staticmethod
    def test_counts_every_nap_it_takes(trial: Trial) -> None:
        trial.shell.replies(when="sleep 5", exit_code=0, always=True)

        result = trial.cast(nap, Nap(naps=3, seconds=5))

        assert result == Slept(naps=3)
        assert trial.shell.commands == ["sleep 5"] * 3
        assert trial.steps == ["sleep"] * 4

    @staticmethod
    def test_a_killed_sleep_fails_the_cast_naming_the_nap(trial: Trial) -> None:
        trial.shell.replies(when="sleep 5", exit_code=143, stderr="Terminated")

        with pytest.raises(RitualError, match="nap 3 failed: Terminated"):
            trial.walk(sleep, Asleep(left=2, slept=2, seconds=5))
        assert trial.shell.commands == ["sleep 5"]
