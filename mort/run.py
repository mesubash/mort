import os
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from mort import state
from mort.rules import pid_alive, stale_lock

NAME = re.compile(r"[A-Za-z0-9._-]+")

# Runs the job, saves its exit code, then frees the lock if the lock still names this wrapper.
# The first loop waits for mort to write the lock, so a job that ends at once still frees it.
# The TERM trap keeps the wrapper alive through `mort kill` (which signals the whole group) so it
# can still clean up; a handler, unlike an ignore, is not inherited by the job.
WRAPPER = r'''
trap ':' TERM
lock_pid() { awk -v f="$MORT_PID_FIELD" 'NF >= f {print $(NF - f + 1); exit}' "$MORT_LOCK" 2>/dev/null; }
i=0
while [ -n "$MORT_LOCK" ] && [ "$(lock_pid)" != "$$" ] && [ $i -lt 50 ]; do sleep 0.1; i=$((i+1)); done
"$@"
echo $? > "$MORT_EXIT"
if [ -n "$MORT_LOCK" ] && [ "$(lock_pid)" = "$$" ]; then rm -f "$MORT_LOCK"; fi
'''


def lock_settings(lock):
    """Return (path, format, PID position counted from the end, 1 = last word) from the [lock] config table.

    Counting from the end lets other tools put spaces in the words before the PID (a job name of
    several words, a folder name), as long as the words after it are fixed.
    """
    path = Path(lock.get("path", state.HOME / "lock")).expanduser()
    fmt = lock.get("format", "{name} {pid} {start}")
    fields = fmt.split()
    if "{pid}" not in fields:
        raise SystemExit("mort: [lock] format needs {pid} as its own word")
    return path, fmt, len(fields) - fields.index("{pid}")


def check_free(db, name):
    if not NAME.fullmatch(name):
        raise SystemExit(f"mort: bad job name {name!r}; use letters, digits, '.', '_' or '-'")
    row = db.execute("SELECT pid FROM jobs WHERE name = ?", (name,)).fetchone()
    if row and pid_alive(row["pid"]):
        raise SystemExit(f"mort: job {name!r} is still running (pid {row['pid']})")


def ps(pid, field):
    out = subprocess.run(["ps", "-o", f"{field}=", "-p", str(pid)], capture_output=True, text=True,
                         env=dict(os.environ, LC_ALL="C"))
    return out.stdout.strip() or None


def check_watch(watch):
    if watch is None:
        return None
    try:
        rx = re.compile(watch)
    except re.error as e:
        raise SystemExit(f"mort: bad --watch pattern: {e}")
    if rx.groups < 1:
        raise SystemExit("mort: --watch needs a group around the number, e.g. 'loss=([0-9.]+)'")
    return watch


def track(pid, name=None, log=None, stall_after=1200, done=None, watch=None):
    """Adopt a process mort did not start."""
    if not pid_alive(pid):
        raise SystemExit(f"mort: no running process {pid}")
    name = name or re.sub(r"[^A-Za-z0-9._-]", "-", Path(ps(pid, "comm") or str(pid)).name)
    db = state.connect()
    check_free(db, name)
    if log is not None:
        log = Path(log).expanduser().resolve()
        if not log.is_file():
            raise SystemExit(f"mort: no log file at {log}")
    lstart = ps(pid, "lstart")
    started = datetime.strptime(lstart, "%a %b %d %H:%M:%S %Y").timestamp() if lstart else time.time()
    if watch and log is None:
        raise SystemExit("mort: --watch needs --log")
    db.execute("INSERT OR REPLACE INTO jobs (name, pid, cmd, log, started, stall_after, lock, last_event, done_marker, watch)"
               " VALUES (?, ?, ?, ?, ?, ?, 0, NULL, ?, ?)",
               (name, pid, ps(pid, "command"), str(log) if log else None, started,
                stall_after if log else None, done, check_watch(watch)))
    db.commit()
    return name


def start(cmd, name=None, stall_after=1200, lock=None, watch=None, watch_log=None):
    """Start cmd detached. lock is the [lock] config table, or None for no lock."""
    name = name or Path(cmd[0]).name
    check_watch(watch)
    db = state.connect()
    check_free(db, name)

    lock_path, pid_field = None, 0
    if lock is not None:
        lock_path, fmt, pid_field = lock_settings(lock)
        text = lock_path.read_text() if lock_path.exists() else ""
        if text.strip() and not stale_lock(text, -pid_field):
            raise SystemExit(f"mort: lock {lock_path} is held: {text.strip()}")

    log, exit_file = state.job_files(name)
    log.parent.mkdir(parents=True, exist_ok=True)
    exit_file.unlink(missing_ok=True)
    if shutil.which("caffeinate"):
        cmd = ["caffeinate", "-dims", *cmd]
    env = dict(os.environ, MORT_EXIT=str(exit_file), MORT_LOCK=str(lock_path or ""), MORT_PID_FIELD=str(pid_field))
    with open(log, "w") as out:
        pid = subprocess.Popen(["sh", "-c", WRAPPER, "mort", *cmd], stdin=subprocess.DEVNULL,
                               stdout=out, stderr=subprocess.STDOUT, env=env, start_new_session=True).pid
    started = time.time()
    if lock_path:
        line = fmt.format(
            name=name, pid=pid, cwd=Path.cwd().name, start=datetime.fromtimestamp(started).strftime("%Y-%m-%d_%H:%M"))
        lock_path.write_text(line + "\n")
    db.execute("INSERT OR REPLACE INTO jobs (name, pid, cmd, log, started, stall_after, lock, last_event, watch, watch_log)"
               " VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)",
               (name, pid, " ".join(cmd), str(log), started, stall_after, int(lock_path is not None), watch,
                str(Path(watch_log).expanduser().absolute()) if watch_log else None))
    db.commit()
    return name, pid, log
