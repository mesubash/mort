import argparse
import os
import time

from mort import daemon, github, jobs, kaggle, remote, state
from mort.run import start, track


def main(argv=None):
    parser = argparse.ArgumentParser(prog="mort", description="Watch long jobs and say when they die, stall or finish.")
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run", help="start a job detached and watch it")
    run.add_argument("--name", help="job name (default: the command's name)")
    run.add_argument("--lock", action="store_true", help="take the lock from config while the job runs")
    run.add_argument("--stall", type=float, default=20, metavar="MIN",
                     help="report a stall after MIN minutes without log output (default 20, 0 turns it off)")
    run.add_argument("cmd", nargs=argparse.REMAINDER, help="-- command and arguments")
    tr = sub.add_parser("track", help="watch something mort did not start").add_subparsers(dest="kind", required=True)
    tp = tr.add_parser("pid", help="adopt a running process")
    tp.add_argument("pid", type=int)
    tp.add_argument("--name", help="job name (default: the process name)")
    tp.add_argument("--log", help="the job's log file, for stall checks and --done")
    tp.add_argument("--stall", type=float, default=20, metavar="MIN", help="minutes without log output (default 20, 0 off)")
    tp.add_argument("--done", metavar="TEXT", help="text the log ends with on success; without it an ended job counts as died")
    ts = tr.add_parser("ssh", help="watch a STATUS file on a remote host (read-only, one ssh per check)")
    ts.add_argument("host")
    ts.add_argument("path")
    ts.add_argument("--name", help="job name (default: the folder holding the file)")
    ts.add_argument("--done", default=r"^DONE\b", metavar="REGEX", help="last line meaning success (default ^DONE)")
    ts.add_argument("--failed", default=r"^FAIL", metavar="REGEX", help="last line meaning failure (default ^FAIL)")
    tk = tr.add_parser("kaggle", help="watch a Kaggle notebook run (uses the kaggle CLI)")
    tk.add_argument("kernel", help="owner/kernel-name")
    tk.add_argument("--name", help="job name (default: the kernel name)")
    tk.add_argument("--pull", metavar="DIR", help="download the output here when it completes (empty or new folder)")
    tr.add_parser("github", help="notify on replies to your open issues and pull requests (uses gh)")
    log = sub.add_parser("log", help="show a job's log")
    log.add_argument("name")
    log.add_argument("-n", type=int, default=20, help="lines to show (default 20)")
    log.add_argument("-f", action="store_true", help="keep following the log")
    sub.add_parser("kill", help="stop a job after asking, and free its lock").add_argument("name")
    sub.add_parser("check", help="apply the rules once and send new events (the daemon runs this)")
    dm = sub.add_parser("daemon", help="run mort check every minute in the background (launchd)")
    dm.add_argument("action", choices=["install", "uninstall", "status"])
    sub.add_parser("forget", help="stop watching a job").add_argument("name")
    args = parser.parse_args(argv)
    config = state.load_config()

    if args.command == "run":
        cmd = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
        if not cmd:
            parser.error("run needs a command after --")
        lock = config.get("lock", {}) if args.lock else None
        name, pid, log = start(cmd, args.name, args.stall * 60 or None, lock)
        print(f"started {name} (pid {pid}), log {log}")
    elif args.command == "track" and args.kind == "kaggle":
        name = kaggle.track(args.kernel, args.name, args.pull)
        print(f"tracking {name} ({args.kernel}), checked every 5 minutes")
    elif args.command == "track" and args.kind == "github":
        db = state.connect()
        github.enable(db, time.time())
        db.commit()
        print("watching replies on your open issues and pull requests, checked every 5 minutes")
    elif args.command == "track" and args.kind == "ssh":
        name = remote.track(args.host, args.path, args.name, args.done, args.failed)
        print(f"tracking {name} ({args.host}:{args.path}); the daemon reads it every minute")
    elif args.command == "track":
        if args.done and not args.log:
            parser.error("--done needs --log")
        name = track(args.pid, args.name, args.log, args.stall * 60 or None, args.done)
        print(f"tracking {name} (pid {args.pid})")
    elif args.command == "log":
        row = jobs.find(args.name)
        if row["kind"] != "local":
            print(row["remote_text"] or "(nothing read yet)")
            return
        if not row["log"]:
            raise SystemExit(f"mort: {args.name} has no log; track it with --log")
        path = row["log"]
        os.execvp("tail", ["tail", "-n", str(args.n), *(["-f"] if args.f else []), path])
    elif args.command == "kill":
        if jobs.kill(args.name):
            print(f"sent stop to {args.name}; its lock is freed when it exits")
    elif args.command == "forget" and args.name == "github":
        db = state.connect()
        db.execute("DELETE FROM alerts WHERE key = 'github'")
        db.commit()
        print("stopped watching GitHub replies")
    elif args.command == "forget":
        running, pid = jobs.forget(args.name)
        print(f"forgot {args.name}" + (f"; it is still running as pid {pid}" if running else ""))
    elif args.command == "check":
        jobs.check(config)
    elif args.command == "daemon":
        if args.action == "install":
            plist, log = daemon.install()
            print(f"installed {plist}; mort check runs every 60 s, output in {log}")
        elif args.action == "uninstall":
            print("removed the launchd agent" if daemon.uninstall() else "no launchd agent was installed")
        else:
            print("daemon: running" if daemon.running() else "daemon: not installed (mort daemon install)")
    else:
        print(jobs.summary(config))
        if not daemon.running():
            print("DAEMON\n   not running, so nothing is sent; start it with: mort daemon install")
