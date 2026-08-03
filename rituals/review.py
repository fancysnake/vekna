# review — read the diff this branch adds, and say what is wrong with it.

import hashlib
from typing import Literal

from pydantic import BaseModel

from vekna.folio.coding import CodingOpts, coding
from vekna.folio.coding_claude import ClaudeOptions
from vekna.folio.shell import shell
from vekna.lexicon import (
    File,
    GitRef,
    RitualError,
    Text,
    Transition,
    done,
    goto,
    ritual,
    step,
)

from .prompts import REVIEW, REVIEW_SYSTEM


class ReviewRequest(BaseModel):
    base: GitRef = "main"
    only: File | None = None
    focus: Text = ""


class Diff(BaseModel):
    base: str
    text: str
    focus: str = ""
    pinned: str | None = None


class Finding(BaseModel):
    where: str
    what: str
    severity: Literal["blocker", "risk", "nit"]


# What the agent returns, and no more: the provenance below is the ritual's to
# state, not the agent's to invent.
class Judgement(BaseModel):
    verdict: Literal["ship", "fix"]
    findings: list[Finding]


class Review(BaseModel):
    base: str
    verdict: Literal["ship", "fix"]
    findings: list[Finding]
    pinned: str | None = None


@ritual("review")
async def review(components: ReviewRequest) -> Transition:
    # The components are already the first step's payload — there is nothing to
    # map, so nothing is mapped.
    return goto(collect, components)


@step
async def collect(request: ReviewRequest) -> Transition:
    scope = f" -- {request.only}" if request.only is not None else ""
    # stream=False: a diff is bulk, not progress. It reaches the agent in the
    # next step either way.
    result = await shell(f"git diff {request.base}...HEAD{scope}", stream=False)
    if result.exit_code:
        msg = f"git diff against {request.base!r} failed: {result.stderr.strip()}"
        raise RitualError(msg)
    # Nothing changed is an answer, and not one worth paying an agent for.
    if not result.stdout.strip():
        return done(Review(base=request.base, verdict="ship", findings=[]))
    return goto(
        judge,
        Diff(
            base=request.base,
            text=result.stdout,
            focus=request.focus,
            # The diff, not the file on disk: `git diff base...HEAD` reads
            # committed content, so hashing the working tree would pin bytes
            # the agent never saw whenever the checkout is dirty.
            pinned=hashlib.sha256(result.stdout.encode()).hexdigest(),
        ),
    )


@step
async def judge(diff: Diff) -> Transition:
    focus = f"Pay particular attention to: {diff.focus}\n\n" if diff.focus else ""
    judgement = await coding(
        f"{REVIEW}{focus}base: {diff.base}\n\n{diff.text}",
        output=Judgement,
        # Read-only, enforced rather than requested: `dontAsk` denies anything
        # outside the allowlist without stopping to prompt. Not `plan`, which
        # executes no tools at all — the reviewer could not read CLAUDE.md.
        opts=CodingOpts(
            system=REVIEW_SYSTEM,
            focus_options=ClaudeOptions(
                permission_mode="dontAsk",
                allowed_tools=["Read", "Grep", "Glob"],
                effort="high",
            ),
        ),
    )
    return done(
        Review(
            base=diff.base,
            verdict=judgement.verdict,
            findings=judgement.findings,
            pinned=diff.pinned,
        )
    )
