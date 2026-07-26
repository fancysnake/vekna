import ast

from vekna.lexicon._pacts import Ritual

from .engine import Compendium

_GOTO = "goto"
_DONE = "done"
# Labels for the two nodes that are not steps: where a cast enters, and where
# it leaves.
START = "(start)"
ENDS = "(done)"


# Best-effort and deliberately shallow: the graph is read off the source text,
# so a `goto` whose target is computed rather than named simply does not show
# up. Running the ritual remains the only way to know for certain.
def _transitions(source: str | None) -> list[str]:
    if source is None:
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    targets: list[str] = []
    ends = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id == _DONE:
            ends = True
        elif node.func.id == _GOTO and node.args:
            target = node.args[0]
            if isinstance(target, ast.Name) and target.id not in targets:
                targets.append(target.id)
    return [*targets, ENDS] if ends else targets


def _walk(
    *,
    compendium: Compendium,
    label: str,
    source: str | None,
    seen: set[str],
    graph: list[tuple[str, list[str]]],
) -> None:
    targets = _transitions(source)
    graph.append((label, targets))
    for target in targets:
        # A target the compendium never saw is a leaf: it is named here but
        # its own transitions cannot be read.
        if target in seen or (found := compendium.step(target)) is None:
            continue
        seen.add(target)
        _walk(
            compendium=compendium,
            label=target,
            source=found.source,
            seen=seen,
            graph=graph,
        )


def step_graph(
    compendium: Compendium, the_ritual: Ritual
) -> list[tuple[str, list[str]]]:
    graph: list[tuple[str, list[str]]] = []
    _walk(
        compendium=compendium,
        label=START,
        source=the_ritual.source,
        seen={START},
        graph=graph,
    )
    return graph
