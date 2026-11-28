# mort plan

Status: planning, nothing built yet. Last updated 2026-11-25.

## The problem

People who run long jobs (model training, data processing, scrapers, cron jobs) start them in several places: their own laptop, a shared server over ssh, a hosted notebook such as Kaggle, and CI. Each place reports trouble differently, and most report nothing at all. The person ends up checking by hand, and finds out late when something went wrong:

- A job crashes at night and is found in the morning, after hours of lost compute.
- A job keeps running but makes no progress: the machine is swapping, or training has stopped improving. The process is alive, so nothing reports a failure.
- A remote job finishes, and its output sits on the server until someone logs in.
- A hosted notebook fails in its first minutes, while its owner believes it is running.
- A lock file that says "a heavy job is running" outlives the job that wrote it, and the next job waits for nothing.
- A reviewer answers a pull request, and the notification email is buried.

mort is a small background program that holds on to every long job you start, wherever it runs, and tells you only when something changes: the job died, stalled, finished, or needs you.

## Who it is for

1. The author first: one Mac, one shared ssh server, Kaggle notebooks, open pull requests on GitHub.
2. Then ML students and researchers in the same position: a laptop, a lab server, free hosted GPUs, no operations team.
3. Later, small teams who want the same view of shared jobs.

## Existing tools and the gap

| Tool | What it covers | What it misses |
| --- | --- | --- |
| Healthchecks.io, Cronitor, Dead Man's Snitch | Scheduled jobs that send a ping on success | Jobs that are alive but stuck; local processes; hosted notebooks; job output |
| Weights & Biases alerts | Training metrics, if the code calls its SDK | The machine (swap, disk), remote STATUS files, notebooks without the SDK |
| ntfy, `noti`, `terminal-notifier` | A message when a command ends | Stalls, remote jobs, locks, follow-up actions |
| GitHub notifications | Everything on GitHub, mixed together | Filtering to "a person answered my open pull request" |

The gap mort fills: one place for every long job a person owns, across machines and services, that notices a stuck job, not only a dead one. This gap comes from the author's own use. Whether other people need it is tested in phase 4 below, not assumed.

## How it works

```
 mort run / mort track ──► state (SQLite, ~/.mort/state.db)
                                  ▲
 launchd agent, every 60 s ──► watchers ──► rules ──► notifier
   (or `mort daemon`)        local process        dead, stalled,      macOS notification,
                             log file             finished,           ntfy push,
                             ssh file             swap/disk,          terminal summary
                             Kaggle kernel        new reply
                             GitHub PR
```

- One Python package. The core uses the standard library only (`subprocess`, `sqlite3`, `tomllib`, `argparse`, `os`). A dependency is added only when a phase needs one.
- Watchers call tools the user already has (`ssh`, `kaggle`, `gh`). mort stores no passwords or tokens of its own.
- State is a single SQLite file, so the CLI and the background agent share it.
- Config is `~/.mort/config.toml`. Nothing personal goes in the repository.
- Each check is read-only. mort never kills, deletes or changes anything unless the user confirms.

### Commands (target for v1.0)

| Command | What it does |
| --- | --- |
| `mort run [--name N] [--lock] [--stall RULE] -- <cmd>` | Starts a job detached and kept awake (`nohup` + `caffeinate` on macOS), logs to `~/.mort/logs/N.log`, takes the lock if asked, and releases it when the job ends |
| `mort track ssh <host> <path>` | Watches a STATUS or log file on a remote host |
| `mort track kaggle <owner/kernel> [--pull DIR]` | Watches a Kaggle kernel and downloads its output when it completes |
| `mort track pid <pid>` | Adopts a process that was started without mort |
| `mort` | One screen: jobs, machine health, lock, replies waiting |
| `mort log <name>` | Tail a job's log |
| `mort kill <name>` | Stops a job after confirmation, releases its lock |
| `mort forget <name>` | Stops watching |
| `mort daemon install` / `uninstall` | Adds or removes the launchd agent |

### What counts as an event

| Event | Rule |
| --- | --- |
| died | process gone without a success marker, or STATUS says failed, or Kaggle says error |
| finished | process exited 0, or STATUS says done, or Kaggle says complete |
| stalled | log not written for N minutes (default 20), or a matched number (for example `loss=`) unchanged for N minutes |
| machine | swap above a set share, free disk below a set size |
| stale lock | lock file names a PID that no longer runs |
| reply | a new comment or review by someone else on the user's open pull requests or issues |

Each event is sent once. Repeats are folded into the summary screen.

## Phases

Each phase ends with something usable. The next phase starts only after the current one has been used for real.

### Phase 1: v0.1, clings locally (about 1 week)

- `mort run`, `mort track pid`, `mort`, `mort log`, `mort kill`, `mort forget`.
- Local watchers: process alive (`os.kill(pid, 0)`), exit code, log file growth.
- Lock file: configurable path and format, taken by `mort run --lock`, released on exit, stale-lock warning.
- macOS notification through `osascript`.
- `mort daemon install`: launchd agent checking every 60 s.
- Tests: one small test file covering the rules (died, finished, stalled, stale lock) with fake clocks and files.

Done when: a real training run started with `mort run` sends a notification when it ends, and the lock is released after a crash.

### Phase 2: v0.2, remote and services (about 1 week)

- ssh watcher: reads a remote file with one `ssh host cat` (or `tail`) per check, with a timeout.
- Kaggle watcher: `kaggle kernels status`, then `kaggle kernels output` into an empty folder on completion.
- GitHub watcher: open pull requests and issues by the user through `gh api`, new comments or reviews by others since the last check.
- Machine watcher: swap (`sysctl vm.swapusage`) and free disk.

Done when: one ssh job, one Kaggle run and one pull request reply are each reported without manual checking.

### Phase 3: v0.3, stall detection (about 1 week)

- Per-job stall rules: a regex that captures a number, and a time window in which it must change.
- Progress line in the summary (for example, last epoch and loss) from the same regex.
- Rough time-left estimate from progress lines, shown only when the pattern gives a total (for example `epoch 12/50`).

Done when: a deliberately frozen job is reported as stalled within its window, and a healthy job never is during a week of use.

### Phase 4: personal test, then public v1.0

Pass rule, fixed before use: after two weeks of daily use, mort has reported at least one failure or reply that would otherwise have been missed, and the author still runs it every day. If yes, continue to public release. If no, park the project and record why.

Public release work:
- ntfy push to a phone, with an optional "kill" action link.
- Homebrew tap (`brew install <user>/tap/mort`) and a PyPI package.
- Linux support: systemd user timer in place of launchd, `notify-send` in place of `osascript`, `/proc/meminfo` for swap.
- README with a 30-second demo GIF, a config reference and one example per watcher.
- Second test, fixed before release: within 30 days of posting (Show HN, r/MachineLearning, r/LocalLLaMA, relevant Discords), at least 100 GitHub stars or 25 people who say they run it. Below that, keep it as a personal tool and stop public work.

## Later versions

Ideas recorded for after v1.0, in rough order. Each one waits for a request from a real user.

| Version | Feature |
| --- | --- |
| v1.1 | More job sources: Google Colab (through a small cell snippet that writes a heartbeat), SLURM (`squeue`, `sacct`), Docker containers, GitHub Actions runs |
| v1.2 | Cloud GPUs: RunPod, Lambda, Vast.ai, Modal; warn when a paid machine sits idle after its job ended, since that costs money |
| v1.3 | Menu-bar view: start as a SwiftBar/xbar plugin that prints `mort` output, a native app only if the plugin is not enough |
| v1.4 | Terminal UI (`mort watch`) with live progress for all jobs |
| v1.5 | Daily digest: one message each morning with what finished, failed and is still waiting |
| v1.6 | Machine-readable status for other tools (editors, scripts, coding assistants): first `mort status --json` (name, kind, state, last event, pull folder), so an assistant can read what finished or died at the start of a session without querying `state.db`; then a local HTTP endpoint and MCP server if that is not enough |
| v2.0 | Hosted relay (paid): phone app or web page that works when the laptop is closed, shared view for a lab or small team, history of runs. The CLI stays free and open |

### Disk: why (requested by the first user, 2026-11-26; build order not set)

The low-disk warning says that space is low but not why. On the author's Mac, about 30 GB came back within nine days of a cleanup, almost all of it in a package manager's cache filled by one-off training environments. Finding that took an hour by hand. mort already knows the machine and the jobs, so it can say where the space went. mort still deletes nothing; cleaning stays with other tools.

1. Growth in the warning: once a day, record the size of a short list of heavy folders (package caches, model caches, container data, project folders, Downloads; configurable). When free disk drops below the limit, the notification names the folders that grew most, e.g. `disk 3.6 GB free · package cache +31 GB this week`.
2. Disk used per job: record free disk when a job starts and ends, and add the difference to its finished or died notice, e.g. `train finished · used 4.2 GB disk`.
3. A hint, never an action: the warning can name a command that would free the space (a cache prune, a cleaner tool), for the user to run.

Done when: on the author's Mac, a real low-disk warning names the folder that caused it, and one real training job reports its disk use.

## Income path

The CLI is free under the MIT license. Income comes later, only if public use passes the phase 4 test, from the hosted relay in v2.0: a paid monthly plan for people who want alerts while their laptop is off and teams who share servers. Payment providers that pay out to the author's country are being checked separately; the hosted plan does not start until one is confirmed.

## Not planned

- Scheduling or queuing jobs. Other tools do this (cron, SLURM, task runners), and mort only watches.
- Acting without confirmation, such as killing a job automatically.
- Cleaning disk space or deleting files. mort reports where space went; cleaner tools do the deleting.
- Collecting usage data.
- A plugin system before three outside contributors ask for the same kind of watcher.

## Risks

| Risk | Answer |
| --- | --- |
| ssh checks every 60 s load a shared server | one short command per check, longer interval option, back off when the host is unreachable |
| Kaggle or GitHub rate limits | check those every 5 minutes by default |
| Too many alerts, so the user ignores them | each event once, quiet hours, digest mode |
| Laptop asleep means no checks | stated in the README; the v2.0 relay is the answer for people who need it |
| The name and the cartoon lemur | the name is the French word for death; no character art or show names are used |
