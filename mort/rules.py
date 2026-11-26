"""Event rules. Callers pass in what they observed, so the rules can be tested with fake clocks."""
import os


def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # the process exists but belongs to another user
    return True


def job_event(alive, exit_code, last_output, now, stall_after):
    """Return 'finished', 'died', 'stalled' or None.

    exit_code is None when the job ended without writing one (killed, or adopted with `track pid`).
    last_output is the log's mtime, or the start time before the first write.
    stall_after is seconds of silence allowed; None turns stall checks off.
    """
    if not alive:
        return "finished" if exit_code == 0 else "died"
    if stall_after is not None and now - last_output > stall_after:
        return "stalled"
    return None


def stale_lock(text, pid_field, alive=pid_alive):
    """True when the lock line names a PID that no longer runs. pid_field indexes the words; negative counts from the end."""
    fields = text.split()
    if not fields:
        return False
    try:
        pid = int(fields[pid_field])
    except (IndexError, ValueError):
        return True  # another tool wrote the lock; a line with no readable PID protects nothing
    return not alive(pid)


def machine_alerts(swap_gb, disk_gb, swap_max_gb, disk_min_gb, active):
    """Return the set of machine alerts that are on: "swap", "disk".

    An alert that is already on stays on until its value is 10% clear of the limit, so a value
    hovering at the limit does not alert every minute. swap_gb is None where swap cannot be read.
    """
    on = set()
    if swap_gb is not None and (swap_gb > swap_max_gb or ("swap" in active and swap_gb > swap_max_gb * 0.9)):
        on.add("swap")
    if disk_gb < disk_min_gb or ("disk" in active and disk_gb < disk_min_gb * 1.1):
        on.add("disk")
    return on


def time_left(start_n, start_t, n, total, now):
    """Seconds left at the rate seen since start, or None before any progress."""
    if n <= start_n or now <= start_t or n >= total:
        return None
    return (total - n) * (now - start_t) / (n - start_n)
