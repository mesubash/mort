import os
import plistlib
import subprocess
import sys
from pathlib import Path

from mort import state

LABEL = "mort.check"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def launchctl(*args):
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def install(interval=60):
    state.HOME.mkdir(exist_ok=True)
    log = str(state.HOME / "daemon.log")
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    with open(PLIST, "wb") as f:
        plistlib.dump({
            "Label": LABEL,
            "ProgramArguments": [sys.executable, "-m", "mort", "check"],
            # ponytail: runs from this checkout; switch to the installed `mort` command once packaged
            # launchd's own PATH lacks Homebrew and pipx folders, where gh and kaggle usually live.
            "EnvironmentVariables": {"PYTHONPATH": str(Path(__file__).resolve().parent.parent),
                                     "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")},
            "StartInterval": interval,
            "RunAtLoad": True,
            "StandardOutPath": log,
            "StandardErrorPath": log,
        }, f)
    domain = f"gui/{os.getuid()}"
    launchctl("bootout", f"{domain}/{LABEL}")  # reinstall replaces a loaded agent
    out = launchctl("bootstrap", domain, str(PLIST))
    if out.returncode != 0:
        raise SystemExit(f"mort: launchctl bootstrap failed: {out.stderr.strip()}")
    return PLIST, log


def uninstall():
    launchctl("bootout", f"gui/{os.getuid()}/{LABEL}")
    existed = PLIST.exists()
    PLIST.unlink(missing_ok=True)
    return existed


def running():
    return launchctl("print", f"gui/{os.getuid()}/{LABEL}").returncode == 0
