from pydantic import BaseModel

from vekna.lexicon._pacts import Ritual, RitualDefinitionError, Step

from .engine import recovery_for, step_taking

# Labels for the two nodes that are not steps: where a cast enters, and where
# it leaves.
START = "(start)"
ENDS = "(done)"
# A legacy `-> Transition` step declares no exits; the graph says so rather
# than guessing.
UNKNOWN = "?"
# Marks the step a raise routes to — the one taking `Failure[<what entered>]`.
ON_FAILURE = " (on failure)"


# An exit no step takes is the one mis-wire mypy cannot see — the annotation
# is well-typed, it just names a class nothing was decorated with. Refused
# here, which every load route reaches before a cast starts.
def _target(*, ritual: str, label: str, exit_type: type[BaseModel]) -> Step:
    if (found := step_taking(exit_type)) is None:
        msg = (
            f"ritual {ritual!r}: {label} may return {exit_type.__name__}, "
            "which no step takes"
        )
        raise RitualDefinitionError(msg)
    return found


# The walk is a closure because the ritual's name, the nodes already drawn and
# the graph being built are the same for the whole of it — only the node moves.
# The name is carried for the diagnostic alone: a library holds many rituals,
# and `START` is a display label that names none of them.
def step_graph(the_ritual: Ritual) -> list[tuple[str, list[str]]]:
    graph: list[tuple[str, list[str]]] = []
    # The steps already walked, by identity rather than by name: a name routes
    # nothing, so one graph may hold two `measure` steps, and skipping the
    # second as seen would leave its exits unchecked.
    seen: set[Step] = set()

    def walk(
        *,
        label: str,
        exits: tuple[type[BaseModel], ...] | None,
        ends: bool,
        payloads: tuple[type[BaseModel], ...] = (),
    ) -> None:
        # Failure edges are read off what enters, not what leaves, so a legacy
        # step that declares no exits still has them.
        recoveries = [found for payload in payloads if (found := recovery_for(payload))]
        failing = list(
            {found: f"{found.name}{ON_FAILURE}" for found in recoveries}.values()
        )
        if exits is None:
            graph.append((label, [UNKNOWN, *failing]))
            targets = recoveries
        else:
            targets = [
                _target(ritual=the_ritual.name, label=label, exit_type=exit_type)
                for exit_type in exits
            ]
            # A union exit names one step several times; the graph draws it
            # once, in the order the annotation put them. Deduped by Step like
            # `seen` is, so two distinct steps of one name stay two edges.
            names = list({target: target.name for target in targets}.values())
            graph.append((label, [*names, *([ENDS] if ends else []), *failing]))
            targets = [*targets, *recoveries]
        for target in targets:
            if target in seen:
                continue
            seen.add(target)
            walk(
                label=target.name,
                exits=target.exits,
                ends=target.ends,
                payloads=target.payloads,
            )

    walk(label=START, exits=the_ritual.exits, ends=the_ritual.ends)
    return graph


# The walk for its refusals rather than its drawing: every exit resolves, or
# `_target` says which one does not. The graph it builds on the way is dropped.
def check_exits(the_ritual: Ritual) -> None:
    step_graph(the_ritual)
