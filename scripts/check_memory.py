"""Watch the memory of the Home Assistant process over time.

Reports the resident memory of the process itself, so the page cache of the
container does not blur the result.
"""

import sys
import time
from pathlib import Path

INTERVAL = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
SAMPLES = int(sys.argv[2]) if len(sys.argv) > 2 else 16


def find_ha_pid() -> int:
    """Return the pid of the Home Assistant process."""
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().decode(errors="ignore")
        except OSError:
            continue
        if "-m" in cmdline and "homeassistant" in cmdline:
            return int(entry.name)
    return 0


def rss_mb(pid: int) -> float:
    """Return the resident memory of the process in MB."""
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    except OSError:
        pass
    return 0.0


def objects_mb(pid: int) -> float:
    """Return the size of the heap in MB, which shows a leak early."""
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmData:"):
                return int(line.split()[1]) / 1024
    except OSError:
        pass
    return 0.0


def main() -> None:
    """Sample the memory of the process over time."""
    pid = find_ha_pid()
    if not pid:
        print("  没有找到 Home Assistant 进程")
        return

    print(f"  Home Assistant pid={pid}")
    print("  时间            RSS(MB)    数据段(MB)")
    start = time.time()
    rss_start = rss_mb(pid)
    data_start = objects_mb(pid)
    peak = rss_start

    for index in range(SAMPLES):
        time.sleep(INTERVAL)
        rss = rss_mb(pid)
        peak = max(peak, rss)
        print(
            f"  t+{int(time.time() - start):4d}s   {rss:8.1f}   {objects_mb(pid):9.1f}",
            flush=True,
        )

    print()
    print(f"  起始 RSS   : {rss_start:.1f} MB")
    print(f"  结束 RSS   : {rss_mb(pid):.1f} MB")
    print(f"  峰值 RSS   : {peak:.1f} MB")
    print(f"  净变化     : {rss_mb(pid) - rss_start:+.1f} MB / {INTERVAL * SAMPLES / 60:.0f} min")
    print(f"  数据段变化 : {objects_mb(pid) - data_start:+.1f} MB")


if __name__ == "__main__":
    main()
