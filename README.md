<p align="center">
  <img src="docs/mort.svg" width="180" alt="mort: a small ghost peeking over a terminal">
</p>

<h1 align="center">mort</h1>

<p align="center">
  Holds on to every long job you start, and tells you when one dies, stalls or finishes.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/status-v0.1%20local-yellowgreen" alt="Status: v0.1 local">
  <img src="https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/dependencies-none-3fb950" alt="No dependencies">
  <img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT license">
</p>

<p align="center">
  <a href="#what-it-catches">What it catches</a> ·
  <a href="#usage">Usage</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#roadmap">Roadmap</a> ·
  <a href="docs/PLAN.md">Full plan</a>
</p>

---

Training runs, data jobs, scrapers, remote scripts and hosted notebooks run in different places, and most of them report nothing when they go wrong. mort is a small background program that watches all of them and speaks up only when something changes.

## What it catches

| Event | When |
| --- | --- |
| died | the process is gone without success, a STATUS file says failed, or a notebook errors |
| finished | exit code 0, a STATUS file says done, or a notebook completes |
| stalled | the log has not been written for a set time, or a number such as `loss=` stops changing |
| machine | swap above a set share, or free disk below a set size |
| stale lock | a lock file names a process that no longer runs |
| reply | someone answers your open pull request or issue |

Each event is sent once.

## Usage

Local jobs work now (macOS, Python 3.11+). There is no package yet, so run it from a clone:

```console
$ git clone https://github.com/mesubash/mort && cd mort
$ alias mort="PYTHONPATH=$PWD python3 -m mort"
$ mort daemon install                       # check every 60 s in the background
$ mort run --name train --lock -- python train.py
started train (pid 4242), log ~/.mort/logs/train.log
$ mort track pid 5151 --log run.log --done "Training complete"
$ mort
JOBS
 * train     running   3h10m, output 12s ago
 x prep      died      02:14 (exit 1)
ok eval      finished  14:05 (exit 0)
LOCK
   held: train 4242 2026-11-25_10:30
```

| Command | What it does |
| --- | --- |
| `mort run [--name N] [--lock] [--stall MIN] [--watch RE] -- CMD` | start a job detached and awake, log it, take the lock if asked |
| `mort track pid PID [--log FILE] [--done TEXT] [--watch RE]` | watch a process mort did not start; `--done` is the log text that means success |
| `mort track ssh HOST PATH [--done RE] [--failed RE]` | watch a STATUS file on a remote host, read-only |
| `mort track kaggle OWNER/KERNEL [--pull DIR]` | watch a Kaggle notebook run, download its output into an empty folder when done |
| `mort track github` | notify when someone else comments on or reviews your open issues and pull requests |
| `mort` | jobs, lock, and a warning if the daemon is off |
| `mort log NAME [-n 50] [-f]` | show or follow a job's log |
| `mort kill NAME` | ask, then stop the job and its child processes; its lock is freed |
| `mort forget NAME` | stop watching a job |
| `mort daemon install \| uninstall \| status` | the launchd agent that runs `mort check` every minute |

A job can be alive and still stuck: swapping, or training that stopped improving. `--watch` names a number in the log that must keep changing; if it stays the same for `--stall` minutes, mort reports a stall even while the log keeps growing. The last matching line is shown as progress, with time left when it holds a count like `12/50`:

```console
$ mort run --name train --stall 30 --watch 'loss=([0-9.]+)' -- python train.py
$ mort
JOBS
 * train   running   1h02m, epoch 14/40 loss=0.48, ~1h55m left
```

The lock is a one-line file that other tools can read too. Set it in `~/.mort/config.toml`:

```toml
[lock]
path = "~/.mort/lock"
format = "{name} {pid} {start}"    # also {cwd}; words before {pid} may contain spaces
```

Remote jobs are read over ssh, one read-only `tail` per minute, with your own ssh config and keys. The last line of the file decides: `DONE` is finished, `FAIL…` is died, and both can be changed:

```console
$ mort track ssh my-server /jobs/prep/STATUS
$ mort track ssh my-server /jobs/seeds/STATUS --done '^s2 DONE'
```

Replies to your open issues and pull requests, through your `gh` login, checked every 5 minutes:

```console
$ mort track github
```

Kaggle notebook runs, through your `kaggle` CLI, checked every 5 minutes; the output is downloaded when the run completes:

```console
$ mort track kaggle user/my-kernel --pull runs/my-kernel
```

## How it works

- A background agent checks every 60 seconds and sends a notification on each new event.
- Watchers call tools you already have (`ssh`, `kaggle`, `gh`). mort stores no passwords or tokens.
- State is one SQLite file in `~/.mort/`, and config is `~/.mort/config.toml`.
- Checks are read-only. mort never kills or deletes anything without asking.
- The core uses only the Python standard library.

## Roadmap

- [x] **v0.1** local jobs: `mort run`, process and log watchers, lock file, macOS notifications
- [ ] **v0.2** remote: ssh STATUS files, Kaggle, GitHub replies, swap and disk (built; in trial use)
- [ ] **v0.3** stall rules: a number that must keep changing, progress line, time left (built; in trial use)
- [ ] **v1.0** public release: phone push, Homebrew, PyPI, Linux

Details and later ideas are in [docs/PLAN.md](docs/PLAN.md).

## License

[MIT](LICENSE)
