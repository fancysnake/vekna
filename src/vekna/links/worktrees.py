import asyncio
import contextlib
import hashlib
import os
import secrets
import shutil
from collections.abc import Callable
from pathlib import Path

from vekna.pacts.circle import Full, Tending, TreeError, Trees
from vekna.wire import (
    BlockedTree,
    FailedTree,
    HeldTree,
    ParkedTree,
    RemovedTree,
    TendedTree,
)

_PARKING = "vekna/wt-"
_PREPARED = ".prepared"
_PREPARE_LOG = ".prepare.log"
_WORKTREE = "worktree "
# What git leaves in a tree's git dir while an operation is half done. A clean
# status does not rule these out: a conflict resolved and staged reads as clean
# to `--porcelain` while the merge is still open. Each names the git command
# whose `--abort` ends it.
_IN_PROGRESS = {
    "MERGE_HEAD": "merge",
    "CHERRY_PICK_HEAD": "cherry-pick",
    "REVERT_HEAD": "revert",
    "rebase-merge": "rebase",
    "rebase-apply": "rebase",
}
# What `git rev-parse --local-env-vars` lists: each aims git at a repository
# other than the one `cwd` is in. A daemon summoned from a git hook inherits
# them, and `reset --hard` there would wipe somebody's own checkout.
_REPOSITORY_ENV = frozenset(
    {
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_CONFIG",
        "GIT_CONFIG_PARAMETERS",
        "GIT_CONFIG_COUNT",
        "GIT_OBJECT_DIRECTORY",
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_IMPLICIT_WORK_TREE",
        "GIT_GRAFT_FILE",
        "GIT_INDEX_FILE",
        "GIT_NO_REPLACE_OBJECTS",
        "GIT_REPLACE_REF_BASE",
        "GIT_PREFIX",
        "GIT_SHALLOW_FILE",
        "GIT_COMMON_DIR",
    }
)
_RESCUE = "vekna/rescue/"
_DETACHED = "detached"
_HEADS = "refs/heads/"
_HELD = "a running cast holds it"
_NEVER_SET_UP = "not set up: run `vekna altar init`"
_NOT_SET_UP = "no worktree is set up for this project: run `vekna altar init`"


# The pool is whatever git lists under this project's directory in the state
# root: `<root>/<repo>-<hash>/<n>`, each tree parked on `vekna/wt-<n>` while no
# cast holds it. A tree is set up once `<n>.prepared` stands beside it, which
# only the altar writes. Nothing else about the pool is recorded, so a daemon
# that restarts reads the same pool back. Identified by path, not by branch: a
# leased tree stands on whatever branch its cast checked out.
class GitTrees(Trees):
    def __init__(self, *, root: Path) -> None:
        self._root = root

    async def lease(
        self, *, project_root: str, project: str, held: set[str]
    ) -> str | Full:
        home = await self._home(project)
        pool = {
            number: tree
            for number, tree in (await _pool(project_root, home)).items()
            if await asyncio.to_thread(_marker(home, number).exists)
        }
        if not pool:
            raise TreeError(_NOT_SET_UP)
        taken = await asyncio.to_thread(_resolved, held)
        blocked: list[str] = []
        for tree in (tree for _, tree in sorted(pool.items()) if tree not in taken):
            # A tree nobody holds and off its parking branch is one a dead cast
            # left; the release that parks it is the check that it is clean.
            if (reason := await self.release(str(tree))) is None:
                return str(tree)
            blocked.append(f"{tree} ({reason})")
        if holding := frozenset(taken[tree] for tree in pool.values() if tree in taken):
            return Full(held=holding)
        msg = f"every tree is blocked: {', '.join(blocked)}"
        raise TreeError(msg)

    # Parked only once it is clean, because `git checkout` carries local
    # changes across a branch switch whenever they do not conflict. Gitignored
    # files are not dirt: the venv `prepare` built is why a tree is reused.
    # Only a tree of the pool is ever switched: a path from anywhere else is
    # somebody's checkout.
    async def release(self, tree: str) -> str | None:
        try:
            number = await self._numbered(tree)
            if await _git(tree, "status", "--porcelain", "--untracked-files=all"):
                return "uncommitted changes"
            git_dir = Path(await _git(tree, "rev-parse", "--absolute-git-dir"))
            if operations := await _open_operations(git_dir):
                return f"a {_IN_PROGRESS[operations[0]]} in progress"
            await _git(tree, "checkout", "--quiet", _branch(number))
        except TreeError as error:
            return str(error)
        return None

    async def tend(self, tending: Tending, held: set[str]) -> list[TendedTree]:
        asked = tending.asked
        root = asked.project_root
        home = await self._home(tending.project)
        # A listing moves no tree, so a base that is wrong is not its trouble.
        moving = asked.fix or asked.init
        base = await _base(root, tending.base) if moving else ""
        pool = await _pool(root, home)
        taken = await asyncio.to_thread(_resolved, held)
        if (only := asked.tree) is not None:
            if only not in pool:
                msg = f"the pool has no worktree {only}"
                raise TreeError(msg)
            if (named := pool[only]) in taken:
                return [FailedTree(path=str(named), reason=_HELD)]
            pool = {only: named}
        tended: list[TendedTree] = [
            HeldTree(path=str(tree))
            for _, tree in sorted(pool.items())
            if tree in taken
        ]
        free = {number: tree for number, tree in pool.items() if tree not in taken}
        if asked.reset:
            tended += await _reset(
                root=root, home=home, free=free, only=only, save=asked.save
            )
        elif asked.fix:
            tended += [
                await self._fixed(tree, number=number, base=base, tending=tending)
                for number, tree in sorted(free.items())
            ]
        elif not asked.init:
            tended += [
                await _standing(tree, _marker(home, number))
                for number, tree in sorted(free.items())
            ]
        if asked.init:
            done = {
                Path(tree.path) for tree in tended if not isinstance(tree, RemovedTree)
            }
            tended += await _founded(home=home, base=base, done=done, tending=tending)
        return tended

    # Saved before anything is thrown away, so a save that fails leaves the
    # tree as it was. The marker goes before `prepare` runs again, so a tree
    # whose setup failed is not leased as if it were set up.
    async def _fixed(
        self, tree: Path, *, number: int, base: str, tending: Tending
    ) -> TendedTree:
        path = str(tree)
        saved: str | None = None
        try:
            git_dir = Path(await _git(path, "rev-parse", "--absolute-git-dir"))
            if tending.asked.save:
                saved = await _saved(path, git_dir)
            await _abandoned(path, git_dir)
        except TreeError as error:
            return FailedTree(path=path, saved=saved, reason=str(error))
        if (reason := await self.release(path)) is not None:
            return FailedTree(path=path, saved=saved, reason=reason)
        marker = _marker(tree.parent, number)
        try:
            await _git(path, "reset", "--hard", "--quiet", base)
            await asyncio.to_thread(marker.unlink, missing_ok=True)
            await _prepared(home=tree.parent, number=number, prepare=tending.prepare)
        except (TreeError, OSError) as error:
            return FailedTree(path=path, saved=saved, reason=str(error))
        return ParkedTree(path=path, saved=saved)

    async def _home(self, project: str) -> Path:
        try:
            return await asyncio.to_thread(_home, self._root, project)
        except OSError as error:
            msg = f"no room for worktrees under {self._root}: {error}"
            raise TreeError(msg) from error

    async def _numbered(self, tree: str) -> int:
        resolved = await asyncio.to_thread(Path(tree).resolve)
        root = await asyncio.to_thread(self._root.resolve)
        if (number := _number(resolved, root)) is None:
            msg = f"{tree} is not a tree of the pool under {self._root}"
            raise TreeError(msg)
        return number


def _branch(number: int) -> str:
    return f"{_PARKING}{number}"


# How a tree nobody holds stands, by what a lease would find and without the
# checkout a lease would do: asking changes nothing.
async def _standing(tree: Path, marker: Path) -> TendedTree:
    path = str(tree)
    if not await asyncio.to_thread(marker.exists):
        return BlockedTree(path=path, reason=_NEVER_SET_UP)
    try:
        if await _git(path, "status", "--porcelain", "--untracked-files=all"):
            return BlockedTree(path=path, reason="uncommitted changes")
        git_dir = Path(await _git(path, "rev-parse", "--absolute-git-dir"))
    except TreeError as error:
        return BlockedTree(path=path, reason=str(error))
    if operations := await _open_operations(git_dir):
        return BlockedTree(
            path=path, reason=f"a {_IN_PROGRESS[operations[0]]} in progress"
        )
    return ParkedTree(path=path)


def _marker(home: Path, number: int) -> Path:
    return home / f"{number}{_PREPARED}"


# The commit every tree is made on and moved to, read in the tree the altar was
# asked from: `HEAD` in a pooled tree would be that tree's own.
async def _base(project_root: str, base: str | None) -> str:
    name = base or "HEAD"
    try:
        return await _git(project_root, "rev-parse", "--verify", f"{name}^{{commit}}")
    except TreeError as error:
        msg = f"the base {name!r} names no commit: {error}"
        raise TreeError(msg) from error


# Every tree of `free` gone, and with it whatever stands beside it: the marker
# and the log. Asked for every tree, a folder git no longer lists goes too. A
# tree whose work could not be saved is left as it was. Git is asked first
# because it unregisters what it removes; the sweep takes what git would not.
async def _reset(
    *, root: str, home: Path, free: dict[int, Path], only: int | None, save: bool
) -> list[TendedTree]:
    saved: dict[int, str | None] = {}
    failed: dict[int, TendedTree] = {}
    for number, tree in sorted(free.items()):
        try:
            saved[number] = await _rescued(str(tree)) if save else None
        except TreeError as error:
            failed[number] = FailedTree(path=str(tree), reason=str(error))
            continue
        with contextlib.suppress(TreeError):
            await _git(root, "worktree", "remove", "--force", "--force", str(tree))
    spared = failed.keys() | await _held_numbers(root, home, free)
    await asyncio.to_thread(
        _swept, home, lambda number: number not in spared and only in {None, number}
    )
    await _git(root, "worktree", "prune")
    for number, tree in free.items():
        if number not in failed and await asyncio.to_thread(tree.exists):
            failed[number] = FailedTree(
                path=str(tree), saved=saved[number], reason="it could not be removed"
            )
    return [
        failed.get(number, RemovedTree(path=str(tree), saved=saved.get(number)))
        for number, tree in sorted(free.items())
    ]


# The numbers of the pool's trees that are not `free`: a cast holds each.
async def _held_numbers(root: str, home: Path, free: dict[int, Path]) -> set[int]:
    return (await _pool(root, home)).keys() - free.keys()


async def _rescued(tree: str) -> str | None:
    return await _saved(tree, Path(await _git(tree, "rev-parse", "--absolute-git-dir")))


def _swept(home: Path, going: Callable[[int], bool]) -> None:
    for entry in home.iterdir():
        number = entry.name.partition(".")[0]
        if not number.isdecimal() or not going(int(number)):
            continue
        # What will not go is said by the caller, which looks for the tree after.
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            with contextlib.suppress(OSError):
                entry.unlink()


# Each tree up to `count` that this run has not already said something of: made
# when the pool lacks it, set up when it never was, and said ready either way.
async def _founded(
    *, home: Path, base: str, done: set[Path], tending: Tending
) -> list[TendedTree]:
    root, only = tending.asked.project_root, tending.asked.tree
    pool = await _pool(root, home)
    founded: list[TendedTree] = []
    for number in range(1, tending.count + 1) if only is None else [only]:
        if (tree := pool.get(number, home / str(number))) in done:
            continue
        try:
            if number not in pool:
                await _git(
                    root, "worktree", "add", str(tree), "-B", _branch(number), base
                )
            await _prepared(home=home, number=number, prepare=tending.prepare)
        except (TreeError, OSError) as error:
            founded.append(FailedTree(path=str(tree), reason=str(error)))
        else:
            founded.append(ParkedTree(path=str(tree)))
    return founded


# The marker of every operation left open in `git_dir`.
async def _open_operations(git_dir: Path) -> list[str]:
    return [
        marker
        for marker in _IN_PROGRESS
        if await asyncio.to_thread((git_dir / marker).exists)
    ]


# Everything uncommitted, untracked files and a half-resolved conflict too, as a
# commit on a branch of its own. Built from plumbing so HEAD never moves: in the
# middle of a rebase or a merge, `checkout` and `commit` would each make it part
# of the operation. `None` when there was nothing to save.
async def _saved(tree: str, git_dir: Path) -> str | None:
    if not await _git(
        tree, "status", "--porcelain", "--untracked-files=all"
    ) and not await _open_operations(git_dir):
        return None
    await _git(tree, "add", "--all")
    snapshot = await _git(tree, "write-tree")
    message = f"vekna altar: what {tree} had not committed"
    commit = await _git(tree, "commit-tree", snapshot, "-p", "HEAD", "-m", message)
    branch = await branch_of(tree) or await _rebasing(git_dir) or _DETACHED
    name = f"{_RESCUE}{branch}-{secrets.token_hex(4)}"
    await _git(tree, "branch", name, commit)
    return name


# A rebase detaches HEAD; the branch it is rebasing is in its own git dir.
async def _rebasing(git_dir: Path) -> str | None:
    for marker in ("rebase-merge", "rebase-apply"):
        try:
            head = await asyncio.to_thread((git_dir / marker / "head-name").read_text)
        except OSError:
            continue
        # A detached head being rebased reads `detached HEAD`.
        if (ref := head.strip()).startswith(_HEADS):
            return ref.removeprefix(_HEADS)
    return None


# Every operation left open aborted, then whatever is not committed thrown away.
# A rebase leaves one of two markers, so each command aborts once. Gitignored
# files stay: `clean` without `-x` leaves them, and the venv `prepare` built is
# among them.
async def _abandoned(tree: str, git_dir: Path) -> None:
    operations = await _open_operations(git_dir)
    for command in {_IN_PROGRESS[marker]: None for marker in operations}:
        await _git(tree, command, "--abort")
    await _git(tree, "reset", "--hard", "--quiet")
    await _git(tree, "clean", "-d", "--force", "--quiet")


# The repository's directory name, for whoever lists the state root, and a hash
# of its common dir, because two clones may share a name.
def _home(root: Path, project: str) -> Path:
    digest = hashlib.sha256(project.encode()).hexdigest()[:8]
    home = root / f"{Path(project).parent.name}-{digest}"
    home.mkdir(parents=True, exist_ok=True)
    return home.resolve()


# Each path as the caller said it, by where it resolves to.
def _resolved(paths: set[str]) -> dict[Path, str]:
    return {Path(path).resolve(): path for path in paths}


async def _pool(project_root: str, home: Path) -> dict[int, Path]:
    listed = await _git(project_root, "worktree", "list", "--porcelain")
    return await asyncio.to_thread(_parsed, listed, home)


def _parsed(listed: str, home: Path) -> dict[int, Path]:
    pool: dict[int, Path] = {}
    for line in listed.splitlines():
        if not line.startswith(_WORKTREE):
            continue
        tree = Path(line.removeprefix(_WORKTREE)).resolve()
        if tree.parent == home and (number := _number(tree, home.parent)) is not None:
            pool[number] = tree
    return pool


# `<root>/<home>/<n>`, both resolved; `None` for any other path.
def _number(tree: Path, root: Path) -> int | None:
    if tree.parent.parent != root or not tree.name.isdecimal():
        return None
    return int(tree.name)


# Once per tree, until a fix asks again: installing a venv is minutes. A tree
# whose prepare failed has no marker, so no lease hands out a tree that only
# looks ready. With no `prepare` the marker alone says the tree is set up.
async def _prepared(*, home: Path, number: int, prepare: str | None) -> None:
    marker = _marker(home, number)
    if await asyncio.to_thread(marker.exists):
        return
    if prepare is None:
        await asyncio.to_thread(marker.touch)
        return
    log = home / f"{number}{_PREPARE_LOG}"
    try:
        with log.open("wb") as out:
            process = await asyncio.create_subprocess_shell(
                prepare,
                cwd=home / str(number),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=out,
                stderr=asyncio.subprocess.STDOUT,
            )
            code = await process.wait()
    except OSError as error:
        msg = f"prepare could not run in {home / str(number)}: {error}"
        raise TreeError(msg) from error
    if code != 0:
        said = await asyncio.to_thread(_tail, log)
        msg = f"prepare exited {code} in {home / str(number)}: {said} (see {log})"
        raise TreeError(msg)
    await asyncio.to_thread(marker.touch)


# The log was just written by this process, so a read that fails is as good as
# an empty one: the exit code and the log's path still say what happened.
def _tail(log: Path) -> str:
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return lines[-1] if lines else ""


async def _git(cwd: str, *args: str) -> str:
    try:
        git = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=cwd,
            env={k: v for k, v in os.environ.items() if k not in _REPOSITORY_ENV},
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as error:
        msg = f"git {args[0]} in {cwd}: {error}"
        raise TreeError(msg) from error
    out, err = await git.communicate()
    if git.returncode != 0:
        msg = f"git {args[0]} in {cwd}: {err.decode(errors='replace').strip()}"
        raise TreeError(msg)
    return out.decode(errors="replace").strip()


# The branch a tree has checked out, read when asked because a cast can switch
# it under its own feet — `gh pr checkout` does. None where git has no name for
# it: a detached head, a directory that is no repository or is gone.
async def branch_of(path: str) -> str | None:
    try:
        branch = await _git(path, "rev-parse", "--abbrev-ref", "HEAD")
    except TreeError:
        return None
    return None if branch == "HEAD" else branch
