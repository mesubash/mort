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
WRAPPER = r'''
lock_pid() { awk -v f="$MORT_PID_FIELD" '{print $f; exit}' "$MORT_LOCK" 2>/dev/null; }
i=0
while [ -n "$MORT_LOCK" ] && [ "$(lock_pid)" != "$$" ] && [ $i -lt 50 ]; do sleep 0.1; i=$((i+1)); done
"$@"
echo $? > "$MORT_EXIT"
if [ -n "$MORT_LOCK" ] && [ "$(lock_pid)" = "$$" ]; then rm -f "$MORT_LOCK"; fi
'''


def start(cmd, name=None, stall_after=1200, lock=None):
    """Start cmd detached. lock is the [lock] config table, or None for no lock."""
    name = name or Path(cmd[0]).name
    if not NAME.fullmatch(name):
        raise SystemExit(f"mort: bad job name {name!r}; use letters, digits, '.', '_' or '-'")
    db = state.connect()
    row = db.execute("SELECT pid FROM jobs WHERE name = ?", (name,)).fetchone()
    if row and pid_alive(row["pid"]):
        raise SystemExit(f"mort: job {name!r} is still running (pid {row['pid']})")

    lock_path, pid_field = None, 0
    if lock is not None:
        lock_path = Path(lock.get("path", state.HOME / "lock")).expanduser()
        fmt = lock.get("format", "{name} {pid} {start}")
        fields = fmt.split()
        if "{pid}" not in fields:
            raise SystemExit("mort: [lock] format needs {pid} as its own word")
        pid_field = fields.index("{pid}") + 1
        text = lock_path.read_text() if lock_path.exists() else ""
        if text.strip() and not stale_lock(text, pid_field - 1):
            raise SystemExit(f"mort: lock {lock_path} is held: {text.strip()}")

    logs = state.HOME / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log, exit_file = logs / f"{name}.log", logs / f"{name}.exit"
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
            name=name, pid=pid, cwd=Path.cwd().name, start=datetime.fromtimestamp(started).strftime("%Y-%m-%dT%H:%M"))
        lock_path.write_text(line + "\n")
    db.execute("INSERT OR REPLACE INTO jobs (name, pid, cmd, log, started, stall_after, lock, last_event)"
               " VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
               (name, pid, " ".join(cmd), str(log), started, stall_after, int(lock_path is not None)))
    db.commit()
    return name, pid, log
