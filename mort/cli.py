import argparse

from mort import state
from mort.run import start


def main(argv=None):
    parser = argparse.ArgumentParser(prog="mort", description="Watch long jobs and say when they die, stall or finish.")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="start a job detached and watch it")
    run.add_argument("--name", help="job name (default: the command's name)")
    run.add_argument("--lock", action="store_true", help="take the lock from config while the job runs")
    run.add_argument("--stall", type=float, default=20, metavar="MIN",
                     help="report a stall after MIN minutes without log output (default 20, 0 turns it off)")
    run.add_argument("cmd", nargs=argparse.REMAINDER, help="-- command and arguments")
    args = parser.parse_args(argv)

    if args.command == "run":
        cmd = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
        if not cmd:
            parser.error("run needs a command after --")
        lock = state.load_config().get("lock", {}) if args.lock else None
        name, pid, log = start(cmd, args.name, args.stall * 60 or None, lock)
        print(f"started {name} (pid {pid}), log {log}")
