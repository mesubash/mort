import re
import shutil
import subprocess
from pathlib import Path

GB = 1024 ** 3


def sysctl(name):
    out = subprocess.run(["sysctl", "-n", name], capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else None


def parse_swap(text):
    """Used swap in GB from `sysctl vm.swapusage` text, e.g. 'total = 2048.00M  used = 503.12M ...'."""
    m = re.search(r"used = ([\d.]+)([MG])", text or "")
    if not m:
        return None
    return float(m.group(1)) / (1024 if m.group(2) == "M" else 1)


def readings():
    """(swap used GB or None, free disk GB, RAM GB or None)."""
    ram = sysctl("hw.memsize")
    return parse_swap(sysctl("vm.swapusage")), shutil.disk_usage(Path.home()).free / GB, int(ram) / GB if ram else None


def limits(config, ram_gb):
    m = config.get("machine", {})
    return m.get("swap_max_gb", (ram_gb or 16) / 2), m.get("disk_min_gb", 4)
