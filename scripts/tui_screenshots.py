# The screenshots of docs/tui.md: the window over made-up casts, one SVG per
# screen. Run it from the repository root after a version bump or a change to
# what the window draws, as `mise exec -- python -m scripts.tui_screenshots`.
# `mise exec -- poetry install` before it, after a bump: that is what makes
# `VERSION` the one in pyproject.toml. A clock a running cast shows is read off
# the wall, so two runs differ by seconds.
import asyncio
import sys
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import JsonValue
from textual.pilot import Pilot
from textual.widgets import Tree
from textual.widgets.tree import TreeNode

from vekna.gates.cli.tui import Opened, ToDaemon, VeknaApp
from vekna.mills.hub import Hub
from vekna.wire import (
    VERSION,
    CastGoodbye,
    CastHello,
    CastRefused,
    CastSeen,
    DecideRequested,
    RiteDelta,
    RiteFinished,
    RiteStarted,
    VigilsRequested,
    WireMessage,
)

_ASSETS = Path(__file__).resolve().parent.parent / "docs" / "assets"
_SIZE = (120, 24)
# Longer than the window waits before it fits its first tree.
_DRAWN = 2.5
_PAINTED = 0.4

_SHOP = str(Path.home() / "shop")
_BLOG = str(Path.home() / "blog")
_BRANCHES = {_SHOP: "fix-discount-rounding", _BLOG: "main"}

_WATCHING = "7be02d41"
_GAVE_UP = "c04d5b6e"
_ASKING = "a1c9e4f2"
_OLD_FAIL = "5e7a10c3"
_BLOGGING = "e8f1a2b3"

_CHECKS = """\
$ gh pr checks 409 --watch
Refreshing checks status every 10 seconds.

lint        pass      24s
unit        pass    1m41s
integration pending
build       pending

lint        pass      24s
unit        pass    1m41s
integration pass    4m02s
build       pending
"""
_AHEAD = """\
1 commit ahead of origin/fix-discount-rounding
  3e1f0aa fix: round the discount once, on the total
"""
_RED = (
    "CI red after 3 repairs: test_refund_webhook times out on the runner and"
    " passes here. Last run: https://github.com/dev/shop/actions/runs/7781"
)
_COVERAGE = """\
blog/feeds.py: 61% covered, 14 lines missing
Writing tests/test_feeds.py::test_atom_feed_escapes_titles
"""


# One made-up cast, said to the hub the way a cast says itself. Every time is
# seconds before `now`: `at` when a rite began, `took` how long it ran.
class _Cast:
    def __init__(self, *, hub: Hub, cast_id: str, now: datetime) -> None:
        self._hub = hub
        self._id = cast_id
        self._now = now

    def began(
        self, *, ritual: str, ago: int, root: str = _SHOP, **flags: JsonValue
    ) -> None:
        self._hub.apply(
            CastHello(
                cast_id=self._id,
                project_root=root,
                project=f"{root}/.git",
                ritual=ritual,
                components=flags,
                started_at=self._now - timedelta(seconds=ago),
                wired=True,
            )
        )

    def rite(
        self,
        name: str,
        *,
        at: int,
        took: int | None = None,
        under: str | None = None,
        error: str | None = None,
    ) -> None:
        started = self._now - timedelta(seconds=at)
        self._hub.apply(
            RiteStarted(
                cast_id=self._id,
                rite_id=name,
                parent_id=under,
                name=name,
                category="step" if under is None else "medium",
                started_at=started,
            )
        )
        if took is not None:
            self._hub.apply(
                RiteFinished(
                    cast_id=self._id,
                    rite_id=name,
                    status="ok" if error is None else "error",
                    finished_at=started + timedelta(seconds=took),
                    error=error,
                )
            )

    def said(self, rite: str, text: str) -> None:
        self._hub.apply(RiteDelta(cast_id=self._id, rite_id=rite, delta=text))

    def asks(self, rite: str, prompt: str) -> None:
        self._hub.apply(
            DecideRequested(
                cast_id=self._id,
                rite_id=rite,
                request_id="q1",
                prompt=prompt,
                options=["yes", "no"],
            )
        )

    def ended(self, detail: str | None = None) -> None:
        self._hub.apply(
            CastGoodbye(
                cast_id=self._id,
                status="ok" if detail is None else "error",
                detail=detail,
            )
        )


def _shop_now(hub: Hub, now: datetime) -> None:
    watching = _Cast(hub=hub, cast_id=_WATCHING, now=now)
    watching.began(ritual="ci_watch", ago=373, pr=409)
    watching.rite("watch", at=373)
    watching.rite("shell", at=372, under="watch")
    watching.said("shell", _CHECKS)

    gave_up = _Cast(hub=hub, cast_id=_GAVE_UP, now=now)
    gave_up.began(ritual="ci_watch", ago=3120, pr=398)
    gave_up.rite("watch", at=3120, took=250)
    gave_up.rite("repair_ci", at=2870, took=300)
    gave_up.rite("coding", at=2869, took=298, under="repair_ci")
    gave_up.rite("gave_up", at=2570, took=2, error=_RED)
    gave_up.said(
        "gave_up", "3 repairs spent, CI still red\nleaving the branch as it is\n"
    )
    gave_up.ended(_RED)

    asking = _Cast(hub=hub, cast_id=_ASKING, now=now)
    asking.began(ritual="pr_fix", ago=182, pr=412)
    asking.rite("look", at=182, took=9)
    asking.rite("shell", at=181, took=8, under="look")
    asking.rite("repair", at=173, took=141)
    asking.rite("coding", at=172, took=139, under="repair")
    asking.rite("push", at=31)
    asking.said("push", _AHEAD)
    asking.asks("push", "Push fix-discount-rounding?")

    swept = _Cast(hub=hub, cast_id="3f9a2b11", now=now)
    swept.began(ritual="sweep", ago=7500)
    swept.rite("sweep", at=7500, took=95)
    swept.ended()


# Casts that ended more than a day ago, which is where the history view begins.
def _shop_before(hub: Hub, now: datetime) -> None:
    day = 86400
    for cast_id, ritual, ago, pr in (
        ("91bb0c4d", "merge_ready", day + 3 * 3600, 401),
        ("dd44ee55", "pr_fix", day + 7 * 3600, 399),
        ("0b3c9d8e", "merge_ready", 2 * day + 5 * 3600, 392),
    ):
        ended = _Cast(hub=hub, cast_id=cast_id, now=now)
        ended.began(ritual=ritual, ago=ago, pr=pr)
        ended.rite("look", at=ago, took=140)
        ended.ended()

    failed = _Cast(hub=hub, cast_id=_OLD_FAIL, now=now)
    failed.began(ritual="ci_watch", ago=2 * day + 2 * 3600, pr=395)
    failed.rite("look", at=2 * day + 2 * 3600, took=320, error="CI red after 3 repairs")
    failed.said("look", "PR #395\n")
    failed.ended("CI red after 3 repairs")


def _blog(hub: Hub, now: datetime) -> None:
    blogging = _Cast(hub=hub, cast_id=_BLOGGING, now=now)
    blogging.began(ritual="write_tests", ago=104, root=_BLOG, path="blog/feeds.py")
    blogging.rite("measure", at=104, took=12)
    blogging.rite("write_tests", at=92)
    blogging.rite("coding", at=91, under="write_tests")
    blogging.said("coding", _COVERAGE)


def _window() -> VeknaApp:
    hub, now = Hub(), datetime.now(UTC)
    _shop_before(hub, now)
    _shop_now(hub, now)
    _blog(hub, now)
    sent: list[WireMessage] = []

    async def mark(request: CastSeen) -> str | None:
        await asyncio.sleep(0)
        reply = hub.mark(request)
        return reply.reason if isinstance(reply, CastRefused) else None

    async def vigils(asked: VigilsRequested) -> bool | None:
        await asyncio.sleep(0)
        return hub.vigils(asked).paused

    async def branch_of(root: str) -> str | None:
        await asyncio.sleep(0)
        return _BRANCHES.get(root)

    return VeknaApp(
        casts=hub,
        opened=Opened(
            project=f"{_SHOP}/.git",
            root=_SHOP,
            history_after=timedelta(days=1),
            title=f"vekna {VERSION}",
            fit=True,
        ),
        daemon=ToDaemon(send=sent.append, mark=mark, vigils=vigils),
        branch_of=branch_of,
    )


def _lines(app: VeknaApp) -> list[TreeNode[str]]:
    tree: Tree[str] = app.query_one("#contents", Tree)
    found: list[TreeNode[str]] = []

    def walk(node: TreeNode[str]) -> None:
        for child in node.children:
            found.append(child)
            walk(child)

    walk(tree.root)
    return found


# The cursor on the first line whose key starts with `key`; a line that is not
# drawn is a scene written for a tree the window no longer draws.
async def _to(pilot: Pilot[None], key: str) -> None:
    app = pilot.app
    if not isinstance(app, VeknaApp):
        raise TypeError(app)
    keys = [node.data or "" for node in _lines(app)]
    for node in _lines(app):
        if (node.data or "").startswith(key):
            app.query_one("#contents", Tree).move_cursor(node)
            await pilot.pause(_PAINTED)
            return
    message = f"no line {key!r} among {keys}"
    raise LookupError(message)


async def _overview(pilot: Pilot[None]) -> None:
    await _to(pilot, f"c:{_WATCHING}")


async def _asks(pilot: Pilot[None]) -> None:
    await pilot.press("w")


async def _takeover(pilot: Pilot[None]) -> None:
    await pilot.press("w", "t")
    await pilot.pause(_PAINTED)
    await pilot.press(*"yes")


async def _rites(pilot: Pilot[None]) -> None:
    await _to(pilot, f"c:{_GAVE_UP}")
    await pilot.press("space")
    await pilot.pause(_PAINTED)
    await _to(pilot, f"t:{_GAVE_UP}:gave_up")


async def _fold(pilot: Pilot[None]) -> None:
    shop = f"{_SHOP}/.git"
    for line in (f"f:p:{shop}", f"r:{shop}:pr_fix", f"r:{shop}:ci_watch"):
        await _to(pilot, line)
        await pilot.press("space")
        await pilot.pause(_PAINTED)


async def _history(pilot: Pilot[None]) -> None:
    await pilot.press("H")
    await pilot.pause(_PAINTED)
    await _to(pilot, f"c:{_OLD_FAIL}")


async def _command(pilot: Pilot[None]) -> None:
    await _to(pilot, f"c:{_WATCHING}")
    await pilot.press("c", *"pr_fix", "space", *"--pr", "space", *"415")


async def _every(pilot: Pilot[None]) -> None:
    await pilot.press("g")
    await pilot.pause(_DRAWN)
    await _to(pilot, f"c:{_BLOGGING}")


_SCENES: dict[str, Callable[[Pilot[None]], Awaitable[None]]] = {
    "overview": _overview,
    "asks": _asks,
    "takeover": _takeover,
    "rites": _rites,
    "fold": _fold,
    "history": _history,
    "command": _command,
    "every": _every,
}


async def _shoot(name: str, scene: Callable[[Pilot[None]], Awaitable[None]]) -> None:
    app = _window()
    async with app.run_test(size=_SIZE) as pilot:
        await pilot.pause(_DRAWN)
        await scene(pilot)
        await pilot.pause(_PAINTED)
        drawn = app.export_screenshot()
    # The exporter's template leaves a line of spaces, which the whitespace
    # check refuses.
    lines = (line.rstrip() for line in drawn.splitlines())
    (_ASSETS / f"tui-{name}.svg").write_text("\n".join(lines) + "\n", encoding="utf-8")
    sys.stdout.write(f"wrote docs/assets/tui-{name}.svg\n")


async def _main() -> None:
    for name, scene in _SCENES.items():
        await _shoot(name, scene)


if __name__ == "__main__":
    asyncio.run(_main())
