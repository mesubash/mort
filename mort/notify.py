import json
import shutil
import subprocess
import urllib.request
from datetime import datetime

from mort import state


def desktop(message, subtitle=""):
    if shutil.which("osascript"):
        # Text goes in as arguments, never into the script, so a job name cannot inject AppleScript.
        subprocess.run(["osascript", "-e", "on run argv", "-e",
                        'display notification (item 2 of argv) with title "mort" subtitle (item 1 of argv)',
                        "-e", "end run", message, subtitle], capture_output=True)
    elif shutil.which("notify-send"):
        subprocess.run(["notify-send", "--app-name=mort", f"mort: {message}", subtitle], capture_output=True)


def phone(ntfy, message, subtitle=""):
    """Push through ntfy, as JSON to the server's root URL (docs.ntfy.sh/publish). Failure is printed, never raised."""
    body = {"topic": ntfy["topic"], "title": f"mort: {message}", "message": subtitle or message, "tags": ["ghost"]}
    req = urllib.request.Request(ntfy.get("server", "https://ntfy.sh").rstrip("/") + "/", method="POST",
                                 data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    if ntfy.get("token"):
        req.add_header("Authorization", f"Bearer {ntfy['token']}")
    try:
        urllib.request.urlopen(req, timeout=10).close()
    except OSError as e:
        print(f"mort: ntfy push failed: {e}", flush=True)


def in_quiet(spec, now):
    """True when now (a datetime) falls in spec "HH:MM-HH:MM", which may wrap past midnight."""
    if not spec:
        return False
    start, end = (int(a) * 60 + int(b) for a, b in (t.split(":") for t in spec.split("-")))
    minute = now.hour * 60 + now.minute
    return start <= minute < end if start <= end else minute >= start or minute < end


def make(config, now=datetime.now):
    """The notify(message, subtitle) used by mort check: prints, then desktop and phone, or holds it in quiet hours."""
    ntfy = config.get("ntfy", {})
    quiet = config.get("notify", {}).get("quiet")
    held = state.HOME / "held.jsonl"

    def send(message, subtitle=""):
        desktop(message, subtitle)
        if ntfy.get("topic"):
            phone(ntfy, message, subtitle)

    def notify(message, subtitle=""):
        print(f"mort: {message}" + (f": {subtitle}" if subtitle else ""), flush=True)
        if in_quiet(quiet, now()):
            with open(held, "a") as f:
                f.write(json.dumps([message, subtitle]) + "\n")
        else:
            send(message, subtitle)

    def flush():
        """After quiet hours, send what was held as one digest."""
        if in_quiet(quiet, now()) or not held.exists():
            return
        events = [json.loads(line) for line in held.read_text().splitlines() if line.strip()]
        held.unlink()
        if events:
            send(f"{len(events)} event{'s' * (len(events) > 1)} during quiet hours",
                 "; ".join(m for m, _ in events)[:250])

    notify.flush = flush
    return notify
