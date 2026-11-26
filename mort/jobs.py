import os
import shutil
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path

from mort import machine, remote, state
from mort.rules import job_event, machine_alerts, pid_alive, stale_lock
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
    if job["kind"] == "ssh":
        return remote.status(job, now)
    log = Path(job["log"]) if job["log"] else None
    _, exit_file = state.job_files(job["name"])
    code = int(exit_file.read_text()) if exit_file.exists() else None
    # An exit file means the job is over even if its PID was reused by another process.
    alive = code is None and pid_alive(job["pid"])
    if not alive and code is None and job["done_marker"] and log and log.exists() and done_in(log, job["done_marker"]):
        code = 0
    last_output = log.stat().st_mtime if log and log.exists() else job["started"]
    event = job_event(alive, code, last_output, now, job["stall_after"])
    wrote = log is not None and log.exists() and log.stat().st_size > 0
    if event is None:
        out = f"output {ago(now - last_output)} ago" if wrote else "no output yet"
        return "running", f"{ago(now - job['started'])}, {out}"
    if event == "stalled":
        return "stalled", f"no output for {ago(now - last_output)}"
    ended = exit_file if exit_file.exists() else log if log and log.exists() else None
    at = datetime.fromtimestamp(ended.stat().st_mtime).strftime("%H:%M") if ended else "?"
    if code is None:
        return event, f"{at} (no exit code)"
    return event, f"{at} (exit {code}{signal_name(code)})"


def signal_name(code):
    """The shell reports a job ended by signal N as exit 128+N."""
    try:
        return f", {signal.Signals(code - 128).name}" if code > 128 else ""
    except ValueError:
        return ""


def done_in(log, marker, tail=8192):
    with open(log, "rb") as f:
        f.seek(max(0, log.stat().st_size - tail))
        return marker in f.read().decode(errors="replace")


MARK = {"running": " *", "stalled": " !", "finished": "ok", "died": " x", "unknown": " ?"}


def summary(config, reading=None):
    lock_cfg = config.get("lock")
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
        elif stale_lock(text, -pid_field):
            lock = f"stale: {text}"
        else:
            lock = f"held: {text}"
        lines += ["LOCK", f"   {lock}"]
    swap, disk, ram = reading or machine.readings()
    swap_max, disk_min = machine.limits(config, ram)
    swap_txt = "swap ?" if swap is None else f"swap {swap:.1f} GB used{' !' if swap > swap_max else ''}"
    lines += ["MACHINE", f"   {swap_txt}   disk {disk:.1f} GB free{' !' if disk < disk_min else ''}"]
    return "\n".join(lines)


def find(name):
    row = state.connect().execute("SELECT * FROM jobs WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise SystemExit(f"mort: no job named {name!r}")
    return row


def kill(name, confirm=input):
    row = find(name)
    pid = row["pid"]
    if row["kind"] != "local":
        raise SystemExit(f"mort: {name} runs on {row['target'].split(':')[0]}; mort only reads remote jobs")
    if not pid_alive(pid):
        raise SystemExit(f"mort: {name} is not running")
    if confirm(f"stop {name} (pid {pid}, started {ago(time.time() - row['started'])} ago)? [y/N] ").strip().lower() != "y":
        return False
    # `mort run` jobs lead their own process group, so the job and its children all get the signal.
    # An adopted job shares a group with whatever started it (maybe your shell), so there mort
    # signals the process and its descendants instead: stopping `caffeinate` alone leaves the job running.
    if os.getpgid(pid) == pid:
        os.killpg(pid, signal.SIGTERM)
    else:
        for p in [pid, *descendants(pid)]:
            try:
                os.kill(p, signal.SIGTERM)
            except ProcessLookupError:
                pass
    db = state.connect()
    db.execute("UPDATE jobs SET last_event = 'died' WHERE name = ?", (name,))  # the user knows; no alert
    db.commit()
    return True


def descendants(pid):
    out = subprocess.run(["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True).stdout
    children = {}
    for line in out.splitlines():
        child, parent = map(int, line.split())
        children.setdefault(parent, []).append(child)
    found, todo = [], [pid]
    while todo:
        for child in children.get(todo.pop(), []):
            found.append(child)
            todo.append(child)
    return found


def forget(name):
    row = find(name)
    db = state.connect()
    db.execute("DELETE FROM jobs WHERE name = ?", (name,))
    db.commit()
    return row["kind"] == "local" and pid_alive(row["pid"]), row["pid"]


def notify(message, subtitle=""):
    print(f"mort: {message}" + (f": {subtitle}" if subtitle else ""), flush=True)
    if shutil.which("osascript"):
        # Text goes in as arguments, never into the script, so a job name cannot inject AppleScript.
        subprocess.run(["osascript", "-e", "on run argv", "-e",
                        'display notification (item 2 of argv) with title "mort" subtitle (item 1 of argv)',
                        "-e", "end run", message, subtitle], capture_output=True)


def check(config, notify=notify, reading=None):
    """Apply the rules once: send each new event, free a stale lock that a mort job left behind."""
    lock_cfg = config.get("lock")
    db = state.connect()
    for row in db.execute("SELECT * FROM jobs WHERE kind = 'ssh'").fetchall():
        if row["last_event"] not in ("finished", "died"):
            remote.poll(db, row)
    rows = db.execute("SELECT * FROM jobs").fetchall()
    for row in rows:
        st, detail = status(row)
        new = None if st in ("running", "unknown") else st
        if new == row["last_event"]:
            continue
        if new is not None:
            notify(f"{row['name']} {st}", detail)
        db.execute("UPDATE jobs SET last_event = ? WHERE name = ?", (new, row["name"]))
    if lock_cfg is not None:
        check_lock(db, lock_cfg, {r["pid"]: r["name"] for r in rows if r["lock"]}, notify)
    check_machine(db, config, notify, reading or machine.readings())
    db.commit()


def check_machine(db, config, notify, reading):
    swap, disk, ram = reading
    swap_max, disk_min = machine.limits(config, ram)
    active = {r["key"] for r in db.execute("SELECT key FROM alerts WHERE key IN ('swap', 'disk')")}
    on = machine_alerts(swap, disk, swap_max, disk_min, active)
    if "swap" in on - active:
        notify(f"swap high: {swap:.1f} GB used", "a job may be thrashing; it can crawl for hours")
    if "disk" in on - active:
        notify(f"disk low: {disk:.1f} GB free", f"below {disk_min:g} GB")
    db.execute("DELETE FROM alerts WHERE key IN ('swap', 'disk')")
    db.executemany("INSERT INTO alerts VALUES (?, NULL)", [(k,) for k in on])


def check_lock(db, lock_cfg, mort_pids, notify):
    path, _, pid_field = lock_settings(lock_cfg)
    warned = db.execute("SELECT value FROM alerts WHERE key = 'lock'").fetchone()
    text = path.read_text().strip() if path.exists() else ""
    if not text or not stale_lock(text, -pid_field):
        db.execute("DELETE FROM alerts WHERE key = 'lock'")
        return
    fields = text.split()
    word = fields[-pid_field] if len(fields) >= pid_field else ""
    owner = mort_pids.get(int(word)) if word.isdigit() else None
    if owner:
        path.unlink()
        notify(f"freed the lock left by {owner}", text)
    elif warned is None or warned["value"] != text:
        notify("stale lock: its process is gone", text)
        db.execute("INSERT OR REPLACE INTO alerts VALUES ('lock', ?)", (text,))
