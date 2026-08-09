# TODO

- DSL-based workflow orchestrator for agents

## Friction

- `tingle`'s `type-cast` metric counts every symbol named `cast`, not just
  `typing.cast`. Naming a `CastView` parameter `cast` — the domain word this
  project is built on — read as +25 typing debt and failed `fullcheck`. Worked
  around by calling them `view`; the metric wants a way to say "this symbol,
  imported from this module".
