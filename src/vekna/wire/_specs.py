from collections.abc import Sequence

_BOOLEAN = ("yes", "no")


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
