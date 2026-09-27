from pydantic import BaseModel

from vekna.lexicon._pacts import Ritual, RitualDefinitionError, Step

from .engine import step_taking

# Labels for the two nodes that are not steps: where a cast enters, and where
# it leaves.
START = "(start)"
ENDS = "(done)"


# An exit no step takes is the one mis-wire mypy cannot see — the annotation
# is well-typed, it just names a class nothing was decorated with. Refused
# here, which every load route reaches before a cast starts.
def _target(*, label: str, exit_type: type[BaseModel]) -> Step:
    if (found := step_taking(exit_type)) is None:
        msg = f"{label} may return {exit_type.__name__}, which no step takes"
        raise RitualDefinitionError(msg)
    return found


def _walk(
    *,
    label: str,
    exits: tuple[type[BaseModel], ...],
    ends: bool,
    seen: set[str],
    graph: list[tuple[str, list[str]]],
) -> None:
    targets = [_target(label=label, exit_type=exit_type) for exit_type in exits]
    # A union exit names one step several times; the graph names it once.
    names: list[str] = []
    for target in targets:
        if target.name not in names:
            names.append(target.name)
    graph.append((label, [*names, ENDS] if ends else names))
    for target in targets:
        if target.name in seen:
            continue
        seen.add(target.name)
        _walk(
            label=target.name,
            exits=target.exits,
            ends=target.ends,
            seen=seen,
            graph=graph,
        )


def step_graph(the_ritual: Ritual) -> list[tuple[str, list[str]]]:
    graph: list[tuple[str, list[str]]] = []
    _walk(
        label=START,
        exits=the_ritual.exits,
        ends=the_ritual.ends,
        seen={START},
        graph=graph,
    )
    return graph
