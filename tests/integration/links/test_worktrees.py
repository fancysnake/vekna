import shutil
import subprocess
from pathlib import Path

import pytest

from vekna.links.worktrees import GitTrees
from vekna.pacts.circle import Full, TreeError


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _conflicts(cwd: Path, branch: str) -> bool:
    merged = subprocess.run(
        ["git", "merge", "-q", branch], cwd=cwd, capture_output=True, check=False
    )
    return merged.returncode != 0


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

    async def lease(
        self,
        *,
        held: set[str] | None = None,
        count: int = 2,
        prepare: str | None = None,
    ) -> str | None:
        found = await self.trees.lease(
            project_root=str(self.repo),
            project=str(self.repo / ".git"),
            held=held or set(),
            count=count,
        )
        if isinstance(found, Full):
            self.full = found
            return None
        await self.trees.prepare(found, prepare)
        return found


@pytest.fixture(name="pool")
def _pool(repo: Path, tmp_path: Path) -> _Pool:
    return _Pool(repo, tmp_path / "state" / "worktrees")


@pytest.mark.asyncio
class TestLease:
    @staticmethod
    async def test_a_new_tree_is_made_on_its_parking_branch_and_prepared(pool: _Pool):
        tree = await pool.lease(prepare="mkdir venv && echo ready > venv/ok")

        assert tree is not None
        assert Path(tree).name == "1"
        assert Path(tree).parent.name.startswith("repo-")
        assert _git(Path(tree), "branch", "--show-current") == "vekna/wt-1"
        assert (Path(tree) / "venv" / "ok").read_text() == "ready\n"

    @staticmethod
    async def test_a_parked_tree_is_reused_and_not_prepared_again(pool: _Pool):
        first = await pool.lease(prepare="mkdir -p venv && echo x >> venv/runs")
        assert first is not None

        again = await pool.lease(prepare="mkdir -p venv && echo x >> venv/runs")

        assert again == first
        assert (Path(first) / "venv" / "runs").read_text() == "x\n"

    @staticmethod
    async def test_a_held_tree_is_passed_over_for_a_new_one(pool: _Pool):
        first = await pool.lease()
        assert first is not None

        second = await pool.lease(held={first})

        assert second is not None
        assert Path(second).name == "2"

    @staticmethod
    async def test_a_full_pool_leases_nothing(pool: _Pool):
        first = await pool.lease(count=1)
        assert first is not None

        assert await pool.lease(held={first}, count=1) is None
        assert pool.full == Full(held=frozenset({first}))

    # Said as the caller said them, and only those that stand in the pool.
    @staticmethod
    async def test_a_full_pool_says_which_held_trees_fill_it(pool: _Pool):
        first = await pool.lease(count=2)
        assert first is not None
        second = await pool.lease(held={first}, count=2)
        assert second is not None
        unresolved = f"{Path(second).parent}/../{Path(second).parent.name}/2"

        assert await pool.lease(held={first, unresolved, "/elsewhere"}) is None
        assert pool.full == Full(held=frozenset({first, unresolved}))

    # A dead cast left its tree on its own branch; the lease is what parks it.
    @staticmethod
    async def test_a_clean_tree_left_on_another_branch_is_parked_and_leased(
        pool: _Pool,
    ):
        tree = await pool.lease()
        assert tree is not None
        _git(Path(tree), "checkout", "-q", "-b", "feature")

        assert await pool.lease() == tree
        assert _git(Path(tree), "branch", "--show-current") == "vekna/wt-1"

    @staticmethod
    async def test_a_dirty_leftover_is_skipped_and_left_as_it_is(pool: _Pool):
        tree = await pool.lease(count=2)
        assert tree is not None
        held = await pool.lease(held={tree}, count=2)
        assert held is not None
        _git(Path(tree), "checkout", "-q", "-b", "feature")
        (Path(tree) / "a.txt").write_text("edited\n")

        assert await pool.lease(held={held}, count=2) is None
        assert _git(Path(tree), "branch", "--show-current") == "feature"
        assert (Path(tree) / "a.txt").read_text() == "edited\n"

    # No cast holds a tree, so none is going to free one.
    @staticmethod
    async def test_every_tree_blocked_and_none_held_says_which(pool: _Pool):
        tree = await pool.lease(count=1)
        assert tree is not None
        (Path(tree) / "a.txt").write_text("edited\n")

        with pytest.raises(TreeError, match=r"every tree is blocked: .*/1 \(unc"):
            await pool.lease(count=1)

    # No marker, so the next lease prepares it again rather than handing out a
    # tree that only looks ready.
    @staticmethod
    async def test_a_failed_prepare_says_why_and_runs_again_next_time(pool: _Pool):
        with pytest.raises(TreeError, match=r"prepare exited 3 .*: broken"):
            await pool.lease(prepare="echo broken; exit 3")

        tree = await pool.lease(prepare="mkdir venv && touch venv/prepared")

        assert tree is not None
        assert (Path(tree) / "venv" / "prepared").is_file()

    @staticmethod
    async def test_a_directory_outside_git_cannot_hold_a_pool(tmp_path: Path):
        plain = tmp_path / "plain"
        plain.mkdir()
        pool = _Pool(plain, tmp_path / "state")

        with pytest.raises(TreeError, match="git worktree"):
            await pool.lease()


@pytest.mark.asyncio
class TestRelease:
    @staticmethod
    async def test_a_clean_tree_goes_back_to_its_parking_branch(pool: _Pool):
        tree = await pool.lease()
        assert tree is not None
        _git(Path(tree), "checkout", "-q", "-b", "feature")
        (Path(tree) / "venv").mkdir()

        assert await pool.trees.release(tree) is None
        assert _git(Path(tree), "branch", "--show-current") == "vekna/wt-1"

    @staticmethod
    async def test_untracked_work_blocks_it(pool: _Pool):
        tree = await pool.lease()
        assert tree is not None
        (Path(tree) / "new.txt").write_text("mine\n")

        assert await pool.trees.release(tree) == "uncommitted changes"

    # Resolved to what HEAD already had, it reads clean to `--porcelain`, and
    # the merge is still open.
    @staticmethod
    async def test_an_open_merge_blocks_it(pool: _Pool):
        tree = await pool.lease()
        assert tree is not None
        work = Path(tree)
        _git(work, "checkout", "-q", "-b", "left")
        (work / "a.txt").write_text("left\n")
        _git(work, "commit", "-q", "-am", "left")
        _git(work, "checkout", "-q", "-b", "right", "main")
        (work / "a.txt").write_text("right\n")
        _git(work, "commit", "-q", "-am", "right")
        assert _conflicts(work, "left")
        _git(work, "checkout", "-q", "--ours", "a.txt")
        _git(work, "add", "a.txt")

        assert await pool.trees.release(tree) == "a merge in progress"

    @staticmethod
    async def test_a_tree_that_is_gone_says_why(pool: _Pool):
        tree = await pool.lease()
        assert tree is not None
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
        tree = await pool.lease()
        assert tree is not None
        odd = Path(tree).parent / "notes"
        odd.mkdir()

        reason = await pool.trees.release(str(odd))

        assert reason is not None
        assert "is not a tree of the pool" in reason

    @staticmethod
    async def test_a_checkout_outside_the_pool_is_never_prepared(
        pool: _Pool, repo: Path
    ):
        with pytest.raises(TreeError, match="is not a tree of the pool"):
            await pool.trees.prepare(str(repo / "1"), "touch prepared")

        assert not (repo / "1.prepared").exists()


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
        tree = await pool.lease()
        assert tree is not None
        (Path(tree).parent / "1.prepare.log").mkdir()

        with pytest.raises(TreeError, match="prepare could not run"):
            await pool.lease(prepare="true")

    # The exit code and the log's path still say what happened.
    @staticmethod
    async def test_a_prepare_log_that_will_not_read_back_still_says_the_exit(
        pool: _Pool,
    ):
        swaps = "rm ../1.prepare.log && mkdir ../1.prepare.log; exit 4"

        with pytest.raises(TreeError, match="prepare exited 4 in "):
            await pool.lease(prepare=swaps)
