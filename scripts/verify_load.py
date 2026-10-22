"""Check the hub under a realistic load: several slaves, one of them silent.

The script runs the integration's own hub against a simulated bus on a pseudo
terminal and reports the timing of every round, the availability per slave and
the memory growth. It never touches a real serial port.
"""

import asyncio
import gc
import os
import pty
import sys
import termios
import time

sys.path.insert(0, "/config")

from custom_components.symi_modbus.const import (  # noqa: E402
    CONF_COIL_COUNT,
    CONF_FRAME,
    CONF_NAME,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_SERIAL,
    CONF_SLAVES,
    CONF_TYPE,
    FRAME_RTU,
)
from custom_components.symi_modbus.modbus import ModbusHub  # noqa: E402

SLAVE_IDS = (0x0A, 0x0B, 0x0C, 0x0D, 0x0E)
SILENT = {0x0C}
COILS = 32
ROUNDS = 40


def crc16(data: bytes) -> bytes:
    """Return the Modbus RTU CRC of a frame body."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return bytes([crc & 0xFF, crc >> 8])


def start_simulator(link: str) -> int:
    """Start the simulated bus and return the master file descriptor."""
    master, _slave_fd = pty.openpty()
    name = os.ttyname(_slave_fd)
    with open(link, "w") as handle:
        handle.write(name)

    attrs = termios.tcgetattr(master)
    attrs[3] &= ~termios.ICANON & ~termios.ECHO
    termios.tcsetattr(master, termios.TCSANOW, attrs)

    def serve() -> None:
        buffer = bytearray()
        while True:
            try:
                chunk = os.read(master, 256)
            except OSError:
                return
            if not chunk:
                return
            buffer.extend(chunk)
            while len(buffer) >= 8:
                frame = bytes(buffer[:8])
                del buffer[:8]
                slave, function = frame[0], frame[1]
                if slave not in SLAVE_IDS or slave in SILENT:
                    continue
                if function == 0x01:
                    count = (frame[4] << 8) | frame[5]
                    packed = bytearray((count + 7) // 8)
                    if slave == SLAVE_IDS[0]:
                        packed[0] = 0x01
                    body = bytes([slave, function, len(packed)]) + bytes(packed)
                    os.write(master, body + crc16(body))
                elif function == 0x05:
                    body = bytes(frame[:6])
                    os.write(master, body + crc16(body))

    import threading

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return master


class FakeHass:
    """Minimal stand-in for the Home Assistant core object."""

    def __init__(self) -> None:
        """Prepare the event bookkeeping."""
        self.loop = asyncio.get_event_loop()

    def async_run_hass_job(self, job, *args, **kwargs):
        """Run a job the way Home Assistant does."""
        return job(*args, **kwargs)

    async def async_add_executor_job(self, func, *args):
        """Run a blocking function inline."""
        return func(*args)


class FakeEntry:
    """Minimal stand-in for a config entry."""

    def __init__(self, data: dict) -> None:
        """Store the entry data."""
        self.data = data
        self.options: dict = {}
        self.entry_id = "verify"


async def main() -> None:
    """Run the rounds and report."""
    link = "/tmp/verify_pty.txt"
    master = start_simulator(link)
    port = open(link).read().strip()
    print(f"  模拟总线: {port}")
    print(f"  从站: {', '.join(f'0x{s:02X}' for s in SLAVE_IDS)}  静默: 0x0C")
    print()

    data = {
        CONF_TYPE: CONF_SERIAL,
        CONF_NAME: "verify",
        CONF_SCAN_INTERVAL: 5,
        CONF_COIL_COUNT: COILS,
        CONF_SLAVES: {str(s): {"start": 0, "count": COILS} for s in SLAVE_IDS},
        CONF_PORT: port,
        CONF_FRAME: FRAME_RTU,
    }
    hub = ModbusHub(FakeHass(), FakeEntry(data))
    hub._config["port"] = port
    hub._connection._port = port
    await hub.async_setup()

    availability: list[tuple[bool, int]] = []
    hub.add_availability_callback(
        lambda available, slave: availability.append((available, slave))
    )

    durations: list[float] = []
    for _ in range(ROUNDS):
        start = time.monotonic()
        await hub.async_poll_slaves()
        durations.append((time.monotonic() - start) * 1000)
        await asyncio.sleep(0.2)

    print(f"  跑了 {ROUNDS} 轮，每轮间隔 0.2s")
    print(f"  单轮耗时: 最小 {min(durations):.1f} ms  中位 {sorted(durations)[len(durations) // 2]:.1f} ms  最大 {max(durations):.1f} ms")
    print(f"  含静默从站的总耗时: 最大 {max(durations):.1f} ms（静默从站 0.5s 超时 + 跳过）")
    print()

    print("  每个从站的最终可用性:")
    for slave in SLAVE_IDS:
        state = "available" if hub._slave_available.get(slave) else "unavailable"
        print(f"    0x{slave:02X}: {state}")
    print()
    print(f"  静默从站被跳过的轮次: {hub._slave_failures.get(0x0C, 0)} 次失败记录")
    print(f"  跳过后重试轮次: {hub._slave_skip_until.get(0x0C, 0)} (当前第 {hub._round} 轮)")

    # Memory check.
    gc.collect()
    before = len(gc.get_objects())
    for _ in range(20):
        await hub.async_poll_slaves()
    gc.collect()
    after = len(gc.get_objects())
    print()
    print(f"  再跑 20 轮后 Python 对象数: {before} -> {after} (差 {after - before})")

    await hub.async_stop()
    os.close(master)


asyncio.run(main())
