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


def parse_meminfo(text):
    """(swap used GB, RAM GB) from Linux /proc/meminfo, whose values are in kB."""
    kb = {k: int(v.split()[0]) for k, v in (line.split(":", 1) for line in text.splitlines() if ":" in line)}
    return (kb["SwapTotal"] - kb["SwapFree"]) / 1024 ** 2, kb["MemTotal"] / 1024 ** 2


def readings():
    """(swap used GB or None, free disk GB, RAM GB or None)."""
    disk = shutil.disk_usage(Path.home()).free / GB
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        swap, ram = parse_meminfo(meminfo.read_text())
        return swap, disk, ram
    ram = sysctl("hw.memsize")
    return parse_swap(sysctl("vm.swapusage")), disk, int(ram) / GB if ram else None


def limits(config, ram_gb):
    m = config.get("machine", {})
    return m.get("swap_max_gb", (ram_gb or 16) / 2), m.get("disk_min_gb", 4)
