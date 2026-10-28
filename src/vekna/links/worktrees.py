import asyncio
import hashlib
import secrets
from pathlib import Path

from vekna.pacts.circle import Full, TreeError, Trees
from vekna.wire import PurifiedTree

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
_RESCUE = "vekna/rescue/"
_DETACHED = "detached"


# The pool is whatever git lists under this project's directory in the state
# root: `<root>/<repo>-<hash>/<n>`, each tree parked on `vekna/wt-<n>` while no
# cast holds it. Nothing about it is recorded, so a daemon that restarts reads
# the same pool back. Identified by path, not by branch: a leased tree stands on
# whatever branch its cast checked out.
class GitTrees(Trees):
    def __init__(self, *, root: Path) -> None:
        self._root = root

    async def lease(
        self, *, project_root: str, project: str, held: set[str], count: int
    ) -> str | Full:
        home = await self._home(project)
        pool = await _pool(project_root, home)
        taken = await asyncio.to_thread(_resolved, held)
        blocked: list[str] = []
        for tree in (tree for _, tree in sorted(pool.items()) if tree not in taken):
            # A tree nobody holds and off its parking branch is one a dead cast
            # left; the release that parks it is the check that it is clean.
            if (reason := await self.release(str(tree))) is None:
                return str(tree)
            blocked.append(f"{tree} ({reason})")
        if len(pool) < count:
            number = next(n for n in range(1, count + 1) if n not in pool)
            tree = home / str(number)
            await _git(
                project_root,
                "worktree",
                "add",
                str(tree),
                "-B",
                _branch(number),
                "HEAD",
            )
            return str(tree)
        if holding := frozenset(taken[tree] for tree in pool.values() if tree in taken):
            return Full(held=holding)
        msg = f"every tree is blocked: {', '.join(blocked)}"
        raise TreeError(msg)

    # The marker and the log are written beside the tree, so only a tree of
    # the pool is prepared.
    async def prepare(self, tree: str, command: str | None) -> None:
        number = await self._numbered(tree)
        await _prepared(home=Path(tree).parent, number=number, prepare=command)

    # Parked only once it is clean, because `git checkout` carries local
    # changes across a branch switch whenever they do not conflict. Gitignored
    # files are not dirt: the venv `prepare` built is why a tree is reused.
    # Only a tree of the pool is ever switched: a path from anywhere else is
    # somebody's checkout.
    async def release(self, tree: str) -> str | None:
        try:
            number = await self._numbered(tree)
            if await _git(tree, "status", "--porcelain"):
                return "uncommitted changes"
            git_dir = Path(await _git(tree, "rev-parse", "--absolute-git-dir"))
            if marker := await _in_progress(git_dir):
                return f"a {_IN_PROGRESS[marker]} in progress"
            await _git(tree, "checkout", "--quiet", _branch(number))
        except TreeError as error:
            return str(error)
        return None

    async def purify(
        self, *, project_root: str, project: str, held: set[str], save: bool
    ) -> list[PurifiedTree]:
        pool = await _pool(project_root, await self._home(project))
        taken = await asyncio.to_thread(_resolved, held)
        return [
            (
                PurifiedTree(path=str(tree), outcome="held")
                if tree in taken
                else await self._purified(str(tree), save=save)
            )
            for _, tree in sorted(pool.items())
        ]

    # Saved before anything is thrown away, so a save that fails leaves the
    # tree as it was.
    async def _purified(self, tree: str, *, save: bool) -> PurifiedTree:
        saved: str | None = None
        try:
            if save:
                saved = await _saved(tree)
            await _abandoned(tree)
        except TreeError as error:
            return PurifiedTree(
                path=tree, outcome="failed", saved=saved, reason=str(error)
            )
        if (reason := await self.release(tree)) is not None:
            return PurifiedTree(path=tree, outcome="failed", saved=saved, reason=reason)
        return PurifiedTree(path=tree, outcome="parked", saved=saved)

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


# The marker of the operation left open in `git_dir`, if one is.
async def _in_progress(git_dir: Path) -> str | None:
    for marker in _IN_PROGRESS:
        if await asyncio.to_thread((git_dir / marker).exists):
            return marker
    return None


# Everything uncommitted, untracked files and a half-resolved conflict too, as a
# commit on a branch of its own. Built from plumbing so HEAD never moves: in the
# middle of a rebase or a merge, `checkout` and `commit` would each make it part
# of the operation. `None` when there was nothing to save.
async def _saved(tree: str) -> str | None:
    git_dir = Path(await _git(tree, "rev-parse", "--absolute-git-dir"))
    if not await _git(tree, "status", "--porcelain") and not await _in_progress(
        git_dir
    ):
        return None
    await _git(tree, "add", "--all")
    snapshot = await _git(tree, "write-tree")
    message = f"vekna purify: what {tree} had not committed"
    commit = await _git(tree, "commit-tree", snapshot, "-p", "HEAD", "-m", message)
    name = f"{_RESCUE}{await branch_of(tree) or _DETACHED}-{secrets.token_hex(4)}"
    await _git(tree, "branch", name, commit)
    return name


# Every operation left open aborted, then whatever is not committed thrown away.
# Gitignored files stay: `clean` without `-x` leaves them, and the venv
# `prepare` built is among them.
async def _abandoned(tree: str) -> None:
    git_dir = Path(await _git(tree, "rev-parse", "--absolute-git-dir"))
    for marker, command in _IN_PROGRESS.items():
        if await asyncio.to_thread((git_dir / marker).exists):
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


# Once per tree, not per cast: installing a venv is minutes. A tree whose
# prepare failed has no marker, so the next lease prepares it again rather than
# handing out a tree that only looks ready.
async def _prepared(*, home: Path, number: int, prepare: str | None) -> None:
    marker = home / f"{number}{_PREPARED}"
    if prepare is None or await asyncio.to_thread(marker.exists):
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
