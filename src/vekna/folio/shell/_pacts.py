from pydantic import BaseModel

from vekna.lexicon import RitualError


# A resumed cast whose ritual changed can land a rite id on a result some other
# medium recorded. The shape it reads back is then not a shell result at all,
# and saying so beats a pydantic traceback out of the middle of a replay.
class ShellOutputError(RitualError):
    pass


class ShellResult(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
