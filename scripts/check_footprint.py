"""Report the runtime footprint of Home Assistant on the host.

Shows the resident memory of the Home Assistant container and how fast the
log file grows, so a long running install can be checked.
"""

import subprocess
import sys
import time
from pathlib import Path

LOG = Path("/config/home-assistant.log")
INTERVAL = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
SAMPLES = int(sys.argv[2]) if len(sys.argv) > 2 else 3


def container_rss_mb() -> float:
    """Return the resident memory of the Home Assistant container in MB."""
    try:
        result = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", "homeassistant"],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
    except Exception:  # noqa: BLE001
        return 0.0

    usage = result.stdout.strip().split()[0]
    for unit in ("GiB", "MiB", "KiB", "GB", "MB", "KB"):
        if usage.endswith(unit):
            value = float(usage[: -len(unit)])
            if unit in ("GiB", "GB"):
                return value * 1024
            if unit in ("MiB", "MB"):
                return value
            return value / 1024
    return 0.0


def log_size() -> int:
    """Return the size of the Home Assistant log file in bytes."""
    try:
        return LOG.stat().st_size
    except OSError:
        return 0


def main() -> None:
    """Sample the footprint over time."""
    print("  时间              容器内存(MB)   日志(KB)    增长(KB/min)")
    start = time.time()
    start_log = log_size()
    rss_start = container_rss_mb()

    for _ in range(SAMPLES):
        time.sleep(INTERVAL)
        now = time.time()
        size = log_size()
        rss = container_rss_mb()
        minutes = (now - start) / 60
        growth = (size - start_log) / 1024 / minutes if minutes else 0
        print(
            f"  {time.strftime('%H:%M:%S'):18s} {rss:9.1f}   {size / 1024:9.1f}   {growth:9.2f}"
        )

    print()
    print(f"  内存变化  : {container_rss_mb() - rss_start:+.1f} MB")
    print(f"  日志增长  : {(log_size() - start_log) / 1024:.1f} KB / {INTERVAL * SAMPLES / 60:.1f} min")


if __name__ == "__main__":
    main()
