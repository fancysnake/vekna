# QA — manual scenarios for `release-0.6.0`

Everything on this branch that a person has to look at: the daemon view, the
wire between a cast and it, the journal on disk, and `vekna cast --continue`.
Automated coverage exists for the units; this is the part that needs eyes.

## Setup

- Two or three terminals, same user, same machine.
- A project with a `rituals.py` holding, at minimum:
  - a ritual with 3+ steps and a `shell` rite that takes ~30s (`sleep 30`),
  - a ritual with a `decide` prompt,
  - a ritual with a `coding` rite (needs `claude-agent-sdk`),
  - a ritual that raises in a step.
- `vekna` installed in the shell (`mise exec -- poetry install`).
- Start clean: no `vekna` running, `~/.local/state/vekna/runs/` and
  `~/.local/state/vekna/debug.log` moved aside.

Where a scenario needs an isolated journal or socket, export `VEKNA_RUNS` and
`VEKNA_SOCKET` in **both** terminals — they are read before the defaults.

---

## 1. The daemon and its view

- [ ] **1.1 Bare `vekna` is the daemon, not help.** Run `vekna`. It paints a
      view, does not print help, does not exit. `vekna --help` prints help.
- [ ] **1.2 Empty view.** With no casts: reads
      ``no casts — run `vekna cast <ritual>` anywhere``, plus the key hints.
- [ ] **1.3 The socket is where it says.** With `XDG_RUNTIME_DIR` set,
      `$XDG_RUNTIME_DIR/vekna.sock` exists while the daemon runs. Unset it,
      restart: `/tmp/vekna-<uid>/vekna.sock`, and `/tmp/vekna-<uid>` is `0700`.
- [ ] **1.4 The socket is cleaned up.** Quit with `q`; the socket file is gone
      and a second `vekna` binds fresh rather than attaching to a corpse.
- [ ] **1.5 A hostile directory is refused.** `chmod 0777 /tmp/vekna-<uid>`
      (with `XDG_RUNTIME_DIR` unset), start `vekna`: it refuses with a sentence
      naming the directory, not a traceback.
- [ ] **1.6 A second `vekna` attaches.** With one running, start another in
      terminal 2. It says `attached to the vekna already running here` and
      paints the **same** casts. It does not bind a second socket.
- [ ] **1.7 A peer sees live casts it missed.** Start a long cast, *then* start
      the second `vekna`. The already-running cast appears in the peer with its
      whole rite tree, not from the moment it attached.
- [ ] **1.8 The peer records nothing.** While only the peer is watching, the
      journal directory gains no new files from the peer's own connection.
- [ ] **1.9 The daemon dying takes the peer down cleanly.** Quit the owner
      daemon; the peer shows `the daemon ended` and exits — no hang, no
      traceback.
- [ ] **1.10 The clock ticks with nothing happening.** With one cast sitting in
      `sleep 60`, `elapsed` and the `now` timer count up every second even
      though no event arrives.

## 2. One row per cast

- [ ] **2.1 The columns say the truth.** Run a 3-step ritual. `ritual` is the
      ritual name, `project` the directory's last segment, `steps` climbs as
      steps finish, `now` shows `<step> · <medium>` and the step's own timer.
- [ ] **2.2 No output leaks into the list.** Run a cast whose shell rite prints
      many lines, including a multi-line pydantic-style error. The table stays
      one row per cast, aligned, nothing reflowed.
- [ ] **2.3 Status words.** Confirm each of `running`, `waiting`, `done`,
      `failed`, `aborted` can be produced and reads as that word:
      - `done` — ritual completes,
      - `failed` — ritual raises,
      - `aborted` — kill the cast process with `SIGKILL`,
      - `waiting` — cast sits on a `decide`.
- [ ] **2.4 Waiting sorts to the top.** With one waiting, two running and two
      finished casts, the waiting one is row 1, running next, ended last.
- [ ] **2.5 An aborted row carries its own cure.** The `SIGKILL`ed cast's `now`
      column reads `vekna cast --continue <id>` — and that command, copied
      verbatim, works (see §5).
- [ ] **2.6 The header tally matches the rows.** `1 running · 1 waiting · …`
      counts what is actually painted.
- [ ] **2.7 Older casts are elided, not lost.** With more casts than the view
      shows, the footer reads `… N older — \`vekna log\` has them all`, and
      `vekna log` does have them.

## 3. Drilling in

- [ ] **3.1 A number drills in.** Type `2`, press enter: the rite tree for the
      cast that was on row 2 — not the one above or below it.
- [ ] **3.2 Live output is here, not in the list.** A streaming shell rite's
      last lines appear indented under the running rite, updating as it runs.
- [ ] **3.3 `b` goes back, `q` quits.** From a drilled-in view.
- [ ] **3.4 A failed cast shows its error here.** Drill into the failed cast:
      the detail it ended on is on screen.
- [ ] **3.5 A waiting cast shows the question and where to answer it.** The
      prompt text, plus `answer it where the cast was started`.
- [ ] **3.6 Junk input is refused, not obeyed.** Type `zzz`: a note saying it is
      not a cast. Type `99`: `there is no cast 99`. The view survives both.
- [ ] **3.7 Notes are said once.** After a note appears, the next repaint (one
      second later) no longer shows it.

## 4. The cast end of the wire

- [ ] **4.1 A cast with no daemon behaves exactly as before.** No daemon
      running: cast a ritual. Full tree in the terminal, prompts work, `result:`
      line at the end, correct exit code. Nothing hangs, nothing warns.
- [ ] **4.2 A daemon raised mid-cast catches up.** Start a long cast with no
      daemon; ~10s in, start `vekna`. Within a couple of seconds the cast
      appears **with the rites it already ran**, not just the ones after.
- [ ] **4.3 A prompt already on screen is caught up too.** Start a cast, let it
      block on `decide`, *then* start `vekna`. The cast shows as `waiting` with
      the prompt — the prompt is not in the rite tree, so this is a separate
      path from 4.2.
- [ ] **4.4 A daemon killed mid-cast strands nothing.** With a cast running,
      `SIGKILL` the daemon. The cast keeps running and finishes normally in its
      own terminal — no hang, no error. Restart `vekna`: the cast reappears.
- [ ] **4.5 The prompt stays where the cast is.** With the daemon running and
      the cast in another terminal, a `decide` is answered on the **cast's**
      stdin. The daemon shows `waiting` while it is open and stops showing it
      the moment it is answered. Typing the answer into `vekna` does nothing.
- [ ] **4.6 Coding's tool gate and the agent's question, same rule.** Run a
      `coding` ritual that trips the gate: the gate prompt is on the cast's
      terminal, and the daemon marks the cast `waiting`.
- [ ] **4.7 A big result crosses the wire.** A shell rite whose stdout is
      several MB (`head -c 5000000 /dev/urandom | base64`). The cast finishes,
      the daemon does not drop the cast or error — the frame limit is 32 MB.
- [ ] **4.8 A cast in a sandbox with its own `XDG_RUNTIME_DIR` is invisible,
      and `VEKNA_SOCKET` fixes it.** Start the cast with a private
      `XDG_RUNTIME_DIR`: `vekna` in the normal shell never sees it. Export the
      same `VEKNA_SOCKET` on both sides: it appears. (Documented behaviour —
      confirm the doc matches reality.)

## 5. The journal and `vekna log`

- [ ] **5.1 A cast run with a daemon is on disk.** After a cast,
      `~/.local/state/vekna/runs/<cast_id>/` holds `run.json` and `events.jsonl`.
      `run.json` names the ritual, the project root and the final status.
- [ ] **5.2 A cast run with no daemon leaves nothing.** No new directory.
- [ ] **5.3 `vekna log` needs no daemon.** Quit the daemon; `vekna log` still
      lists the casts, newest first, with id, status glyph, ritual, local
      timestamp and project root.
- [ ] **5.4 `vekna log` with nothing recorded** says `no casts recorded`.
- [ ] **5.5 One torn record does not hide the rest.** Truncate one
      `run.json` to half a line. `vekna log` lists every other cast without a
      traceback; the broken one is simply absent.
- [ ] **5.6 Pruning keeps the last 200 and spares the living.** Not worth
      faking 200 casts by hand — instead confirm a **running** cast's directory
      survives a daemon restart, and that restarting the daemon does not delete
      recent records.
- [ ] **5.7 Fail-closed on a full disk.** Point `VEKNA_RUNS` at a tiny
      read-only or full filesystem, run a cast under the daemon. The daemon
      reports the write failure; afterwards, `vekna cast --continue <id>`
      **refuses**, saying the journal has a hole in it — it does not replay a
      log missing a rite.

## 6. `vekna cast --continue`

- [ ] **6.1 The happy carry-on.** Run a ritual with: step A (`shell` writing a
      marker file), step B (`decide`), step C (`shell`). Answer the decide,
      `SIGKILL` mid-step-C. Then `vekna cast --continue <id>` from **a
      different directory**:
      - it runs in the original project directory,
      - step A's shell command does **not** run again (marker file untouched,
        no second append),
      - the `decide` is **not** asked again,
      - step C runs live,
      - the cast finishes with a fresh `cast_id`, and `vekna log` shows both.
- [ ] **6.2 A coding rite is not paid for twice.** Same shape with a `coding`
      rite before the interruption: the resumed cast does not call the agent for
      it, and a **later** coding rite on the same thread still remembers the
      earlier conversation (ask it something only the first call could know).
- [ ] **6.3 A coding rite interrupted mid-flight runs again.** Kill during the
      agent call. On resume, that rite runs live, on the session already opened.
- [ ] **6.4 Divergence stops the replay, safely.** Edit the ritual so it takes a
      different branch, then `--continue` the old cast. Replay stops at the
      first rite that does not match and everything from there runs live — no
      answer from the old path leaks into the new one.
- [ ] **6.5 Changed `decide` options are refused, not coerced.** Record an
      answer, then change that `decide`'s options so the recorded answer is no
      longer offered. Resume: it errors saying the journaled answer is not one
      of the options, rather than replaying a value the `Literal` forbids.
- [ ] **6.6 No journal, plain sentence.** `vekna cast --continue deadbeef`:
      names the directory it looked in and says only a cast the daemon saw can
      be resumed. No traceback.
- [ ] **6.7 The project moved.** Rename the project directory, then
      `--continue` a cast from it: `<path> is not there any more — cast '<id>'
      ran in it`. No `NotADirectoryError` out of asyncio.
- [ ] **6.8 An unreadable record/log.** Corrupt `events.jsonl` (garbage line),
      then resume: a sentence naming the file. Same for a corrupt `run.json`.
- [ ] **6.9 Resume does not need a daemon,** and a resumed cast that runs with
      one shows in the view as its own row.

## 7. Option parsing (Docker's rule)

- [ ] **7.1 vekna's flag before the ritual name.**
      `vekna cast --continue <id>` resumes.
- [ ] **7.2 The ritual's flag after the name.** With a ritual declaring its own
      `--continue` component, `vekna cast release --continue` passes it to the
      **ritual**; vekna does not try to resume.
- [ ] **7.3 Unknown options after the name are the ritual's.**
      `vekna cast mine --whatever x` reaches the ritual (or its own error), not
      click's.
- [ ] **7.4 Usage on nothing.** `vekna cast --continue` with no id prints the
      usage block including the `--continue <cast_id>` line, exit 2.
- [ ] **7.5 `vekna cast --help`** still prints the ritual help, not click's.
- [ ] **7.6 `vekna rituals list` / `show`** still work and do **not** start a
      daemon.

## 8. `--debug`

- [ ] **8.1 It says where it is logging.** `vekna --debug` notes
      `logging every event to ~/.local/state/vekna/debug.log` in the view.
- [ ] **8.2 A line per event, including drops.** Run a cast; the log has a line
      per event with kind and cast id. Provoke a drop (e.g. a `RiteFinished`
      for a cast with no hello, by connecting and sending one by hand) and
      confirm the drop is logged with a reason.
- [ ] **8.3 It writes to the file, not the screen.** Nothing from `--debug`
      paints over the view.
- [ ] **8.4 Without `--debug`, nothing is written.** No `debug.log` appears.

## 9. Regression sweep (things this branch touched but did not aim at)

- [ ] **9.1 Rite summaries.** `↳ shell  git status` — the medium's first string
      argument, collapsed and cut — still renders in the cast terminal.
- [ ] **9.2 Notifications.** Desktop notification on `done` and on `failed`,
      including a ritual that dies with an `AttributeError`.
- [ ] **9.3 `vekna cast --prompt "…"`** still runs the one-shot coding ritual.
- [ ] **9.4 Exit codes.** `0` on success, `2` on a load/definition error,
      non-zero on a ritual failure — unchanged with and without a daemon.
- [ ] **9.5 Python 3.12 and 3.13.** Run §1.6, §4.4 and §6.1 on both; the socket
      teardown differs between them.

---

## Notes

- §5.7 and §8.2 need a bit of setup (a full filesystem, a hand-written frame).
  Skip them only if the automated tests for `Journal._mark_gapped` and
  `Hub` drop-logging are green — they are the same paths.
- Anything in §6 is the expensive half of the release: a wrong replay re-runs an
  agent call or a `git push`. Do §6.1 and §6.4 even under time pressure.
