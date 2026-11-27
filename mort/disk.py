"""Where disk space went: daily sizes of heavy folders, growth over a week, and hints. mort never deletes."""
import os
import subprocess
import sys
import time
from pathlib import Path

from mort import state

KB_PER_GB = 1024 ** 2
DAY = 86400
CANDIDATES = ["~/.cache", "~/Library/Caches", "~/Library/Containers/com.docker.docker", "~/.docker",
              "~/Downloads", "~/.conda", "~/miniconda3/pkgs", "~/anaconda3/pkgs", "~/.ollama",
              "~/Library/Developer", "~/.gradle", "~/.m2", "~/.npm", "~/.local/share",
              "~/Developer", "~/Projects", "~/code", "~/src"]
# Commands that free space in folders mort recognises, shown as hints for the user to run.
HINTS = {"uv": "uv cache clean", "pip": "pip cache purge", "huggingface": "huggingface-cli delete-cache",
         "Homebrew": "brew cleanup --prune=all", "pkgs": "conda clean --all", ".npm": "npm cache clean --force",
         "com.docker.docker": "docker system prune", ".docker": "docker system prune",
         "pypoetry": "poetry cache clear --all .", "DerivedData": "rm -rf ~/Library/Developer/Xcode/DerivedData"}

SCHEMA = "CREATE TABLE IF NOT EXISTS disk_sizes (path TEXT, at REAL, kb INTEGER)"


def folders(config):
    """The folders to measure: [disk] folders from config, else the candidates that exist."""
    chosen = config.get("disk", {}).get("folders", CANDIDATES)
    return [str(Path(f).expanduser()) for f in chosen if Path(f).expanduser().is_dir()]


def parse_du(text):
    """{path: kB} from `du -k -d 1` output; one line per entry, 'kB<TAB>path'."""
    sizes = {}
    for line in text.splitlines():
        kb, _, path = line.partition("\t")
        if kb.strip().isdigit() and path:
            sizes[path] = int(kb)
    return sizes


def measure(paths, timeout=600):
    """{path: kB} for each folder and its direct children. A folder that times out is skipped."""
    sizes = {}
    for p in paths:
        try:
            out = subprocess.run(["du", "-k", "-d", "1", p], capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            continue
        sizes.update(parse_du(out.stdout))  # du exits non-zero on unreadable subfolders but still reports the rest
    return sizes


def record(db, sizes, now):
    db.execute(SCHEMA)
    db.executemany("INSERT INTO disk_sizes VALUES (?, ?, ?)", [(p, now, kb) for p, kb in sizes.items()])
    db.execute("DELETE FROM disk_sizes WHERE at < ?", (now - 30 * DAY,))


def due(db, now):
    db.execute(SCHEMA)
    last = db.execute("SELECT MAX(at) FROM disk_sizes").fetchone()[0]
    return last is None or now - last > 20 * 3600


def growth(db, now, days=7):
    """[(path, grown kB)] over the last `days`, largest first, naming the folder that grew, not its parent."""
    db.execute(SCHEMA)
    rows = db.execute("SELECT path, at, kb FROM disk_sizes WHERE at >= ? ORDER BY at", (now - days * DAY,)).fetchall()
    first, last = {}, {}
    for path, at, kb in rows:
        first.setdefault(path, (at, kb))
        last[path] = (at, kb)
    grown = {p: last[p][1] - first[p][1] for p in last if last[p][0] - first[p][0] >= DAY / 2}
    ranked = sorted(((p, kb) for p, kb in grown.items() if kb > 0), key=lambda x: -x[1])
    # Drop a folder when one child explains most of its growth, so the notice says ~/.cache/uv, not ~/.cache.
    explained = {p for p, kb in ranked
                 if any(c.startswith(p + os.sep) and ckb >= 0.7 * kb for c, ckb in ranked)}
    return [(p, kb) for p, kb in ranked if p not in explained]


def hint(path):
    """The command for the innermost folder name mort knows, e.g. com.docker.docker/Data -> docker system prune."""
    for part in reversed(Path(path).parts):
        if part in HINTS:
            return HINTS[part]
    return None


def short(path):
    home = str(Path.home())
    return "~" + path[len(home):] if path.startswith(home) else path


def why(db, now, top=2, min_gb=1.0):
    """'~/.cache/uv +31 GB this week (uv cache clean)' for the folders that grew most, or ''."""
    parts = []
    for path, kb in growth(db, now)[:top]:
        if kb / KB_PER_GB < min_gb:
            break
        h = hint(path)
        parts.append(f"{short(path)} +{kb / KB_PER_GB:.0f} GB this week" + (f" ({h})" if h else ""))
    return "; ".join(parts)


def start_measure():
    """Measure in a separate process, so the minute check is never held up by du."""
    log = open(state.HOME / "daemon.log", "a")
    subprocess.Popen([sys.executable, "-m", "mort", "disk", "--measure"], stdin=subprocess.DEVNULL, stdout=log,
                     stderr=log, start_new_session=True, env=dict(os.environ, PYTHONPATH=str(Path(__file__).parent.parent)))


def report(db, now):
    """Lines for `mort disk`: the biggest measured folders, growth this week, and hints."""
    db.execute(SCHEMA)
    latest = db.execute("SELECT MAX(at) FROM disk_sizes").fetchone()[0]
    if latest is None:
        return ["no sizes yet; run: mort disk --measure"]
    rows = db.execute("SELECT path, kb FROM disk_sizes WHERE at = ? ORDER BY kb DESC", (latest,)).fetchall()
    tops = [(p, kb) for p, kb in rows if not any(p.startswith(q + os.sep) for q, _ in rows if q != p)]
    kids = [(p, kb) for p, kb in rows if (p, kb) not in tops]
    lines = [f"measured {int((now - latest) // 3600)}h ago", "BIGGEST"]
    lines += [f"   {kb / KB_PER_GB:6.1f} GB  {short(p)}" + (f"   ({hint(p)})" if hint(p) else "")
              for p, kb in sorted(kids, key=lambda x: -x[1])[:8]]
    grew = growth(db, now)
    lines.append("GREW THIS WEEK")
    lines += [f"   +{kb / KB_PER_GB:5.1f} GB  {short(p)}" for p, kb in grew[:5] if kb >= KB_PER_GB / 10] or ["   nothing over 0.1 GB yet (needs a few days of sizes)"]
    return lines
