"""Modbus device simulator used to verify the integration end to end.

Serves a Modbus RTU slave on a pseudo terminal (so it looks like a serial
device to Home Assistant) and optionally on a TCP port. The slave keeps the
coil state in memory and accepts write coil requests.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import pty
import struct
import sys
import termios
from typing import Optional

SLAVE_ID = 0x0A
COIL_COUNT = 16

FUNCTION_READ_COILS = 0x01
FUNCTION_WRITE_SINGLE_COIL = 0x05


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


class Slave:
    """A Modbus RTU slave with 16 coils."""

    def __init__(self, slave_id: int = SLAVE_ID, coils: int = COIL_COUNT) -> None:
        """Prepare the coil state."""
        self.slave_id = slave_id
        self.state = [False] * coils
        self.requests = 0
        self.writes: list[tuple[int, bool]] = []
        # Every slave that answers on this connection.
        self.slave_ids = {slave_id}
        self.slave_states = {slave_id: self.state}

    def add_slave(self, slave_id: int, coils: int = COIL_COUNT) -> None:
        """Let another slave answer on the same connection."""
        self.slave_ids.add(slave_id)
        self.slave_states[slave_id] = [False] * coils

    def handle(self, frame: bytes) -> bytes | None:
        """Answer one request frame."""
        if len(frame) < 3:
            return None
        self.requests += 1
        slave = frame[0]
        function = frame[1]
        if slave not in self.slave_ids:
            return None
        state = self.slave_states[slave]

        if function == FUNCTION_READ_COILS:
            address = (frame[2] << 8) | frame[3]
            count = (frame[4] << 8) | frame[5]
            packed = bytearray((count + 7) // 8)
            for index in range(count):
                coil = address + index
                if 0 <= coil < len(state) and state[coil]:
                    packed[index // 8] |= 1 << (index % 8)
            body = bytes([slave, function, len(packed)]) + bytes(packed)
            return body + crc16(body)

        if function == FUNCTION_WRITE_SINGLE_COIL:
            address = (frame[2] << 8) | frame[3]
            value = frame[4] == 0xFF
            if 0 <= address < len(state):
                state[address] = value
                self.writes.append((address, value))
            body = bytes(frame[:6])
            return body + crc16(body)

        return None


def _read_exactly(fd: int, size: int, buffer: bytearray) -> bytes:
    """Read a complete frame from the descriptor."""
    while len(buffer) < size:
        try:
            chunk = os.read(fd, 256)
        except OSError:
            return b""
        if not chunk:
            return b""
        buffer.extend(chunk)

    frame = bytes(buffer[:size])
    del buffer[:size]
    return frame


def serve_pty(slave: Slave, link: str) -> None:
    """Serve the slave on a pseudo terminal."""
    master, slave_fd = pty.openpty()
    name = os.ttyname(slave_fd)
    with open(link, "w") as handle:
        handle.write(name)

    # Raw mode so the bytes arrive unmodified.
    attrs = termios.tcgetattr(master)
    attrs[3] &= ~termios.ICANON & ~termios.ECHO
    termios.tcsetattr(master, termios.TCSANOW, attrs)

    buffer = bytearray()
    print(f"pty slave on {name} (link {link})", flush=True)

    while True:
        try:
            chunk = os.read(master, 256)
        except OSError:
            break
        if not chunk:
            break
        buffer.extend(chunk)

        # RTU request: slave, func, addr(2), qty(2) -> 8 bytes.
        while len(buffer) >= 8:
            frame = bytes(buffer[:8])
            del buffer[:8]
            response = slave.handle(frame)
            if response:
                os.write(master, response)


async def serve_tcp(slave: Slave, port: int) -> None:
    """Serve the slave on a TCP port using RTU framing."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        buffer = bytearray()
        try:
            while True:
                chunk = await reader.read(256)
                if not chunk:
                    return
                buffer.extend(chunk)
                while len(buffer) >= 8:
                    frame = bytes(buffer[:8])
                    del buffer[:8]
                    response = slave.handle(frame)
                    if response:
                        writer.write(response)
                        await writer.drain()
        except (asyncio.CancelledError, ConnectionResetError):
            return
        finally:
            writer.close()

    server = await asyncio.start_server(handle, "0.0.0.0", port)
    print(f"tcp slave on 127.0.0.1:{port}", flush=True)
    async with server:
        await server.serve_forever()


def main() -> None:
    """Run the simulator."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--pty-link", help="Write the pty device path to this file")
    parser.add_argument("--tcp-port", type=int, help="Also serve on this TCP port")
    parser.add_argument(
        "--extra-slaves",
        type=int,
        nargs="*",
        default=[],
        help="Additional slave ids that answer on the same connection",
    )
    args = parser.parse_args()

    slave = Slave()
    for extra in args.extra_slaves:
        slave.add_slave(extra)

    if args.pty_link:
        serve_pty(slave, args.pty_link)

    if args.tcp_port:
        asyncio.run(serve_tcp(slave, args.tcp_port))
    else:
        while True:
            try:
                slave.requests = 0
                import time

                time.sleep(5)
            except KeyboardInterrupt:
                break


if __name__ == "__main__":
    main()
