import logging
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from vekna.pacts.casts import Casts
from vekna.pacts.circle import CastQueue, Limits, Vigil
from vekna.wire import CastHello, CastStatus, RunRecord

_log = logging.getLogger(__name__)

_TOME_SEPARATOR = ":"
_OPEN = frozenset({"queued", "running"})
# A vigil that has never run is due before any that has.
_NEVER = datetime.min.replace(tzinfo=UTC)


# Casts each due vigil's ritual, the longest overdue first, into room nothing
# else is waiting for. It never leaves a cast waiting in the queue for a slot:
# a vigil that finds no room stays due and is looked at again.
# shortcut: a ritual that needs a worktree waits queued when no tree is free,
# counted against `vigil_processes` while it does; leasing before the cast is
# made is the upgrade.
class Vigils:
    def __init__(
        self,
        *,
        hub: Casts,
        queue: CastQueue,
        limits: Limits,
        alive: Callable[[int], bool],
    ) -> None:
        self._hub = hub
        self._queue = queue
        self._limits = limits
        self._alive = alive

    # `projects` names the repository of each vigil's root, as a hello says it.
    # `records` is the journal: the casts this daemon has not seen, and when
    # each began.
    def tick(
        self,
        *,
        now: datetime,
        vigils: Sequence[Vigil],
        projects: Mapping[str, str],
        records: Sequence[RunRecord],
    ) -> list[CastHello]:
        whens = [
            self._due_at(vigil, project=projects[vigil.project_root], records=records)
            for vigil in vigils
        ]
        due = [at for at, when in enumerate(whens) if when <= now]
        started: list[CastHello] = []
        for vigil in (vigils[at] for at in sorted(due, key=whens.__getitem__)):
            project = projects[vigil.project_root]
            known = list(self._known(records))
            if any(
                status in _OPEN and _same(hello, vigil=vigil, project=project)
                for hello, status in known
            ):
                continue
            kept = sum(
                status in _OPEN and hello.vigil is not None for hello, status in known
            )
            if kept >= self._limits.vigils():
                break
            if not self._queue.has_spare(
                project_root=vigil.project_root, project=project
            ):
                continue
            started.append(self._cast(vigil, project=project, now=now))
        return started

    def _cast(self, vigil: Vigil, *, project: str, now: datetime) -> CastHello:
        hello = CastHello(
            cast_id=uuid4().hex,
            project_root=vigil.project_root,
            project=project,
            ritual=vigil.ritual,
            components=dict(vigil.args),
            started_at=now,
            wired=True,
            vigil=vigil.name,
        )
        self._queue.enqueue(hello)
        _log.info(
            "vigil %s cast %s %s in %s",
            vigil.name,
            vigil.ritual,
            hello.cast_id,
            vigil.project_root,
        )
        return hello

    # Counted from the last cast of the ritual in the project, whoever started
    # it: a cast typed by hand an hour ago is not owed again by the vigil.
    def _due_at(
        self, vigil: Vigil, *, project: str, records: Sequence[RunRecord]
    ) -> datetime:
        began = [
            hello.started_at
            for hello, _ in self._known(records)
            if _same(hello, vigil=vigil, project=project)
        ]
        if not began:
            return _NEVER
        return max(began) + timedelta(seconds=vigil.every)

    # Every cast with how it stands: the hub's word first, then the journal's
    # on the casts the hub has not seen. Of those, one the record leaves
    # running is a cast a stopped daemon left behind, and it still runs only
    # while its process does.
    def _known(
        self, records: Sequence[RunRecord]
    ) -> Iterator[tuple[CastHello, CastStatus]]:
        casts = self._hub.casts
        for view in casts.values():
            yield view.hello, view.status
        for record in records:
            hello = record.hello
            if hello.cast_id in casts:
                continue
            gone = record.status == "running" and not (
                hello.pid is not None and self._alive(hello.pid)
            )
            yield hello, "disconnected" if gone else record.status


# A cast says its ritual with the tome it came from, `cabinet:heal.mine`, and
# a config may name it bare, as it is typed. Only the cast loads the rituals,
# so the daemon cannot resolve the name.
# shortcut: a bare name counts the cast of any tome's ritual of that name, so
# a project with the name in two tomes waits on either; naming the tome in the
# vigil tells them apart.
def _same(hello: CastHello, *, vigil: Vigil, project: str) -> bool:
    bare = hello.ritual.rpartition(_TOME_SEPARATOR)[2]
    return hello.project == project and vigil.ritual in {hello.ritual, bare}
