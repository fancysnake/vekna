import json

import pytest

from rituals.ci_watch import CiWatch
from rituals.sweep import Queued, Sweep, Swept, fan_out, sweep
from vekna.lexicon import Done, RitualError
from vekna.trial import Trial

_LIST = "gh pr list --base main --limit 1000 --json number,isCrossRepository"


def _listed(*numbers: int, forks: tuple[int, ...] = ()) -> str:
    return json.dumps(
        [{"number": n, "isCrossRepository": False} for n in numbers]
        + [{"number": n, "isCrossRepository": True} for n in forks]
    )


class TestSweep:
    @staticmethod
    def test_queues_one_watch_per_pull_request(trial: Trial) -> None:
        trial.shell.replies(when="gh pr list *", exit_code=0, stdout=_listed(7, 9))

        transition = trial.walk(fan_out, Sweep(base_branch="main"))

        assert transition == Done(
            Swept(
                queued=[
                    Queued(pull_request=7, cast_id="c1"),
                    Queued(pull_request=9, cast_id="c2"),
                ]
            )
        )
        assert trial.shell.commands == [_LIST]
        assert [cast.components for cast in trial.queue.enqueued] == [
            CiWatch(pull_request=7),
            CiWatch(pull_request=9),
        ]
        assert trial.queue.rituals == ["ci_watch", "ci_watch"]

    @staticmethod
    def test_a_fork_is_not_queued(trial: Trial) -> None:
        trial.shell.replies(
            when="gh pr list *", exit_code=0, stdout=_listed(7, forks=(8,))
        )

        transition = trial.walk(fan_out, Sweep(base_branch="main"))

        assert transition == Done(Swept(queued=[Queued(pull_request=7, cast_id="c1")]))
        assert [cast.components for cast in trial.queue.enqueued] == [
            CiWatch(pull_request=7)
        ]

    @staticmethod
    def test_forks_do_not_use_up_max_prs(trial: Trial) -> None:
        trial.shell.replies(
            when="gh pr list *", exit_code=0, stdout=_listed(7, 9, forks=(8,))
        )

        transition = trial.walk(fan_out, Sweep(base_branch="main", max_prs=1))

        assert transition == Done(Swept(queued=[Queued(pull_request=7, cast_id="c1")]))
        assert trial.shell.commands == [_LIST]

    @staticmethod
    def test_a_failed_listing_queues_nothing(trial: Trial) -> None:
        trial.shell.replies(when="gh pr list *", exit_code=1, stderr="not a repo")

        with pytest.raises(RitualError, match="not a repo"):
            trial.walk(fan_out, Sweep(base_branch="main"))

        assert trial.queue.enqueued == []


class TestSweepCast:
    @staticmethod
    def test_sweep_lists_against_the_base_it_was_given(trial: Trial) -> None:
        trial.shell.replies(when="gh pr list *", exit_code=0, stdout=_listed())

        result = trial.cast(sweep, Sweep(base_branch="main"))

        assert result == Swept(queued=[])
        assert trial.shell.commands == [_LIST]
