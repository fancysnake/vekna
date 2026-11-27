from collections.abc import Sequence
from importlib.metadata import version

_BOOLEAN = ("yes", "no")

VERSION = version("vekna")


# The wire's whole compatibility rule: a daemon and whatever talks to it agree
# when their major versions do. A minor or patch release may add to the wire and
# may not break it. `None` is a daemon too old to say its version.
def compatible(theirs: str | None) -> bool:
    return theirs is not None and major(theirs) == major(VERSION)


def major(release: str) -> str:
    return release.partition(".")[0]


# How much of a cast id a person reads: enough to tell the casts on screen apart
# and to type back at `--continue`.
SHORT_ID = 8


# The one reading of a `(options, free)` pair, because every side that meets a
# prompt needs it: the channel asking, the trial double checking a script, the
# ledger checking a journal, the dashboard answering for a spawned cast. `None`
# is "anything goes" — under `free` the options are guesses at the answer and
# answering past them is the point. A bare `decide` offers yes and no.
def allowed_answers(
    *, options: Sequence[str] | None, free: bool
) -> tuple[str, ...] | None:
    if free:
        return None
    return _BOOLEAN if options is None else tuple(options)


# The answers a reaction can give: one emoji names one answer, so a question
# takes reactions when it offers options, suggested or not, or asks yes or no.
# `None` is a question open to any text with nothing offered to name.
def reaction_answers(
    *, options: Sequence[str] | None, free: bool
) -> tuple[str, ...] | None:
    if options is not None:
        return tuple(options)
    return None if free else _BOOLEAN


# The option a typed answer names: itself, or its number in the menu an
# operator was shown. `isdigit` is wider than `int` accepts — "²" is a digit and
# `int` raises on it, as it does on a digit string past CPython's conversion
# limit. Neither is a menu number, and raising here would crash a prompt that
# has an answer for anything else typed at it.
def picked_option(answer: str, options: Sequence[str]) -> str | None:
    if answer in options:
        return answer
    if not answer.isdecimal() or len(answer) > len(str(len(options))):
        return None
    index = int(answer)
    return options[index - 1] if 1 <= index <= len(options) else None


# `--key value` and `--key=value`, as `vekna cast` and the dashboard both take
# them, so a ritual started from either reads its flags the same way.
def parse_flags(flags: Sequence[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    tokens = iter(flags)
    for token in tokens:
        if not token.startswith("--"):
            msg = f"unexpected argument: {token!r}"
            raise ValueError(msg)
        key, separator, inline = token[2:].partition("=")
        if separator:
            value = inline
        else:
            # Without this, `--a --b` reads --b as the value of --a and never
            # sets b at all. `None` is the sentinel because the tokens are
            # strings: a default of "" would read a trailing `--a` as `--a=`
            # and set the field to empty instead of naming the mistake.
            following = next(tokens, None)
            if following is None or following.startswith("--"):
                msg = f"--{key} is missing a value (write --{key}=<value>)"
                raise ValueError(msg)
            value = following
        parsed[key.replace("-", "_")] = value
    return parsed


# The way back: the flag an operator types for a field, so every refusal and
# listing spells it as `parse_flags` reads it.
def flag_of(field: str) -> str:
    return f"--{field.replace('_', '-')}"
