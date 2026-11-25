# mort log

Dated decisions and progress, newest first.

## 2026-11-25

- `mort run` (task 3): starts `sh -c WRAPPER` in a new session (no hangup when the terminal closes), wrapped in `caffeinate -dims` when that exists (it passes the exit code through, checked). The wrapper writes `$?` to `~/.mort/logs/<name>.exit` and frees the lock only if the lock still names the wrapper's PID, so it never removes a lock another tool wrote. It waits up to 5 s for mort to write the lock first, so a job that ends at once still frees it. A wrapper killed with SIGKILL cannot free the lock; the stale-lock check covers that case.
- Lock config: `[lock] path` and `format` in `~/.mort/config.toml`, with `{name}`, `{pid}`, `{start}`, `{cwd}`. The PID position is read from the format, so there is no separate field number to get wrong. A held lock refuses the run; a stale one is taken over.
- Job names are limited to letters, digits, `.`, `_`, `-`, because they become file names. Run with `python3 -m mort` until packaging.
- Icon: `docs/mort.svg`, an original ghost peeking over a terminal (mort is French for death). Animated with CSS inside the SVG: slow glance left and right, smile and blush when facing the viewer, blink, bob, finger taps, cursor blink. Still under `prefers-reduced-motion`. No show character art is used.
- Phase 1 started. Rules (`mort/rules.py`) are plain functions that take observed values (alive, exit code, last log write, now), so tests use fake clocks and need no real jobs. Run tests with `python3 -m unittest`.
- Exit codes: `mort run` will wrap the command so the shell writes `$?` to a file when it ends, and mort records the wrapper's PID. A job that is gone with no exit file (killed, or adopted with `track pid`) counts as died.
- Stalled: alive and no log write for more than `stall_after` seconds. Exactly `stall_after` is not a stall. `None` turns the check off.
- Lock: the PID is read from one whitespace-separated field, set by index in config, so any one-line lock format works. An empty lock is free. A lock with no readable PID counts as stale, since it protects nothing.
- State: one SQLite table `jobs` in `~/.mort/state.db`. `last_event` holds the last event sent, so each event is sent once.
