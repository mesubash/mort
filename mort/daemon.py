import os
import plistlib
import subprocess
import sys
from pathlib import Path

from mort import state

LABEL = "mort.check"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
UNITS = Path.home() / ".config" / "systemd" / "user"


def run(*args):
    return subprocess.run(list(args), capture_output=True, text=True)


def environment():
    # The agent's own PATH lacks Homebrew, pipx and ~/.local folders, where gh and kaggle usually live.
    return {"PYTHONPATH": str(Path(__file__).resolve().parent.parent),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")}


def install(interval=60):
    state.HOME.mkdir(exist_ok=True)
    log = state.HOME / "daemon.log"
    if sys.platform == "darwin":
        return install_launchd(interval, log)
    return install_systemd(interval, log)


def install_launchd(interval, log):
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    with open(PLIST, "wb") as f:
        plistlib.dump({"Label": LABEL, "ProgramArguments": [sys.executable, "-m", "mort", "check"],
                       "EnvironmentVariables": environment(), "StartInterval": interval, "RunAtLoad": True,
                       "StandardOutPath": str(log), "StandardErrorPath": str(log)}, f)
    domain = f"gui/{os.getuid()}"
    run("launchctl", "bootout", f"{domain}/{LABEL}")  # reinstall replaces a loaded agent
    out = run("launchctl", "bootstrap", domain, str(PLIST))
    if out.returncode != 0:
        raise SystemExit(f"mort: launchctl bootstrap failed: {out.stderr.strip()}")
    return PLIST, log


def service_text(log):
    env = "".join(f'Environment="{k}={v}"\n' for k, v in environment().items())
    return (f"[Unit]\nDescription=mort check\n\n[Service]\nType=oneshot\n{env}"
            f"ExecStart={sys.executable} -m mort check\nStandardOutput=append:{log}\nStandardError=append:{log}\n")


def timer_text(interval):
    return (f"[Unit]\nDescription=run mort check every {interval} s\n\n[Timer]\nOnBootSec=30\n"
            f"OnUnitActiveSec={interval}\nAccuracySec=5\n\n[Install]\nWantedBy=timers.target\n")


def install_systemd(interval, log):
    UNITS.mkdir(parents=True, exist_ok=True)
    (UNITS / "mort.service").write_text(service_text(log))
    (UNITS / "mort.timer").write_text(timer_text(interval))
    for args in (("daemon-reload",), ("enable", "--now", "mort.timer")):
        out = run("systemctl", "--user", *args)
        if out.returncode != 0:
            raise SystemExit(f"mort: systemctl --user {' '.join(args)} failed: {out.stderr.strip()}")
    return UNITS / "mort.timer", log


def uninstall():
    if sys.platform == "darwin":
        run("launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}")
        existed = PLIST.exists()
        PLIST.unlink(missing_ok=True)
        return existed
    run("systemctl", "--user", "disable", "--now", "mort.timer")
    existed = (UNITS / "mort.timer").exists()
    for unit in ("mort.timer", "mort.service"):
        (UNITS / unit).unlink(missing_ok=True)
    run("systemctl", "--user", "daemon-reload")
    return existed


def running():
    if sys.platform == "darwin":
        return run("launchctl", "print", f"gui/{os.getuid()}/{LABEL}").returncode == 0
    return run("systemctl", "--user", "is-active", "--quiet", "mort.timer").returncode == 0
