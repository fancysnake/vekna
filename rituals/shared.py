from typing import Annotated

from pydantic import Field

from vekna.folio.shell import ShellResult

# A retry budget counts down to zero, so a negative one has no meaning to count
# from. Rejecting it at the boundary is the whole point of a typed Components:
# `--bound -1` is a mistake the CLI can name, not a cast that runs to max_steps.
Bound = Annotated[int, Field(ge=0)]


# Both streams, in arrival order as far as two captures allow: a tool puts its
# diagnostics on stdout, but a run that dies before it starts — a missing tool,
# a bad flag, a traceback — says so on stderr and nowhere else. Passing stdout
# alone hands the agent an empty complaint.
def said(result: ShellResult) -> str:
    joined = "\n".join(part for part in (result.stdout, result.stderr) if part.strip())
    return joined or f"the command exited with code {result.exit_code}"
