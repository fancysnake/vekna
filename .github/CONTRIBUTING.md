# Contributing to vekna

Questions and ideas go to
[Discussions](https://github.com/fancysnake/vekna/discussions); bugs and
planned work go to [issues](https://github.com/fancysnake/vekna/issues).
Issues labelled
[`good first issue`](https://github.com/fancysnake/vekna/labels/good%20first%20issue)
are small and self-contained.

## Setup

Vekna uses [mise](https://mise.jdx.dev/) for tools and tasks, and Poetry for
the environment:

```bash
mise install
mise exec -- poetry install
mise tasks            # every runnable task, described
```

## The loop

```bash
mise run check:py     # while you work: format, lint, tests
mise run fullcheck    # before you push: adds diff-coverage and tingle
```

A pull request is ready when `mise run fullcheck` passes. Linters stay as
configured: fix the code rather than adding `noqa` or `type: ignore`.

## Where code goes

Code is layered by [GLIMPSE](https://glimpse.fancysnake.dev/), and
`import-linter` enforces the boundaries. Read
[`docs/architecture.md`](../docs/architecture.md) before adding a module, and
[`tests/CLAUDE.md`](../tests/CLAUDE.md) before adding a test: the layer under
test decides whether it is a unit or an integration test.

## Pull requests

- One change per pull request, on a branch off `main`.
- A bug fix starts with a test that fails because of the bug.
- User-visible changes get a line under `Unreleased` in
  [`CHANGELOG.md`](../CHANGELOG.md).
