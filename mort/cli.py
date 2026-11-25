import argparse
import os

from mort import jobs, state
from mort.run import start


def main(argv=None):
    parser = argparse.ArgumentParser(prog="mort", description="Watch long jobs and say when they die, stall or finish.")
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run", help="start a job detached and watch it")
    run.add_argument("--name", help="job name (default: the command's name)")
    run.add_argument("--lock", action="store_true", help="take the lock from config while the job runs")
    run.add_argument("--stall", type=float, default=20, metavar="MIN",
                     help="report a stall after MIN minutes without log output (default 20, 0 turns it off)")
    run.add_argument("cmd", nargs=argparse.REMAINDER, help="-- command and arguments")
    log = sub.add_parser("log", help="show a job's log")
    log.add_argument("name")
    log.add_argument("-n", type=int, default=20, help="lines to show (default 20)")
    log.add_argument("-f", action="store_true", help="keep following the log")
    sub.add_parser("kill", help="stop a job after asking, and free its lock").add_argument("name")
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
    elif args.command == "log":
        path, _ = state.job_files(jobs.find(args.name)["name"])
        os.execvp("tail", ["tail", "-n", str(args.n), *(["-f"] if args.f else []), str(path)])
    elif args.command == "kill":
        if jobs.kill(args.name):
            print(f"sent stop to {args.name}; its lock is freed when it exits")
    elif args.command == "forget":
        running, pid = jobs.forget(args.name)
        print(f"forgot {args.name}" + (f"; it is still running as pid {pid}" if running else ""))
    else:
        print(jobs.summary(config.get("lock")))
