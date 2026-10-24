"""The ritual author's test seam.

A `Trial` installs a double where each medium reaches the outside — the Focus
`coding` resolves, the Focus `shell` resolves, the Channel `decide` asks, the
queue `enqueue` and `await_cast` reach — and runs the ritual against a script
of answers. The medium's own body still runs, so session threading, output
validation and exit-code handling are exercised rather than skipped.

    with Trial() as trial:
        trial.shell.replies(when="mise run lint:py", exit_code=0)
        transition = trial.walk(gates, Attempt(budget=1))

Under pytest the `trial` fixture is the same object, already installed.
"""

from ._inits import Trial
from ._links import CodingDouble, DecideDouble, QueueDouble, ShellDouble
from ._pacts import Asked, Enqueued, TrialError, TrialScriptError

__all__ = [
    "Asked",
    "CodingDouble",
    "DecideDouble",
    "Enqueued",
    "QueueDouble",
    "ShellDouble",
    "Trial",
    "TrialError",
    "TrialScriptError",
]
