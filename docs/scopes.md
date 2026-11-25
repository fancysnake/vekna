---
description: "The three scopes vekna works at: rituals a project owns, tomes several projects install, and one user-scope install that serves every checkout on the machine from a single config."
---

# Scopes: project, tome, user

vekna works at three scopes. Each one moves a step further from the single
repository, and each is a different way of using the tool, with its own answer
to three questions: where vekna is installed, where the rituals live, and where
the settings live.

| Scope | vekna is installed | Rituals live | Settings live |
| --- | --- | --- | --- |
| **Project** | in the project | in the project's `rituals.py` | in the project's `.vekna.toml` |
| **Tome** | in the project | in a package the project installs | in the project's `.vekna.toml` |
| **User** | once, for the machine | in tomes installed beside vekna | in `~/.config/vekna/config.toml` |

The scopes combine. A project at user scope can still own a `rituals.py`, and
its `.vekna.toml` still counts. Choose by what you want to stay the same: the
project scope pins everything to one repository, the user scope keeps one
version of vekna and of each tome across all of them.

## Project scope: the repository owns its rituals

This is where [the first ritual](index.md#your-first-ritual) starts. vekna is a
dev dependency, the rituals sit in `rituals.py` or a `rituals/` package, and
`.vekna.toml` is committed beside them. Everything a cast needs travels with
the repository, and a second repository shares nothing with the first.

Use it for rituals that only make sense in one codebase.

## Tome scope: several projects install the same rituals

A [tome](rituals.md#tomes-rituals-you-install) is a ritual library published
as a package. The rituals leave the repository; the install and the settings
stay in it. Each project lists the tome in its `.vekna.toml`, pins its own
version of vekna and of the tome, and sets its own values.

Use it when the rituals are shared but each project must control when it
upgrades.

The cost shows as the projects multiply. Each one carries its own vekna, so
five projects can run five versions against the one daemon the machine has, and
a tome upgrade is five upgrades.

## User scope: one vekna for every checkout

At user scope vekna is a tool of the machine, like git. You install it once,
with its tomes, and one file says which rituals exist and what each project's
settings are. A project needs nothing committed to be cast in: no dependency,
no `.vekna.toml`.

This is also the scope the daemon works at. It starts every queued cast with
its own interpreter, so a cast it spawns already runs the daemon's vekna and
the daemon's tomes, whatever the project pins.

### Install once

A tome installs into the environment vekna runs in, so name it when you
install vekna. With [mise](https://mise.jdx.dev), in
`~/.config/mise/config.toml`:

```toml
[tools]
pipx = "<version>"
# uvx = false because --preinstall is a pipx flag.
"pipx:vekna" = { version = "<version>", uvx = false, pipx_args = "--preinstall mycompany-rites" }
```

With pipx alone: `pipx install vekna`, then `pipx inject vekna
mycompany-rites`.

A project that also lists vekna as a dev dependency, to test rituals of its
own, runs that copy while its virtualenv is active.

### One config for every project

`~/.config/vekna/config.toml` holds two kinds of table. Top-level tables apply
to every project. A `[projects.<name>]` table applies to one, and holds the
same tables a `.vekna.toml` would:

```toml
# Every project casts these.
[rituals]
modules = ["mycompany.rites"]

[defaults."mycompany:review"]
depth = 2

# One project. The name is yours; `path` is the checkout.
[projects.app]
path = "~/work/app"

[projects.app.defaults."mycompany:review"]
base_branch = "develop"

[projects.app.circle]
worktrees = 4

# A tome that only this project casts.
[projects.api]
path = "~/work/api"

[projects.api.rituals]
modules = ["apiteam.rites"]
```

A project is a checkout on this machine, and `path` names it. The table speaks
for the whole repository: a cast started in a subdirectory, or in a worktree
the daemon leased, reads the same table as a cast started at `path`. Outside
git, a table speaks for the directory `path` names and nothing below it.

The table names a checkout, not an address on a forge, so repositories from
GitHub and GitLab sit in one file. A ritual that needs the remote reads it from
the checkout.

### Which setting wins

Per key, the nearest place that sets it:

1. a flag on the command line
2. the project's own `.vekna.toml`
3. the `[projects.<name>]` table in your user config
4. the top level of your user config

The project's file comes first: it is what the repository says for everyone
who clones it. Your table for the project sets what the file leaves unset, for
your checkout only. Your top level sets the rest, for every project.
`[rituals]` is the exception to "nearest wins": every place adds to the list.

`vekna rituals show <ritual>` prints each configured component with the place
that set it:

```text
  --base-branch <str>  = develop (/home/me/.config/vekna/config.toml: [projects.app])
```

`vekna audit` prints every setting with the layer it is taken from, and lists
the settings that change nothing.

Three settings are the machine's and not a project's, and are read from the
top level only: `[circle] coding`, the limit on agents running at once,
`[circle] total_processes`, the limit on casts running at once, and
`[circle] vigil_processes`, the limit on casts that
[vigils](cli.md#vigils) started. The whole of [`[discord]`](cli.md#discord) is
the machine's too.

### When a project still needs a `.vekna.toml`

Only when it defines rituals of its own outside the default places. A
`rituals.py` or `rituals/` at the repository root is found without any config.
A ritual source elsewhere in the tree is named by `[rituals] files`, and that
key belongs in the project's `.vekna.toml`: a project table in the user config
refuses it. The file resolves against the tree the cast runs in, which a path
in your user config could not do for a leased worktree.

`[projects]` is read from the user config only. A `.vekna.toml` that holds one
is refused, since a repository cannot say where it is checked out on your
machine.

### Settings are checked when a ritual is cast

The user config lists every tome you use, so a project sees rituals it will
never cast and holds no settings for. That is not an error. vekna checks what a
ritual needs when that ritual is cast, and never when the config is loaded:

- a `[defaults.<ritual>]` table for a ritual that is not installed is ignored
- a default one ritual refuses stops a cast of that ritual, and no other
- a component with no default and no flag is reported as required by the cast
  that needs it

So with rituals `A` and `B` enabled and only `B` configured for a project,
`vekna cast B` runs, and `vekna cast A` says which setting it is missing.

What does stop every command is a config vekna cannot read at all: a file that
is not valid TOML, a misspelt table such as `[ritual]`, or a project table with
no `path`. Each error names the file and the table.

## For tome authors: read your table through vekna

A tome with settings of its own keeps them in a table named after it, such as
`[mytome]`. Read it with `config_table`, and vekna returns the table merged
across every place above, so the tome works at all three scopes without
knowing which one it is in:

```python
from vekna.lexicon import config_table

table = config_table("mytome")
settings = MyTomeSettings.model_validate(table.values)
```

`table.values` is the merged table, nearest key first, with inner tables merged
key by key. `table.sources` names each table that contributed, as the file
spells it, for the error you raise over a refused value. A tome that opens
`.vekna.toml` itself only works at the project scope.

Follow the rule above in your own rituals: validate what a ritual needs when it
is cast, and not when the tome is imported.
