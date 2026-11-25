import os
import signal
import time
from datetime import datetime
from pathlib import Path

from mort import state
from mort.rules import job_event, pid_alive, stale_lock
from mort.run import lock_settings


def ago(seconds):
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    return f"{s // 3600}h{s % 3600 // 60:02d}m"


def status(job, now=None):
    """Return (state, detail) for a jobs row: running, stalled, finished or died."""
    now = now or time.time()
    log = Path(job["log"]) if job["log"] else None
    _, exit_file = state.job_files(job["name"])
    code = int(exit_file.read_text()) if exit_file.exists() else None
    # An exit file means the job is over even if its PID was reused by another process.
    alive = code is None and pid_alive(job["pid"])
    if not alive and code is None and job["done_marker"] and log and log.exists() and done_in(log, job["done_marker"]):
        code = 0
    last_output = log.stat().st_mtime if log and log.exists() else job["started"]
    event = job_event(alive, code, last_output, now, job["stall_after"])
    if event is None:
        return "running", f"{ago(now - job['started'])}, output {ago(now - last_output)} ago"
    if event == "stalled":
        return "stalled", f"no output for {ago(now - last_output)}"
    ended = exit_file if exit_file.exists() else log if log and log.exists() else None
    at = datetime.fromtimestamp(ended.stat().st_mtime).strftime("%H:%M") if ended else "?"
    return event, f"{at} (exit {code})" if code is not None else f"{at} (no exit code)"


def done_in(log, marker, tail=8192):
    with open(log, "rb") as f:
        f.seek(max(0, log.stat().st_size - tail))
        return marker in f.read().decode(errors="replace")


MARK = {"running": " *", "stalled": " !", "finished": "ok", "died": " x"}


def summary(lock_cfg):
    db = state.connect()
    lines = ["JOBS"]
    rows = db.execute("SELECT * FROM jobs ORDER BY started DESC").fetchall()
    width = max([len(r["name"]) for r in rows] + [4])
    for row in rows:
        st, detail = status(row)
        lines.append(f"{MARK[st]} {row['name']:<{width}}  {st:<8}  {detail}")
    if not rows:
        lines.append("   none; start one with: mort run -- <command>")
    if lock_cfg is not None:
        path, _, pid_field = lock_settings(lock_cfg)
        text = path.read_text().strip() if path.exists() else ""
        if not text:
            lock = "free"
        elif stale_lock(text, pid_field - 1):
            lock = f"stale: {text}"
        else:
            lock = f"held: {text}"
        lines += ["LOCK", f"   {lock}"]
    return "\n".join(lines)


def find(name):
    row = state.connect().execute("SELECT * FROM jobs WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise SystemExit(f"mort: no job named {name!r}")
    return row


def kill(name, confirm=input):
    row = find(name)
    pid = row["pid"]
    if not pid_alive(pid):
        raise SystemExit(f"mort: {name} is not running")
    if confirm(f"stop {name} (pid {pid}, started {ago(time.time() - row['started'])} ago)? [y/N] ").strip().lower() != "y":
        return False
    # `mort run` jobs lead their own process group, so the job and its children all get the signal.
    if os.getpgid(pid) == pid:
        os.killpg(pid, signal.SIGTERM)
    else:
        os.kill(pid, signal.SIGTERM)
    db = state.connect()
    db.execute("UPDATE jobs SET last_event = 'died' WHERE name = ?", (name,))  # the user knows; no alert
    db.commit()
    return True


def forget(name):
    row = find(name)
    db = state.connect()
    db.execute("DELETE FROM jobs WHERE name = ?", (name,))
    db.commit()
    return pid_alive(row["pid"]), row["pid"]
