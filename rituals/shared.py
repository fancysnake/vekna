from typing import Annotated

from pydantic import Field

# A retry budget counts down to zero, so a negative one has no meaning to count
# from. Rejecting it at the boundary is the whole point of a typed Components:
# `--bound -1` is a mistake the CLI can name, not a cast that runs to max_steps.
Bound = Annotated[int, Field(ge=0)]
