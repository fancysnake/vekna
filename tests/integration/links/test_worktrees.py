import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from vekna.links.worktrees import GitTrees, branch_of
from vekna.pacts.circle import Full, Tending, TreeError
from vekna.wire import (
    AltarRequested,
    BlockedTree,
    FailedTree,
    HeldTree,
    ParkedTree,
    RemovedTree,
    TendedTree,
)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _conflicts(cwd: Path, command: str, branch: str) -> bool:
    ran = subprocess.run(
        ["git", command, "-q", branch], cwd=cwd, capture_output=True, check=False
    )
    return ran.returncode != 0


@pytest.fixture(name="repo")
def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "vekna@example.com")
    _git(repo, "config", "user.name", "vekna")
    (repo / ".gitignore").write_text("venv/\n")
    (repo / "a.txt").write_text("a\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "first")
    return repo


class _Pool:
    def __init__(self, repo: Path, root: Path) -> None:
        self.repo = repo
        self.trees = GitTrees(root=root)
        self.full: Full | None = None
        self.tending = Tending(
            asked=AltarRequested(project_root=str(repo)),
            project=str(repo / ".git"),
            count=2,
            base=None,
            prepare=None,
        )

    # Every later command acts on tree `number` alone.
    def only(self, number: int) -> None:
        self.tending = replace(
            self.tending, asked=self.tending.asked.model_copy(update={"tree": number})
        )

    def asking(self, **asked: bool) -> Tending:
        return replace(self.tending, asked=self.tending.asked.model_copy(update=asked))

    async def init(
        self, *, count: int = 2, prepare: str | None = None
    ) -> list[TendedTree]:
        tending = replace(self.asking(init=True), count=count, prepare=prepare)
        return await self.trees.tend(tending, set())

    async def fix(
        self, *, held: set[str] | None = None, save: bool = False
    ) -> list[TendedTree]:
        return await self.trees.tend(self.asking(fix=True, save=save), held or set())

    async def reset(
        self, *, held: set[str] | None = None, save: bool = False
    ) -> list[TendedTree]:
        return await self.trees.tend(self.asking(reset=True, save=save), held or set())

    async def listed(self, *, held: set[str] | None = None) -> list[TendedTree]:
        return await self.trees.tend(self.tending, held or set())

    async def lease(self, *, held: set[str] | None = None) -> str | None:
        found = await self.trees.lease(
            project_root=str(self.repo),
            project=str(self.repo / ".git"),
            held=held or set(),
        )
        if isinstance(found, Full):
            self.full = found
            return None
        return found

    # A pool of `count` trees, and the first of them leased.
    async def leased(self, *, count: int = 2, prepare: str | None = None) -> str:
        await self.init(count=count, prepare=prepare)
        tree = await self.lease()
        assert tree is not None
        return tree


@pytest.fixture(name="pool")
def _pool(repo: Path, tmp_path: Path) -> _Pool:
    return _Pool(repo, tmp_path / "state" / "worktrees")


@pytest.mark.asyncio
class TestLease:
    @staticmethod
    async def test_a_pool_never_set_up_leases_nothing_and_says_how(pool: _Pool):
        with pytest.raises(TreeError, match=r"run `vekna altar init`"):
            await pool.lease()

        assert _git(pool.repo, "worktree", "list").count("\n") == 0

    @staticmethod
    async def test_a_tree_whose_setup_failed_is_not_leased(pool: _Pool):
        await pool.init(count=1, prepare="exit 3")

        with pytest.raises(TreeError, match=r"run `vekna altar init`"):
            await pool.lease()

    @staticmethod
    async def test_a_parked_tree_is_leased_again(pool: _Pool):
        first = await pool.leased()

        assert await pool.lease() == first
        assert Path(first).name == "1"

    @staticmethod
    async def test_a_held_tree_is_passed_over_for_the_next(pool: _Pool):
        first = await pool.leased()

        second = await pool.lease(held={first})

        assert second is not None
        assert Path(second).name == "2"

    @staticmethod
    async def test_a_full_pool_leases_nothing(pool: _Pool):
        first = await pool.leased(count=1)

        assert await pool.lease(held={first}) is None
        assert pool.full == Full(held=frozenset({first}))

    # Said as the caller said them, and only those that stand in the pool.
    @staticmethod
    async def test_a_full_pool_says_which_held_trees_fill_it(pool: _Pool):
        first = await pool.leased()
        second = await pool.lease(held={first})
        assert second is not None
        unresolved = f"{Path(second).parent}/../{Path(second).parent.name}/2"

        assert await pool.lease(held={first, unresolved, "/elsewhere"}) is None
        assert pool.full == Full(held=frozenset({first, unresolved}))

    # A dead cast left its tree on its own branch; the lease is what parks it.
    @staticmethod
    async def test_a_clean_tree_left_on_another_branch_is_parked_and_leased(
        pool: _Pool,
    ):
        tree = await pool.leased()
        _git(Path(tree), "checkout", "-q", "-b", "feature")

        assert await pool.lease() == tree
        assert _git(Path(tree), "branch", "--show-current") == "vekna/wt-1"

    @staticmethod
    async def test_a_dirty_leftover_is_skipped_and_left_as_it_is(pool: _Pool):
        tree = await pool.leased()
        held = await pool.lease(held={tree})
        assert held is not None
        _git(Path(tree), "checkout", "-q", "-b", "feature")
        (Path(tree) / "a.txt").write_text("edited\n")

        assert await pool.lease(held={held}) is None
        assert _git(Path(tree), "branch", "--show-current") == "feature"
        assert (Path(tree) / "a.txt").read_text() == "edited\n"

    # No cast holds a tree, so none is going to free one.
    @staticmethod
    async def test_every_tree_blocked_and_none_held_says_which(pool: _Pool):
        tree = await pool.leased(count=1)
        (Path(tree) / "a.txt").write_text("edited\n")

        with pytest.raises(TreeError, match=r"every tree is blocked: .*/1 \(unc"):
            await pool.lease()

    @staticmethod
    async def test_a_directory_outside_git_cannot_hold_a_pool(tmp_path: Path):
        plain = tmp_path / "plain"
        plain.mkdir()
        pool = _Pool(plain, tmp_path / "state")

        with pytest.raises(TreeError, match="git worktree"):
            await pool.lease()


@pytest.mark.asyncio
class TestInit:
    @staticmethod
    async def test_each_tree_is_made_on_its_parking_branch_and_prepared(pool: _Pool):
        first, second = await pool.init(prepare="mkdir venv && echo ready > venv/ok")

        assert isinstance(first, ParkedTree)
        assert Path(first.path).name == "1"
        assert Path(first.path).parent.name.startswith("repo-")
        assert _git(Path(first.path), "branch", "--show-current") == "vekna/wt-1"
        assert (Path(first.path) / "venv" / "ok").read_text() == "ready\n"
        assert second == ParkedTree(path=str(Path(first.path).parent / "2"))
        assert _git(Path(second.path), "branch", "--show-current") == "vekna/wt-2"

    @staticmethod
    async def test_a_tree_already_set_up_is_not_prepared_again(pool: _Pool):
        [first] = await pool.init(
            count=1, prepare="mkdir -p venv && echo x >> venv/runs"
        )

        again = await pool.init(count=1, prepare="mkdir -p venv && echo x >> venv/runs")

        assert again == [first]
        assert (Path(first.path) / "venv" / "runs").read_text() == "x\n"

    # No marker, so the next init prepares it again rather than calling ready a
    # tree that only looks it.
    @staticmethod
    async def test_a_failed_prepare_says_why_and_runs_again_next_time(pool: _Pool):
        [failed] = await pool.init(count=1, prepare="echo broken; exit 3")

        [tree] = await pool.init(count=1, prepare="mkdir venv && touch venv/prepared")

        assert isinstance(failed, FailedTree)
        assert "prepare exited 3 " in failed.reason
        assert ": broken" in failed.reason
        assert tree == ParkedTree(path=failed.path)
        assert (Path(tree.path) / "venv" / "prepared").is_file()

    @staticmethod
    async def test_a_held_tree_is_said_held_and_the_rest_made(pool: _Pool):
        first = await pool.leased(count=1)

        made = await pool.trees.tend(pool.asking(init=True), {first})

        assert made == [
            HeldTree(path=first),
            ParkedTree(path=str(Path(first).parent / "2")),
        ]

    @staticmethod
    async def test_trees_stand_on_the_base_asked_for(pool: _Pool):
        _git(pool.repo, "checkout", "-q", "-b", "feature")
        (pool.repo / "a.txt").write_text("feature\n")
        _git(pool.repo, "commit", "-q", "-am", "feature")
        pool.tending = replace(pool.tending, base="main")

        [tree] = await pool.init(count=1)

        assert (Path(tree.path) / "a.txt").read_text() == "a\n"

    @staticmethod
    async def test_a_base_that_names_no_commit_says_so(pool: _Pool):
        pool.tending = replace(pool.tending, base="nowhere")

        with pytest.raises(TreeError, match="the base 'nowhere' names no commit"):
            await pool.init()


@pytest.mark.asyncio
class TestRelease:
    @staticmethod
    async def test_a_clean_tree_goes_back_to_its_parking_branch(pool: _Pool):
        tree = await pool.leased()
        _git(Path(tree), "checkout", "-q", "-b", "feature")
        (Path(tree) / "venv").mkdir()

        assert await pool.trees.release(tree) is None
        assert _git(Path(tree), "branch", "--show-current") == "vekna/wt-1"

    @staticmethod
    async def test_untracked_work_blocks_it(pool: _Pool):
        tree = await pool.leased()
        (Path(tree) / "new.txt").write_text("mine\n")

        assert await pool.trees.release(tree) == "uncommitted changes"

    @staticmethod
    async def test_untracked_work_blocks_it_when_status_hides_untracked(pool: _Pool):
        _git(pool.repo, "config", "status.showUntrackedFiles", "no")
        tree = await pool.leased()
        (Path(tree) / "new.txt").write_text("mine\n")

        assert await pool.trees.release(tree) == "uncommitted changes"

    # Resolved to what HEAD already had, it reads clean to `--porcelain`, and
    # the merge is still open.
    @staticmethod
    async def test_an_open_merge_blocks_it(pool: _Pool):
        tree = await pool.leased()
        work = Path(tree)
        _git(work, "checkout", "-q", "-b", "left")
        (work / "a.txt").write_text("left\n")
        _git(work, "commit", "-q", "-am", "left")
        _git(work, "checkout", "-q", "-b", "right", "main")
        (work / "a.txt").write_text("right\n")
        _git(work, "commit", "-q", "-am", "right")
        assert _conflicts(work, "merge", "left")
        _git(work, "checkout", "-q", "--ours", "a.txt")
        _git(work, "add", "a.txt")

        assert await pool.trees.release(tree) == "a merge in progress"

    @staticmethod
    async def test_a_tree_that_is_gone_says_why(pool: _Pool):
        tree = await pool.leased()
        shutil.rmtree(tree)

        reason = await pool.trees.release(tree)

        assert reason is not None
        assert reason.startswith("git status in ")

    @staticmethod
    async def test_a_checkout_outside_the_pool_is_never_switched(
        pool: _Pool, repo: Path
    ):
        _git(repo, "checkout", "-q", "-b", "feature")

        reason = await pool.trees.release(str(repo))

        assert reason is not None
        assert "is not a tree of the pool" in reason
        assert _git(repo, "branch", "--show-current") == "feature"

    @staticmethod
    async def test_a_directory_under_the_root_not_numbered_is_no_tree(pool: _Pool):
        tree = await pool.leased()
        odd = Path(tree).parent / "notes"
        odd.mkdir()

        reason = await pool.trees.release(str(odd))

        assert reason is not None
        assert "is not a tree of the pool" in reason


@pytest.mark.asyncio
class TestFix:
    @staticmethod
    async def test_saved_work_is_kept_on_a_branch_and_the_tree_parked(pool: _Pool):
        tree = await pool.leased(count=1, prepare="mkdir venv && touch venv/prepared")
        work = Path(tree)
        _git(work, "checkout", "-q", "-b", "feature")
        (work / "a.txt").write_text("edited\n")
        (work / "new.txt").write_text("mine\n")

        [fixed] = await pool.fix(save=True)

        assert isinstance(fixed, ParkedTree)
        assert fixed.saved is not None
        assert fixed.saved.startswith("vekna/rescue/feature-")
        assert _git(pool.repo, "show", f"{fixed.saved}:a.txt") == "edited"
        assert _git(pool.repo, "show", f"{fixed.saved}:new.txt") == "mine"
        assert _git(work, "branch", "--show-current") == "vekna/wt-1"
        assert not _git(work, "status", "--porcelain")
        assert (work / "venv" / "prepared").is_file()

    @staticmethod
    async def test_untracked_work_is_saved_when_status_hides_untracked(pool: _Pool):
        _git(pool.repo, "config", "status.showUntrackedFiles", "no")
        tree = await pool.leased(count=1)
        (Path(tree) / "new.txt").write_text("mine\n")

        [fixed] = await pool.fix(save=True)

        assert isinstance(fixed, ParkedTree)
        assert fixed.saved is not None
        assert _git(pool.repo, "show", f"{fixed.saved}:new.txt") == "mine"

    @staticmethod
    async def test_unsaved_work_is_thrown_away(pool: _Pool):
        tree = await pool.leased(count=1)
        (Path(tree) / "a.txt").write_text("edited\n")
        (Path(tree) / "new.txt").write_text("mine\n")

        [fixed] = await pool.fix()

        assert fixed == ParkedTree(path=tree)
        assert (Path(tree) / "a.txt").read_text() == "a\n"
        assert not (Path(tree) / "new.txt").exists()
        assert "vekna/rescue/" not in _git(pool.repo, "branch", "--list")

    @staticmethod
    async def test_an_open_merge_is_saved_then_aborted(pool: _Pool):
        tree = await pool.leased(count=1)
        work = Path(tree)
        _git(work, "checkout", "-q", "-b", "left")
        (work / "a.txt").write_text("left\n")
        _git(work, "commit", "-q", "-am", "left")
        _git(work, "checkout", "-q", "-b", "right", "main")
        (work / "a.txt").write_text("right\n")
        _git(work, "commit", "-q", "-am", "right")
        assert _conflicts(work, "merge", "left")

        [fixed] = await pool.fix(save=True)

        assert isinstance(fixed, ParkedTree)
        assert fixed.saved is not None
        assert "<<<<<<<" in _git(pool.repo, "show", f"{fixed.saved}:a.txt")
        assert _git(work, "branch", "--show-current") == "vekna/wt-1"
        assert not (
            Path(_git(work, "rev-parse", "--absolute-git-dir")) / "MERGE_HEAD"
        ).exists()

    @staticmethod
    async def test_an_open_rebase_is_saved_under_the_branch_being_rebased(pool: _Pool):
        tree = await pool.leased(count=1)
        work = Path(tree)
        _git(work, "checkout", "-q", "-b", "onto")
        (work / "a.txt").write_text("onto\n")
        _git(work, "commit", "-q", "-am", "onto")
        _git(work, "checkout", "-q", "-b", "feature", "main")
        (work / "a.txt").write_text("feature\n")
        _git(work, "commit", "-q", "-am", "feature")
        assert _conflicts(work, "rebase", "onto")

        [fixed] = await pool.fix(save=True)

        assert isinstance(fixed, ParkedTree)
        assert fixed.saved is not None
        assert fixed.saved.startswith("vekna/rescue/feature-")
        assert _git(work, "branch", "--show-current") == "vekna/wt-1"

    @staticmethod
    async def test_an_open_rebase_of_a_detached_head_is_saved_as_detached(pool: _Pool):
        tree = await pool.leased(count=1)
        work = Path(tree)
        _git(work, "checkout", "-q", "-b", "onto")
        (work / "a.txt").write_text("onto\n")
        _git(work, "commit", "-q", "-am", "onto")
        _git(work, "checkout", "-q", "--detach", "main")
        (work / "a.txt").write_text("detached\n")
        _git(work, "commit", "-q", "-am", "detached")
        assert _conflicts(work, "rebase", "onto")

        [fixed] = await pool.fix(save=True)

        assert isinstance(fixed, ParkedTree)
        assert fixed.saved is not None
        assert fixed.saved.startswith("vekna/rescue/detached-")
        assert _git(work, "branch", "--show-current") == "vekna/wt-1"

    @staticmethod
    async def test_a_held_tree_is_left_as_it_is(pool: _Pool):
        tree = await pool.leased(count=1)
        (Path(tree) / "a.txt").write_text("edited\n")

        fixed = await pool.fix(held={tree})

        assert fixed == [HeldTree(path=tree)]
        assert (Path(tree) / "a.txt").read_text() == "edited\n"

    @staticmethod
    async def test_a_clean_tree_has_nothing_to_save(pool: _Pool):
        tree = await pool.leased(count=1)
        _git(Path(tree), "checkout", "-q", "-b", "feature")

        fixed = await pool.fix(save=True)

        assert fixed == [ParkedTree(path=tree)]
        assert "vekna/rescue/" not in _git(pool.repo, "branch", "--list")

    @staticmethod
    async def test_a_tree_whose_parking_branch_is_gone_says_why(pool: _Pool):
        tree = await pool.leased(count=1)
        _git(Path(tree), "checkout", "-q", "-b", "feature")
        _git(pool.repo, "branch", "-q", "-D", "vekna/wt-1")

        [fixed] = await pool.fix()

        assert isinstance(fixed, FailedTree)
        assert fixed.reason.startswith("git checkout in ")

    # As a daemon summoned from a git hook would inherit them.
    @staticmethod
    async def test_a_repository_named_in_the_environment_is_not_touched(
        pool: _Pool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        tree = await pool.leased(count=1)
        (Path(tree) / "a.txt").write_text("edited\n")
        mine = tmp_path / "mine"
        mine.mkdir()
        _git(mine, "init", "-q")
        (mine / "work.txt").write_text("unsaved\n")
        monkeypatch.setenv("GIT_DIR", str(mine / ".git"))
        monkeypatch.setenv("GIT_WORK_TREE", str(mine))

        fixed = await pool.fix()

        assert fixed == [ParkedTree(path=tree)]
        assert (mine / "work.txt").read_text() == "unsaved\n"

    @staticmethod
    async def test_a_tree_that_is_gone_fails_alone(pool: _Pool):
        first = await pool.leased()
        second = await pool.lease(held={first})
        assert second is not None
        shutil.rmtree(first)
        (Path(second) / "a.txt").write_text("edited\n")

        gone, fixed = await pool.fix()

        assert isinstance(gone, FailedTree)
        assert gone.reason.startswith("git rev-parse in ")
        assert fixed == ParkedTree(path=second)

    # The parking branch never moved since the tree was made; the fix moves it.
    @staticmethod
    async def test_the_tree_is_moved_to_the_base_and_prepared_again(pool: _Pool):
        [tree] = await pool.init(count=1, prepare="echo x >> ../runs")
        (pool.repo / "a.txt").write_text("newer\n")
        _git(pool.repo, "commit", "-q", "-am", "newer")
        pool.tending = replace(pool.tending, prepare="echo x >> ../runs")

        fixed = await pool.fix()

        assert fixed == [tree]
        assert (Path(tree.path) / "a.txt").read_text() == "newer\n"
        assert _git(Path(tree.path), "branch", "--show-current") == "vekna/wt-1"
        assert (Path(tree.path).parent / "runs").read_text() == "x\nx\n"

    @staticmethod
    async def test_a_prepare_that_fails_leaves_the_tree_not_set_up(pool: _Pool):
        await pool.init(count=1)
        pool.tending = replace(pool.tending, prepare="exit 3")

        [fixed] = await pool.fix()

        assert isinstance(fixed, FailedTree)
        assert "prepare exited 3 " in fixed.reason
        with pytest.raises(TreeError, match=r"run `vekna altar init`"):
            await pool.lease()

    @staticmethod
    async def test_asked_for_one_tree_only_that_one_is_fixed(pool: _Pool):
        first = await pool.leased()
        second = Path(first).parent / "2"
        (Path(first) / "a.txt").write_text("edited\n")
        (second / "a.txt").write_text("edited\n")
        pool.only(2)

        fixed = await pool.fix()

        assert fixed == [ParkedTree(path=str(second))]
        assert (second / "a.txt").read_text() == "a\n"
        assert (Path(first) / "a.txt").read_text() == "edited\n"

    @staticmethod
    async def test_asked_for_a_held_tree_it_fails_and_is_left(pool: _Pool):
        tree = await pool.leased()
        (Path(tree) / "a.txt").write_text("edited\n")
        pool.only(1)

        fixed = await pool.fix(held={tree})

        assert fixed == [FailedTree(path=tree, reason="a running cast holds it")]
        assert (Path(tree) / "a.txt").read_text() == "edited\n"

    @staticmethod
    async def test_asked_for_a_tree_the_pool_lacks_says_so(pool: _Pool):
        await pool.init()
        pool.only(7)

        with pytest.raises(TreeError, match="the pool has no worktree 7"):
            await pool.fix()


@pytest.mark.asyncio
class TestReset:
    @staticmethod
    async def test_every_tree_goes_with_what_stood_beside_it(pool: _Pool):
        tree = await pool.leased(prepare="mkdir venv && touch venv/prepared")
        home = Path(tree).parent
        (Path(tree) / "a.txt").write_text("edited\n")

        removed = await pool.reset()

        assert removed == [RemovedTree(path=tree), RemovedTree(path=str(home / "2"))]
        assert not list(home.iterdir())
        assert _git(pool.repo, "worktree", "list").count("\n") == 0

    @staticmethod
    async def test_saved_work_outlives_the_tree(pool: _Pool):
        tree = await pool.leased(count=1)
        (Path(tree) / "new.txt").write_text("mine\n")

        [removed] = await pool.reset(save=True)

        assert isinstance(removed, RemovedTree)
        assert removed.saved is not None
        assert _git(pool.repo, "show", f"{removed.saved}:new.txt") == "mine"
        assert tree not in _git(pool.repo, "worktree", "list")

    @staticmethod
    async def test_a_held_tree_and_its_marker_stay(pool: _Pool):
        tree = await pool.leased()
        home = Path(tree).parent

        reset = await pool.reset(held={tree})

        assert reset == [HeldTree(path=tree), RemovedTree(path=str(home / "2"))]
        assert sorted(entry.name for entry in home.iterdir()) == ["1", "1.prepared"]
        assert await pool.lease() == tree

    # Nothing is removed that could not be saved first.
    @staticmethod
    async def test_a_tree_whose_work_cannot_be_saved_is_left(pool: _Pool):
        tree = await pool.leased(count=1)
        git_file = Path(tree) / ".git"
        linked = git_file.read_text()
        git_file.write_text("gitdir: /nowhere\n")
        (Path(tree) / "new.txt").write_text("mine\n")

        [failed] = await pool.reset(save=True)
        git_file.write_text(linked)

        assert isinstance(failed, FailedTree)
        assert failed.reason.startswith("git rev-parse in ")
        assert (Path(tree) / "new.txt").read_text() == "mine\n"
        assert await pool.listed() == [
            BlockedTree(path=tree, reason="uncommitted changes")
        ]

    @staticmethod
    async def test_a_tree_that_will_not_go_says_so(pool: _Pool):
        tree = await pool.leased(count=1)
        home = Path(tree).parent
        home.chmod(0o500)
        try:
            removed = await pool.reset()
        finally:
            home.chmod(0o700)

        assert removed == [FailedTree(path=tree, reason="it could not be removed")]

    # Git has forgotten the folder, so only the sweep can take it.
    @staticmethod
    async def test_a_folder_git_no_longer_lists_goes_too(pool: _Pool):
        tree = await pool.leased(count=1)
        stray = Path(tree).parent / "2"
        stray.mkdir()
        (stray / "left.txt").write_text("left\n")

        await pool.reset()

        assert not stray.exists()

    @staticmethod
    async def test_with_init_the_pool_is_made_again(pool: _Pool):
        tree = await pool.leased(count=1)
        (Path(tree) / "new.txt").write_text("mine\n")
        pool.tending = replace(pool.asking(init=True), count=1)

        again = await pool.reset()

        assert again == [RemovedTree(path=tree), ParkedTree(path=tree)]
        assert not (Path(tree) / "new.txt").exists()
        assert await pool.lease() == tree

    @staticmethod
    async def test_asked_for_one_tree_only_that_one_is_made_again(pool: _Pool):
        first = await pool.leased()
        second = Path(first).parent / "2"
        (Path(first) / "new.txt").write_text("mine\n")
        (second / "new.txt").write_text("mine\n")
        pool.tending = pool.asking(init=True)
        pool.only(2)

        again = await pool.reset()

        assert again == [RemovedTree(path=str(second)), ParkedTree(path=str(second))]
        assert not (second / "new.txt").exists()
        assert (Path(first) / "new.txt").read_text() == "mine\n"
        assert (Path(first).parent / "1.prepared").is_file()


@pytest.mark.asyncio
class TestList:
    @staticmethod
    async def test_each_tree_is_said_as_it_stands_and_none_is_touched(pool: _Pool):
        first = await pool.leased(count=3)
        home = Path(first).parent
        (home / "2" / "a.txt").write_text("edited\n")
        _git(home / "3", "checkout", "-q", "-b", "feature")
        (home / "3.prepared").unlink()

        listed = await pool.listed(held={first})

        assert listed == [
            HeldTree(path=first),
            BlockedTree(path=str(home / "2"), reason="uncommitted changes"),
            BlockedTree(
                path=str(home / "3"), reason="not set up: run `vekna altar init`"
            ),
        ]
        assert (home / "2" / "a.txt").read_text() == "edited\n"
        assert _git(home / "3", "branch", "--show-current") == "feature"

    @staticmethod
    async def test_a_clean_tree_off_its_parking_branch_is_ready(pool: _Pool):
        tree = await pool.leased(count=1)
        _git(Path(tree), "checkout", "-q", "-b", "feature")

        assert await pool.listed() == [ParkedTree(path=tree)]
        assert _git(Path(tree), "branch", "--show-current") == "feature"

    @staticmethod
    async def test_an_open_merge_is_said(pool: _Pool):
        tree = await pool.leased(count=1)
        work = Path(tree)
        _git(work, "checkout", "-q", "-b", "left")
        (work / "a.txt").write_text("left\n")
        _git(work, "commit", "-q", "-am", "left")
        _git(work, "checkout", "-q", "-b", "right", "main")
        (work / "a.txt").write_text("right\n")
        _git(work, "commit", "-q", "-am", "right")
        assert _conflicts(work, "merge", "left")
        _git(work, "checkout", "-q", "--ours", "a.txt")
        _git(work, "add", "a.txt")

        assert await pool.listed() == [
            BlockedTree(path=tree, reason="a merge in progress")
        ]

    @staticmethod
    async def test_a_tree_that_is_gone_says_why(pool: _Pool):
        tree = await pool.leased(count=1)
        shutil.rmtree(tree)

        [listed] = await pool.listed()

        assert isinstance(listed, BlockedTree)
        assert listed.reason.startswith("git status in ")


@pytest.mark.asyncio
class TestTroubles:
    @staticmethod
    async def test_a_state_root_it_cannot_write_says_why(repo: Path, tmp_path: Path):
        root = tmp_path / "taken"
        root.write_text("")

        with pytest.raises(TreeError, match="no room for worktrees"):
            await _Pool(repo, root).lease()

    @staticmethod
    async def test_a_prepare_log_it_cannot_open_says_why(pool: _Pool):
        tree = await pool.leased(count=1)
        (Path(tree).parent / "2.prepare.log").mkdir()

        _, failed = await pool.init(prepare="true")

        assert isinstance(failed, FailedTree)
        assert "prepare could not run" in failed.reason

    # The exit code and the log's path still say what happened.
    @staticmethod
    async def test_a_prepare_log_that_will_not_read_back_still_says_the_exit(
        pool: _Pool,
    ):
        swaps = "rm ../1.prepare.log && mkdir ../1.prepare.log; exit 4"

        [failed] = await pool.init(count=1, prepare=swaps)

        assert isinstance(failed, FailedTree)
        assert "prepare exited 4 in " in failed.reason


@pytest.mark.asyncio
class TestBranchOf:
    @staticmethod
    async def test_the_checked_out_branch_is_named(repo: Path):
        _git(repo, "switch", "-q", "-c", "feature")

        assert await branch_of(str(repo)) == "feature"

    @staticmethod
    async def test_a_detached_head_has_no_name(repo: Path):
        _git(repo, "switch", "-q", "--detach")

        assert await branch_of(str(repo)) is None

    @staticmethod
    async def test_a_directory_that_is_no_repository_has_no_name(tmp_path: Path):
        assert await branch_of(str(tmp_path)) is None
