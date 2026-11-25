<p align="center">
  <img src="docs/mort.svg" width="180" alt="mort: a small ghost peeking over a terminal">
</p>

<h1 align="center">mort</h1>

<p align="center">
  Holds on to every long job you start, and tells you when one dies, stalls or finishes.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/status-phase%201-orange" alt="Status: phase 1">
  <img src="https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/dependencies-none-3fb950" alt="No dependencies">
  <img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT license">
</p>

<p align="center">
  <a href="#what-it-catches">What it catches</a> ·
  <a href="#how-it-will-look">How it will look</a> ·
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

## How it will look

> Planned commands. Phase 1 is in progress; nothing below runs yet.

```console
$ mort run --name train --lock -- python train.py
$ mort track ssh my-server /jobs/prep/STATUS
$ mort track kaggle user/my-kernel --pull runs/
$ mort
JOBS
 x train         local   died 02:14 (exit 1)
 * prep          ssh     running 3h10m   STATUS: step 8/20
 ok my-kernel    kaggle  done 14:05      output pulled to runs/
MACHINE
   swap 1.1/8 GB   disk 38 GB free   lock: free
```

## How it works

- A background agent checks every 60 seconds and sends a notification on each new event.
- Watchers call tools you already have (`ssh`, `kaggle`, `gh`). mort stores no passwords or tokens.
- State is one SQLite file in `~/.mort/`, and config is `~/.mort/config.toml`.
- Checks are read-only. mort never kills or deletes anything without asking.
- The core uses only the Python standard library.

## Roadmap

- [ ] **v0.1** local jobs: `mort run`, process and log watchers, lock file, macOS notifications
- [ ] **v0.2** remote: ssh STATUS files, Kaggle, GitHub replies, swap and disk
- [ ] **v0.3** stall rules: a number that must keep changing, progress line, time left
- [ ] **v1.0** public release: phone push, Homebrew, PyPI, Linux

Details and later ideas are in [docs/PLAN.md](docs/PLAN.md).

## License

[MIT](LICENSE)
