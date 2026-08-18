# Mediums

A medium is what a step reaches out to. Three ship: `coding` (an agent),
`shell`, and `decide` (ask the operator). Each call opens a rite of its own, so
the grimoire records what happened and in what order.

On the surface that rite is one line, quoting the medium's first argument — a
`shell`'s command, a prompt — with its whitespace collapsed and cut to 60
characters, so lead with the part worth reading. The first argument as the
medium *declares* it, not as the call happened to spell it: `shell(cwd=...,
command=...)` still quotes the command.

## `shell`

```python
from vekna.folio.shell import shell

result = await shell("pytest -x")
if result.exit_code != 0:
    ...
```

Returns the exit code, stdout and stderr. Nothing is raised on a non-zero exit
— a failing command is usually the thing the ritual is about, and an exception
would make the ordinary case the exceptional one.

## `decide`

Hands a choice back to you mid-cast. The cast blocks until you answer.

```python
from vekna.lexicon import offer_prompt

if not await offer_prompt("Push to main?"):
    return done(Verdict(outcome="stopped"))
```

There is no default and no timeout: a `decide` is a choice the ritual author
declared was yours, and guessing it is worse than waiting.

## `coding`

```python
from vekna.folio.coding import CodingOpts, Session, coding
from vekna.folio.coding_claude import ClaudeOptions

# Portable knobs
await coding("refactor this", opts=CodingOpts(model="opus", cwd="./svc"))

# Ask before the agent runs a tool
await coding("clean the build", opts=CodingOpts(gate_tools=["Bash"]))

# Which thread of agent memory this call is on
await coding("try again", session=Session.CONTINUE, key="lint-loop")

# Typed output, validated on return
class Plan(BaseModel):
    steps: int

plan = await coding("plan the migration", output=Plan)

# Knobs only the answering Focus reads
await coding("survey the code", opts=CodingOpts(focus_options=ClaudeOptions(
    permission_mode="dontAsk", allowed_tools=["Read", "Grep"], effort="high"
)))
```

Everything reusable bundles into `CodingOpts` — sharing one across calls is
harmless, which is the point. What stays on the call is what cannot be shared:
`session` and `key`, which say which agent memory *this* call is on, and
`output`, which decides what it returns.

`dontAsk` with an allowlist is how you get a read-only agent: everything
outside the list is denied without stopping to ask you. Not
`permission_mode="plan"`, which executes no tools at all — an agent in plan
mode cannot read the files you gave it `Read` for.

An agent can hand a decision back to you mid-rite by calling the `ask_human`
tool; the cast blocks until you answer, exactly as `decide` does. Any options it
offers are suggestions — pick one by number or by name, or answer in your own
words, which is what the agent gets.

### Sessions

Two `coding` calls in one cast either share the agent's context or they do not.
`session` says whether this call resumes, and `key` says which thread it
resumes and files itself under:

| declaration | what the call gets |
| --- | --- |
| `Session.NEW` (default) | a fresh context |
| `Session.CONTINUE` | the cast's last agent call, carried on |
| `Session.CONTINUE, key="fix"` | the thread keyed `"fix"`, carried on |
| `Session.NEW, key="fix"` | a fresh context, and `"fix"` starts from it |

A retry wants `continue` — an agent remembering what it already tried is the
whole value. A review step wants `new`: an agent that helped write the code is
not a reviewer of it, and sharing silently makes that step worthless while
looking like it ran.

The default is `new` because a step is a task boundary, and carrying context
across one by default contradicts what the boundary is for.

Give a loop its own key. An unkeyed `continue` means whichever agent call ran
last, which is the same thing while a ritual has one, and stops being the same
the moment it gains a second.

A key is refused if it names nothing (`""`, `"  "`), and `session` takes only
the two words, so a thread name left in an older spelling raises
`CodingSessionError` rather than quietly opening a thread of its own.

## When the agent cannot be reached

The `coding` medium runs through the Claude Code CLI, which installs separately
from this package. If it is missing, the cast fails with a message saying so
rather than a traceback. Anything else the SDK raises mid-cast — the subprocess
dying, a dropped connection — ends the cast with the failure named.
