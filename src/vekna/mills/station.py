from datetime import UTC, datetime

from vekna.wire import CastRefused, CastRequested, LichStatus

# What a bare prompt is called on the wire and on screen. `vekna cast --prompt`
# has no ritual name, and "casting None for four minutes" is not a status line.
PROMPT = "prompt"
_PROMPT_FLAGS = frozenset({"-p", "--prompt"})


def _now() -> datetime:
    return datetime.now(tz=UTC)


# One lich's own state, and the rule that makes it a station rather than a queue:
# one cast, never two. A second is refused rather than queued — nothing queued
# means no backlog to reason about and nothing silently lost when the process
# dies. Pure, so the rule is tested without a socket or a subprocess.
class Station:
    def __init__(self, *, name: str, root: str) -> None:
        self.name = name
        self.root = root
        self._ritual: str | None = None
        self._cast_id: str | None = None
        self._since: datetime | None = None

    @property
    def idle(self) -> bool:
        return self._ritual is None

    # Why this request cannot be taken, or None while the slot is free. The
    # refusal carries what runs and since when; the sentence is the surface's,
    # because a channel with buttons will not word it the way a terminal does.
    def refusal(self, message: CastRequested) -> CastRefused | None:
        del message
        if self._ritual is None or self._since is None:
            return None
        return CastRefused(lich=self.name, ritual=self._ritual, since=self._since)

    # The slot is taken by the request, not by the process: the cast has its own
    # id and says it over its own connection, and this has to be able to refuse
    # a second `cast` before any of that has happened.
    def began(
        self, message: CastRequested, *, at: datetime | None = None
    ) -> LichStatus:
        self._ritual = ritual_of(message.argv)
        self._since = at if at is not None else _now()
        return self.status()

    # A cast the lich spawned says which id it took, and a surface wanting to
    # look at it needs that rather than the ritual's name.
    def is_running(self, cast_id: str) -> LichStatus:
        self._cast_id = cast_id
        return self.status()

    def ended(self) -> LichStatus:
        self._ritual = None
        self._cast_id = None
        self._since = None
        return self.status()

    def status(self) -> LichStatus:
        return LichStatus(
            lich=self.name,
            ritual=self._ritual,
            cast_id=self._cast_id,
            since=self._since,
        )


# What to call what is about to run. The first argument is the ritual, unless it
# is the prompt flag — in which case there is no ritual and saying so is better
# than showing a flag where a name goes.
def ritual_of(argv: list[str]) -> str:
    if not argv:
        return PROMPT
    first = argv[0].partition("=")[0]
    return PROMPT if first in _PROMPT_FLAGS else argv[0]
