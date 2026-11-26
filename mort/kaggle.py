import re
import subprocess
import time
from pathlib import Path

from mort import state
from mort.run import check_free

SLUG = re.compile(r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+")
INTERVAL = 300  # Kaggle rate limits
STATES = {"QUEUED": "running", "RUNNING": "running", "COMPLETE": "finished", "ERROR": "died",
          "CANCEL_REQUESTED": "died", "CANCEL_ACKNOWLEDGED": "died"}


def kaggle(*args, timeout=120):
    """Run the kaggle CLI. mort never reads the user's Kaggle token; the CLI does."""
    try:
        out = subprocess.run(["kaggle", *args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "kaggle timed out"
    except OSError as e:
        return None, f"cannot run kaggle: {e.strerror}"
    if out.returncode != 0:
        return None, (out.stderr.strip() or out.stdout.strip() or "kaggle failed").splitlines()[-1][:200]
    return out.stdout, None


def read_status(slug):
    out, error = kaggle("kernels", "status", slug, timeout=60)
    if error:
        return None, error
    m = re.search(r"KernelWorkerStatus\.([A-Z_]+)", out)
    return (m.group(1), None) if m else (None, f"unexpected reply: {out.strip()[:100]}")


def track(slug, name=None, pull=None):
    if not SLUG.fullmatch(slug):
        raise SystemExit(f"mort: kernel must look like owner/kernel-name, got {slug!r}")
    if pull is not None:
        pull = Path(pull).expanduser().resolve()
        if pull.exists() and (not pull.is_dir() or any(pull.iterdir())):
            raise SystemExit(f"mort: --pull needs an empty or new folder; {pull} has files")
    name = name or slug.split("/")[1]
    db = state.connect()
    check_free(db, name)
    db.execute("INSERT OR REPLACE INTO jobs (name, pid, cmd, started, kind, target, pull)"
               " VALUES (?, NULL, ?, ?, 'kaggle', ?, ?)",
               (name, f"kaggle {slug}", time.time(), slug, str(pull) if pull else None))
    db.commit()
    return name


def poll(db, job, now):
    if job["tried_at"] and now - job["tried_at"] < INTERVAL:
        return
    word, error = read_status(job["target"])
    if error:
        db.execute("UPDATE jobs SET remote_error = ?, tried_at = ? WHERE name = ?", (error, now, job["name"]))
    else:
        db.execute("UPDATE jobs SET remote_text = ?, remote_error = NULL, remote_at = ?, tried_at = ? WHERE name = ?",
                   (word, now, now, job["name"]))


def status(job, now):
    if job["remote_at"] is None:
        return "unknown", f"not read yet{': ' + job['remote_error'] if job['remote_error'] else ''}"
    word = job["remote_text"]
    st = STATES.get(word, "unknown")
    detail = f"Kaggle: {word.lower()}, read {int(now - job['remote_at']) // 60}m ago"
    if job["remote_error"]:
        detail += f", last try failed: {job['remote_error']}"
    return st, detail


def pull_output(job):
    """Download a finished kernel's output into its empty --pull folder. Returns a line for the notification."""
    dest = Path(job["pull"])
    if dest.exists() and any(dest.iterdir()):
        return f"output not pulled: {dest} is no longer empty"
    dest.mkdir(parents=True, exist_ok=True)
    _, error = kaggle("kernels", "output", job["target"], "-p", str(dest), "-q", timeout=1800)
    return f"output pull failed: {error}" if error else f"output in {dest}"
