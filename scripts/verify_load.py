"""Check the hub and the panel bus under a realistic load.

The script runs the integration's own hub against a simulated bus on a pseudo
terminal and reports the timing of every round, the availability per slave and
the memory growth. It never touches a real serial port.

Two scenarios are covered:

* the Modbus side with several slaves, one of them silent
* the panel side with a burst of button presses from many panels
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
    CONF_SLAVE,
    CONF_TYPE,
    FRAME_RTU,
    SUBENTRY_SLAVE,
)
from custom_components.symi_modbus.modbus import ModbusHub  # noqa: E402
from custom_components.symi_modbus.panels.symi import SymiProtocol  # noqa: E402

SLAVE_IDS = (0x0A, 0x0B, 0x0C, 0x0D, 0x0E)
SILENT = {0x0C}
COILS = 32
ROUNDS = 40

# The scale the integration has to stay stable at: a hundred switches on the
# Modbus side and four hundred buttons on the panel side.
SCALE_SLAVES = (0x0A, 0x0B, 0x0C, 0x0D)
SCALE_PANELS = 50
SCALE_BUTTONS = 8


def crc16(data: bytes) -> bytes:
    """Return the Modbus RTU CRC of a frame body."""
    crc = 0xFFFF
    poly = 0xA001
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ poly
            else:
                crc >>= 1
    return bytes([crc & 0xFF, crc >> 8])


def start_simulator(link: str, slave_ids: tuple[int, ...]) -> int:
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
                if slave not in slave_ids or slave in SILENT:
                    continue
                if function == 0x01:
                    count = (frame[4] << 8) | frame[5]
                    packed = bytearray((count + 7) // 8)
                    if slave == slave_ids[0]:
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
        target = getattr(job, "target", job)
        kwargs.pop("background", None)
        return target(*args, **kwargs)

    async def async_add_executor_job(self, func, *args):
        """Run a blocking function inline."""
        return func(*args)


class FakeSubentry:
    """Minimal stand-in for a config subentry."""

    def __init__(self, data: dict) -> None:
        """Store the data of the subentry."""
        self.data = data
        self.subentry_id = "verify"
        self.subentry_type = SUBENTRY_SLAVE
        self.title = "verify"


class FakeEntry:
    """Minimal stand-in for a config entry."""

    def __init__(self, data: dict, slaves: dict[int, int]) -> None:
        """Store the entry data."""
        self.data = data
        self.options: dict = {}
        self.entry_id = "verify"
        self._slaves = slaves

    def get_subentries_of_type(self, subentry_type: str) -> list[FakeSubentry]:
        """Return the slaves of this entry as subentries."""
        if subentry_type != SUBENTRY_SLAVE:
            return []
        return [
            FakeSubentry(
                {
                    CONF_SLAVE: slave,
                    "start": 0,
                    CONF_COIL_COUNT: count,
                }
            )
            for slave, count in self._slaves.items()
        ]


async def run_hub(
    slave_ids: tuple[int, ...], coils: int, scan_interval: float, rounds: int
) -> tuple[ModbusHub, list[float]]:
    """Run the hub against the simulator and report the round timings."""
    link = "/tmp/verify_pty.txt"
    master = start_simulator(link, slave_ids)
    port = open(link).read().strip()
    print(f"  模拟总线: {port}")
    print(f"  从站: {', '.join(f'0x{s:02X}' for s in slave_ids)}  静默: 0x0C")
    print()

    data = {
        CONF_TYPE: CONF_SERIAL,
        CONF_NAME: "verify",
        CONF_SCAN_INTERVAL: scan_interval,
        CONF_COIL_COUNT: coils,
        CONF_PORT: port,
        CONF_FRAME: FRAME_RTU,
    }
    hub = ModbusHub(FakeHass(), FakeEntry(data, {s: coils for s in slave_ids}))
    hub._connection._port = port
    await hub.async_setup()

    durations: list[float] = []
    for _ in range(rounds):
        start = time.monotonic()
        await hub.async_poll_slaves()
        durations.append((time.monotonic() - start) * 1000)
        await asyncio.sleep(0.05)

    print(f"  跑了 {rounds} 轮")
    print(
        f"  单轮耗时: 最小 {min(durations):.1f} ms  "
        f"中位 {sorted(durations)[len(durations) // 2]:.1f} ms  最大 {max(durations):.1f} ms"
    )
    print(f"  每台从站的轮询间隔: {scan_interval / len(slave_ids):.3f} 秒")
    print()

    print("  每个从站的最终可用性:")
    for slave in slave_ids:
        state = "available" if hub._slave_available.get(slave) else "unavailable"
        print(f"    0x{slave:02X}: {state}")
    print()

    gc.collect()
    before = len(gc.get_objects())
    for _ in range(20):
        await hub.async_poll_slaves()
    gc.collect()
    after = len(gc.get_objects())
    print(f"  再跑 20 轮后 Python 对象数: {before} -> {after} (差 {after - before})")

    await hub.async_stop()
    os.close(master)
    return hub, durations


async def run_panel_burst() -> None:
    """Feed a burst of button presses and report the handling time."""
    protocol = SymiProtocol()
    frames = bytearray()
    for panel in range(1, SCALE_PANELS + 1):
        for button in range(1, SCALE_BUTTONS + 1):
            frames += protocol.build_led_frame(panel, button, True)

    events = 0
    start = time.monotonic()
    for _ in range(10):
        parsed = protocol.parse_frames(bytes(frames))
        events += len(parsed)
    elapsed = time.monotonic() - start

    print(f"  面板数: {SCALE_PANELS}  每面板按键: {SCALE_BUTTONS}")
    print(f"  一次突发包含 {len(frames)} 字节、{SCALE_PANELS * SCALE_BUTTONS} 个按键")
    print(f"  解析 10 轮共 {events} 个按键事件，耗时 {elapsed * 1000:.1f} ms")
    print(f"  单个事件平均耗时 {elapsed / events * 1e6:.1f} µs")

    gc.collect()
    before = len(gc.get_objects())
    for _ in range(10):
        protocol.parse_frames(bytes(frames))
    gc.collect()
    after = len(gc.get_objects())
    print(f"  再解析 10 轮后 Python 对象数: {before} -> {after} (差 {after - before})")


async def main() -> None:
    """Run the scenarios."""
    print("=== 场景一：多从站，其中一台静默 ===")
    await run_hub(SLAVE_IDS, COILS, 5, ROUNDS)

    print()
    print("=== 场景二：一百个开关的规模（4 台从站 × 32 线圈，1 秒一轮）===")
    await run_hub(SCALE_SLAVES, 32, 1, 40)

    print()
    print("=== 场景三：四百个按钮的规模 ===")
    await run_panel_burst()


asyncio.run(main())
