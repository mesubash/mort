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
    """True when the lock line names a PID that no longer runs. pid_field is the 0-based field index."""
    fields = text.split()
    if not fields:
        return False
    try:
        pid = int(fields[pid_field])
    except (IndexError, ValueError):
        return True  # another tool wrote the lock; a line with no readable PID protects nothing
    return not alive(pid)
