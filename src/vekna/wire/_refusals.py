from typing import NamedTuple

from pydantic import ValidationError


class Refusal(NamedTuple):
    loc: tuple[int | str, ...]
    kind: str
    msg: str


# Pydantic's own report is a list of TypedDicts whose values are `Any`, and this
# is the one module that reads it: everything past here gets typed fields.
def refusals(error: ValidationError) -> list[Refusal]:
    return [
        Refusal(loc=tuple(detail["loc"]), kind=detail["type"], msg=detail["msg"])
        for detail in error.errors(include_url=False)
    ]


# `str(error)` titles the report with a model name the reader never wrote, ends
# every line with a docs URL, and quotes the input back at length. What is left
# is the field and what was wrong with it.
def explained(error: ValidationError) -> str:
    return "; ".join(
        (
            f"{'.'.join(str(part) for part in refusal.loc)}: {refusal.msg}"
            if refusal.loc
            else refusal.msg
        )
        for refusal in refusals(error)
    )
