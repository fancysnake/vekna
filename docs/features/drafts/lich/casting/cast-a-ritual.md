status: draft
updated: 2026-05-24

# Cast a ritual end-to-end

## Defining a ritual

As a developer, I want to declare a function as a ritual with a name, so that I can invoke it later without writing glue code.

- the system registers the function under the given name
- the function's typed parameters become the ritual's required inputs

## Running a ritual

As a developer, I want to run a ritual by name and supply its inputs, so that I can execute the work in one motion.

- the system finds the ritual by name
- the system validates every input against its declared type before any ritual code runs
- the ritual body never runs when validation fails
- a failed invocation reports failure
- the system emits distinct start, finish, and failure markers as the ritual runs

## Supplying inputs

As a developer, I want to pass an existing file path as an input, so that the ritual can read it without me wrapping each call in existence checks.

- nonexistent or unreadable paths are rejected before the ritual runs

As a developer, I want to pass an existing directory path as an input, so that the ritual can operate on a tree without bespoke validation.

- nonexistent directories are rejected before the ritual runs

As a developer, I want to pass a short string input inline, so that quick invocations stay terse.

As a developer, I want to pipe a string input from another process, so that I can compose rituals with other tools.

As a developer, I want to compose a long multi-line string input in my editor, so that I'm not fighting shell quoting for prose-sized inputs.

## Discovering rituals

As a developer, I want the system to find a rituals file near where I'm working automatically, so that I don't have to point at it every time.

- the system walks upward from the current directory until it finds one

As a developer, I want to list additional ritual sources in a project-level config, so that a team shares one ritual catalog without per-developer setup.

As a developer, I want to list ritual sources in a personal global config, so that my own utility rituals follow me across projects.

As a developer, I want project sources to take precedence over global ones when names collide, so that project intent wins over personal defaults.

## Inspecting available rituals

As a developer, I want to see every ritual the system knows about along with each one's inputs, so that I can discover what's runnable without grepping source.

As a developer, I want to inspect a single ritual's inputs and source location, so that I can see what it accepts and jump to its definition.
