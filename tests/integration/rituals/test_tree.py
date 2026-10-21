import pytest

from rituals.tree import Look, Stood, Tree, look, tree
from vekna.lexicon import Done, RitualError
from vekna.trial import Trial

_WHERE = "git rev-parse --show-toplevel && git branch --show-current"


class TestTree:
    @staticmethod
    def test_says_the_tree_it_ran_in(trial: Trial) -> None:
        trial.shell.replies(when=_WHERE, exit_code=0, stdout="/pool/1\nfix\n")

        result = trial.cast(tree, Tree())

        assert result == Stood(root="/pool/1", branch="fix", dirty=False)
        assert trial.shell.commands == [_WHERE]

    @staticmethod
    def test_dirty_leaves_an_untracked_file(trial: Trial) -> None:
        trial.shell.replies(when=_WHERE, exit_code=0, stdout="/pool/1\nfix\n")
        trial.shell.replies(when="echo dirt > tree.dirt", exit_code=0)

        transition = trial.walk(look, Look(dirty=True))

        assert transition == Done(Stood(root="/pool/1", branch="fix", dirty=True))
        assert trial.shell.commands == [_WHERE, "echo dirt > tree.dirt"]

    @staticmethod
    def test_dirt_that_will_not_write_fails_the_cast(trial: Trial) -> None:
        trial.shell.replies(when=_WHERE, exit_code=0, stdout="/pool/1\nfix\n")
        trial.shell.replies(
            when="echo dirt > tree.dirt", exit_code=1, stderr="permission denied"
        )

        with pytest.raises(
            RitualError, match=r"leaving tree\.dirt failed: permission denied"
        ):
            trial.walk(look, Look(dirty=True))
        assert trial.shell.commands == [_WHERE, "echo dirt > tree.dirt"]

    @staticmethod
    def test_outside_git_fails_the_cast(trial: Trial) -> None:
        trial.shell.replies(when=_WHERE, exit_code=128, stderr="not a git repository")

        with pytest.raises(RitualError, match="reading the tree failed: not a git"):
            trial.walk(look, Look(dirty=False))
        assert trial.shell.commands == [_WHERE]

    @staticmethod
    def test_detached_head_reads_no_branch(trial: Trial) -> None:
        trial.shell.replies(when=_WHERE, exit_code=0, stdout="/pool/1\n")

        transition = trial.walk(look, Look(dirty=False))

        assert transition == Done(Stood(root="/pool/1", branch="", dirty=False))
        assert trial.shell.commands == [_WHERE]
