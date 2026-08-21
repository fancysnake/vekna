# Feature — pushover: the notification that leaves the desk

**Version:** `0.8.0` — **planned**, beside [13-ritual-craft.md](13-ritual-craft.md)
and [14-ritual-defaults.md](14-ritual-defaults.md), which are the same size.

See [00-common.md](00-common.md) — discovery and configuration, standalone.

## Where this came from

A cast that stops for an answer raises an OSC 777 notification, and a terminal
that is not on screen raises it to nobody. The whole reason the notification
exists is the operator who walked away, and the OSD reaches exactly as far as
the machine they walked away from. An unattended `pr_check` that hits a `decide`
at 02:00 waits until someone comes back to the desk to find out it was waiting.

[Pushover](https://pushover.net/) is the smallest thing that closes that gap: an
account, an application token, one HTTPS POST, a phone that buzzes. No daemon
involvement, no wire message, no new dependency — `urllib.request` posts a form.
Discord ([`../hand/07-discord.md`](../hand/07-discord.md), `3.0.0`) covers the
same ground properly, for a lich, with a channel per station and commands coming
back the other way. This does not compete with it — and now precedes it by two
major versions: it is three lines of config for the operator who has the phone
already, and it works from a plain `vekna cast` with no lich standing.

## Goal

Every desktop notification a cast raises also reaches the operator's phone, when
the machine is configured for it and silently not otherwise.

## What ships

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
([`safety.md`](../safety.md)); a project file that could carry the token would
be a repository carrying a credential, and a project file that could *override*
the user key would be a repository redirecting someone's notifications. Neither
is worth the line it would take to support. A `[pushover]` table found in a
project config fails the cast, naming the file — silently ignoring it is how an
operator concludes the feature does not work.

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

## Errors

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

## Out of scope

- **Notifications from the daemon.** Notifying is the cast's, in the one place
  every ending already funnels through. A daemon that also notified would double
  every buzz for an attached cast.
- **Any second provider.** ntfy, Gotify and Telegram all fit the same three
  fields, and the abstraction to hold them is bigger than the second
  implementation. Write the second one flat if it is ever asked for; extract
  when there is a third.
- **A `vekna notify` command / a `notify` medium.** A ritual that wants to tell
  someone something mid-run is a real want and a different feature — this one is
  about the notifications vekna already raises.
- **Env overrides.** `VEKNA_*` is for one-shots ([00-common.md](00-common.md));
  a credential is not one.

## Where it lands

- `Config` in `vekna/lexicon/_pacts.py` gains `pushover: PushoverConfig | None`,
  a two-field model forbidding extras.
- `vekna/lexicon/_links/pushover.py` — new, one function: token, user, title,
  body → POST `https://api.pushover.net/1/messages.json` via
  `urllib.request.urlopen`, urlencoded form, errors to stderr. The only module
  that knows the vendor exists.
- `StandaloneRenderer.__init__` takes an optional `also_notify` callable; the
  first line of `notify()` calls it, before the `isatty` guard. Links may not
  import links — the renderer never learns what Pushover is, and the terminal
  notification keeps working with nothing injected.
- `vekna/lexicon/_inits.py` reads the global config, and binds the sink when the
  table is there. `_config_files` already finds the file; this is the second
  caller to want its contents.
- [`cli.md`](../cli.md) *Notifications* gains the table and the sentence that
  the OSD is per-terminal and this is not.

## Acceptance

- A configured machine casting a ritual that hits `decide` buzzes the phone with
  the prompt, before the prompt has been answered.
- `done` and `failed` arrive after the process has exited, not truncated by it.
- An unconfigured machine, and a machine whose network is down, cast exactly as
  they do today — same exit code, same output, one stderr line in the second case.
- `[pushover]` in a project `.vekna.toml` fails the cast naming the file.
- `deptry` stays green: nothing was added to `pyproject.toml`.
