# mort log

Dated decisions and progress, newest first.

## 2026-11-25

- Icon: `docs/mort.svg`, an original ghost peeking over a terminal (mort is French for death). Animated with CSS inside the SVG: slow glance left and right, smile and blush when facing the viewer, blink, bob, finger taps, cursor blink. Still under `prefers-reduced-motion`. No show character art is used.
- Phase 1 started. Rules (`mort/rules.py`) are plain functions that take observed values (alive, exit code, last log write, now), so tests use fake clocks and need no real jobs. Run tests with `python3 -m unittest`.
- Exit codes: `mort run` will wrap the command so the shell writes `$?` to a file when it ends, and mort records the wrapper's PID. A job that is gone with no exit file (killed, or adopted with `track pid`) counts as died.
- Stalled: alive and no log write for more than `stall_after` seconds. Exactly `stall_after` is not a stall. `None` turns the check off.
- Lock: the PID is read from one whitespace-separated field, set by index in config, so any one-line lock format works. An empty lock is free. A lock with no readable PID counts as stale, since it protects nothing.
- State: one SQLite table `jobs` in `~/.mort/state.db`. `last_event` holds the last event sent, so each event is sent once.
