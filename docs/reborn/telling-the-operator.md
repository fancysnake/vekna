# Telling the operator what happened

See [common.md](common.md) — standalone mode, discovery and configuration,
telemetry in the grimoire.

Three ways vekna reports on itself: an error that names the place it went wrong,
a buzz that reaches a phone rather than an empty terminal, and numbers for the
primitives.

## Error pathways, audited

Every failure path a second user can reach ends in a message that names the
thing that went wrong and the place it went wrong in — not a traceback out of
someone else's library, and not a silent swallow.

Each of these reached deliberately, given a useful error, and covered by a test:

- an SDK disconnect mid-rite;
- resume against a corrupt or truncated run directory;
- a malformed `rituals.py`;
- a `rituals/` submodule that fails to import;
- two sources declaring the same step name;
- a phylactery whose root no longer exists;
- a Focus extra that is not installed;
- a config file that parses but does not validate;
- a component value that fails validation at the CLI boundary.

The list is what is known; the work is the sweep, and anything the sweep turns
up joins it.

Out of scope: recovering from these. A useful error is the deliverable; turning
a failure into a route is
[`../hand/failure-as-transition.md`](../hand/failure-as-transition.md).

## Pushover: the notification that leaves the desk

A cast that stops for an answer raises an OSC 777 notification, and a terminal
that is not on screen raises it to nobody. The whole reason the notification
exists is the operator who walked away, and the OSD reaches exactly as far as
the machine they walked away from. An unattended cast that hits a `decide` at
02:00 waits until someone comes back to the desk to find out it was waiting.

[Pushover](https://pushover.net/) is the smallest thing that closes that gap: an
account, an application token, one HTTPS POST, a phone that buzzes. No daemon
involvement, no wire message, no new dependency — `urllib.request` posts a form.
A lich's own remote channel
([`../eye/discord-channel.md`](../eye/discord-channel.md)) covers the same
ground properly, with commands coming back the other way. This does not compete
with it: it is three lines of config for the operator who has the phone already,
and it works from a plain `vekna cast` with no lich standing.

One table in the **global** config, `~/.config/vekna/config.toml` — per machine,
which is where a credential belongs and where "my phone" is true:

```toml
[pushover]
token = "abc…"   # the application's API token, from pushover.net/apps
user  = "uQi…"   # the user (or group) key, from the dashboard
```

Both keys are required and unknown keys are rejected, as `[rituals]` already is:
a misspelt `usr` would otherwise leave a configured operator waiting for a buzz
that was never going to come.

**The table is read from the global config only.** `.vekna.toml` is committed
([`../safety.md`](../safety.md)); a project file that could carry the token would
be a repository carrying a credential, and a project file that could *override*
the user key would be a repository redirecting someone's notifications. A
`[pushover]` table found in a project config fails the cast, naming the file —
silently ignoring it is how an operator concludes the feature does not work.

**No filter.** All three events — `decide`, `done`, `failed` — go, with the
title the terminal already uses (`vekna needs you` / `vekna finished` /
`vekna failed`) and the same body, truncated at Pushover's 1024 rather than the
terminal's 120. Priorities, sounds, a per-event opt-out and a `device` key are
all out of scope until one of them is missed.

**Not gated on a tty.** The OSC sequence is, because a redirected cast must not
collect escape codes, but a redirected cast is precisely the unattended one.
Nothing is written to stdout, so there is nothing to corrupt.

**Off by default, and off is silent.** No table, no POST, no warning — the
overwhelming majority of casts are watched by someone sitting in front of them.

Errors:

- **A POST that fails** — no network, a revoked token, Pushover down, the
  monthly limit reached — writes one line to stderr (`pushover: <what>`) and
  changes nothing else. A notification is not the cast; a cast that succeeded
  must still exit 0 and say so.
- **Each send runs in its own non-daemon thread**, so a slow POST does not stall
  the event loop before a prompt is printed, and the interpreter still joins it
  on the way out — which is what makes the `done` and `failed` sends, fired
  immediately before the process exits, actually leave the machine. Timeout 5s.
- **A malformed `[pushover]` table** stops the command with the path and the
  complaint, exactly as a malformed `[rituals]` does today.

Out of scope:

- **Notifications from the daemon.** Notifying is the cast's, in the one place
  every ending already funnels through. A daemon that also notified would double
  every buzz for an attached cast.
- **Any second provider.** ntfy, Gotify and Telegram all fit the same three
  fields, and the abstraction to hold them is bigger than the second
  implementation. Write the second one flat if it is ever asked for; extract
  when there is a third.
- **A `vekna notify` command / a `notify` medium.** A ritual that wants to tell
  someone something mid-run is a real want and a different feature.
- **Env overrides.** `VEKNA_*` is for one-shots; a credential is not one.

Where it lands: `Config` in `vekna/lexicon/_pacts.py` gains
`pushover: PushoverConfig | None`, a two-field model forbidding extras.
`vekna/lexicon/_links/pushover.py` is new — one function, token/user/title/body
→ POST `https://api.pushover.net/1/messages.json` via `urllib.request.urlopen`,
urlencoded form, errors to stderr, and the only module that knows the vendor
exists. `StandaloneRenderer.__init__` takes an optional `also_notify` callable
that `notify()` calls before the `isatty` guard, so links never import links and
the renderer never learns what Pushover is. `_inits.py` reads the global config
and binds the sink when the table is there. [`../cli.md`](../cli.md)
*Notifications* gains the table and the sentence that the OSD is per-terminal
and this is not.

## Telemetry hooks

Measure what the primitives cost. Per-call agent telemetry already lands in the
journal; what is missing is the engine's own numbers — how long a step boundary
takes, how long a medium spends before its Focus answers, how long a lock
acquisition waits — so that "vekna is slow" becomes a measurement rather than an
impression.

- **Opt-in hooks** at the boundaries the engine owns: step entry and exit,
  medium call and reply, lock request and grant, journal write.
- **Off by default and free when off.** A hook that is not installed costs a
  branch, not an allocation.
- **A callable, not a format.** Vekna emits `(name, duration, labels)` and does
  not ship an exporter — whoever is measuring already has one.

Out of scope: an exporter, a metrics server, a dashboard; sampling, aggregation
or percentiles; anything that is on by default.

## Acceptance

- Each error path above has a test that asserts on the message, not just the
  exit code, and none of them ends in a traceback from a third-party module.
- A configured machine casting a ritual that hits `decide` buzzes the phone with
  the prompt, before the prompt has been answered; `done` and `failed` arrive
  after the process has exited, not truncated by it.
- An unconfigured machine, and a machine whose network is down, cast exactly as
  they do today — same exit code, same output, one stderr line in the second
  case. `[pushover]` in a project `.vekna.toml` fails the cast naming the file.
- With no telemetry hook installed, a cast's event stream and timing are
  unchanged; with one installed, every boundary reports once per crossing.
- `deptry` stays green: nothing was added to `pyproject.toml`.
- `mise run fullcheck` passes.
