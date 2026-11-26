import re
import shlex
import subprocess
import time
from pathlib import PurePosixPath

from mort import state
from mort.run import check_free

HOST = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._@-]*")  # never starts with "-", so it cannot pass ssh an option
BACKOFF = 300


def read(host, path, timeout=20):
    """Last lines of a remote file with one read-only ssh command: (text, error). Missing file is ("", None)."""
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host, "tail -n 5 -- " + shlex.quote(path)]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "ssh timed out"
    if out.returncode == 255:
        return None, out.stderr.strip().splitlines()[-1] if out.stderr.strip() else "ssh failed"
    if out.returncode != 0:
        return "", None  # the job has not written its STATUS file yet
    return out.stdout, None


def track(host, path, name=None, done=r"^DONE\b", failed=r"^FAIL"):
    if not HOST.fullmatch(host):
        raise SystemExit(f"mort: bad host {host!r}")
    for pattern in (done, failed):
        try:
            re.compile(pattern)
        except re.error as e:
            raise SystemExit(f"mort: bad pattern {pattern!r}: {e}")
    name = name or re.sub(r"[^A-Za-z0-9._-]", "-", PurePosixPath(path).parent.name or host)
    db = state.connect()
    check_free(db, name)
    db.execute("INSERT OR REPLACE INTO jobs (name, pid, cmd, started, kind, target, done_marker, failed_marker)"
               " VALUES (?, NULL, ?, ?, 'ssh', ?, ?, ?)",
               (name, f"ssh {host} {path}", time.time(), f"{host}:{path}", done, failed))
    db.commit()
    return name


def poll(db, job, now=None):
    """Read the remote file unless the host failed less than BACKOFF seconds ago."""
    now = now or time.time()
    if job["remote_error"] and job["tried_at"] and now - job["tried_at"] < BACKOFF:
        return
    host, path = job["target"].split(":", 1)
    text, error = read(host, path)
    if error:
        db.execute("UPDATE jobs SET remote_error = ?, tried_at = ? WHERE name = ?", (error, now, job["name"]))
    else:
        db.execute("UPDATE jobs SET remote_text = ?, remote_error = NULL, remote_at = ?, tried_at = ? WHERE name = ?",
                   (text, now, now, job["name"]))


def status(job, now):
    """(state, detail) from what the daemon last read: running, finished, died or unknown."""
    lines = [l for l in (job["remote_text"] or "").splitlines() if l.strip()]
    last = lines[-1].strip() if lines else ""
    if job["remote_at"] is None:
        return "unknown", f"not read yet{': ' + job['remote_error'] if job['remote_error'] else ''}"
    if last and re.search(job["failed_marker"], last):
        return "died", f"STATUS: {last}"
    if last and re.search(job["done_marker"], last):
        return "finished", f"STATUS: {last}"
    age = int(now - job["remote_at"])
    seen = f"read {age // 60}m ago" if age >= 60 else "read just now"
    if job["remote_error"]:
        seen += f", host unreachable: {job['remote_error']}"
    return "running", f"STATUS: {last or '(none yet)'}, {seen}"
