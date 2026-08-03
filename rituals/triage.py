# triage — read an issue or a PR, and decide what it deserves.

import shlex
from typing import Literal

from pydantic import BaseModel

from vekna.folio.coding import CodingOpts, coding
from vekna.folio.coding_claude import ClaudeOptions
from vekna.folio.flow import decide
from vekna.folio.shell import shell
from vekna.lexicon import RitualError, Transition, Url, done, goto, ritual, step

from .prompts import ACT_ON, END_ISSUE, FILE_IT, READ_ISSUE


class Triage(BaseModel):
    link: Url


class Fetched(BaseModel):
    link: str
    body: str


class Reading(BaseModel):
    headline: str
    asks: str
    touches: str
    size: Literal["small", "large", "unclear"]


class Verdict(BaseModel):
    link: str
    reading: Reading


Took = Literal["fix", "file", "ignore"]

# Named as a constant, and typed: `decide` answers with the type it was offered,
# so this is what carries the literal through to `Triaged` rather than a `str`
# the step would have to check for itself.
_TOOK: tuple[Took, ...] = ("fix", "file", "ignore")


class Triaged(BaseModel):
    link: str
    reading: Reading
    took: Took


# `gh`, not an agent holding a fetch tool: it reads private repositories, it
# returns JSON rather than HTML, and fetching needs no judgement — so it belongs
# in a shell, where it is deterministic and costs nothing.
_FIELDS = "title,body,state,author,url"


def _gh_view(link: Url) -> str:
    quoted = shlex.quote(str(link))
    path = link.path or ""
    if "/pull/" in path:
        return f"gh pr view {quoted} --json {_FIELDS}"
    if "/issues/" in path:
        return f"gh issue view {quoted} --json {_FIELDS}"
    msg = f"not a GitHub issue or pull request URL: {link}"
    raise RitualError(msg)


@ritual("triage")
async def triage(components: Triage) -> Transition:
    return goto(read_link, components)


@step
async def read_link(request: Triage) -> Transition:
    result = await shell(_gh_view(request.link), stream=False)
    if result.exit_code:
        msg = f"gh could not read {request.link}: {result.stderr.strip()}"
        raise RitualError(msg)
    return goto(size_up, Fetched(link=str(request.link), body=result.stdout))


@step
async def size_up(fetched: Fetched) -> Transition:
    # Read-only, and it does read: the agent judges what the issue touches by
    # opening the code, not by guessing from the title.
    reading = await coding(
        f"{READ_ISSUE}{fetched.body}{END_ISSUE}",
        output=Reading,
        opts=CodingOpts(
            focus_options=ClaudeOptions(
                permission_mode="dontAsk",
                allowed_tools=["Read", "Grep", "Glob"],
                max_turns=8,
            )
        ),
    )
    return goto(route, Verdict(link=fetched.link, reading=reading))


@step
async def route(verdict: Verdict) -> Transition:
    # Three answers, and the ritual ends on two of them — which is the point of
    # asking before an agent starts editing anything.
    # The headline and the size, not the whole reading: the reading is in the
    # result, and a prompt you have to scroll is not a prompt.
    took = await decide(
        f"{verdict.reading.headline} [{verdict.reading.size}]", options=_TOOK
    )
    triaged = Triaged(link=verdict.link, reading=verdict.reading, took=took)
    if took == "ignore":
        return done(triaged)
    prompt = ACT_ON if took == "fix" else FILE_IT
    # The agent may run commands, and every one of them is gated: `gate_tools`
    # puts each Bash call to you before it happens.
    await coding(
        f"{prompt}{verdict.reading.asks}\n\nlink: {verdict.link}",
        opts=CodingOpts(gate_tools=["Bash"]),
    )
    return done(triaged)
