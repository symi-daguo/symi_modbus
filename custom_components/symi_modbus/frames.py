"""Modbus frame encoding and decoding (MBAP / RTU)."""
from __future__ import annotations

from .const import FRAME_MBAP, FRAME_RTU

FUNCTION_READ_COILS: int = 0x01
FUNCTION_READ_DISCRETE_INPUTS: int = 0x02
FUNCTION_READ_HOLDING_REGISTERS: int = 0x03
FUNCTION_READ_INPUT_REGISTERS: int = 0x04
FUNCTION_WRITE_SINGLE_COIL: int = 0x05
FUNCTION_WRITE_SINGLE_REGISTER: int = 0x06
FUNCTION_WRITE_MULTIPLE_COILS: int = 0x0F
FUNCTION_WRITE_MULTIPLE_REGISTERS: int = 0x10

MBAP_HEADER_LENGTH: int = 7
MBAP_PROTOCOL_ID: int = 0x0000

# RTU responses whose length is fixed regardless of the payload.
_RTU_FIXED_LENGTH: dict[int, int] = {
    FUNCTION_WRITE_SINGLE_COIL: 8,
    FUNCTION_WRITE_SINGLE_REGISTER: 8,
}


def crc16_fn(data: bytes | list[int]) -> list[int]:
    """Return CRC16 low byte, high byte for Modbus RTU frame (excluding CRC)."""
    crc16 = 0xFFFF
    poly = 0xA001
    for byte in data:
        crc16 ^= byte
        for _ in range(8):
            if crc16 & 1:
                crc16 = (crc16 >> 1) ^ poly
            else:
                crc16 >>= 1
    return [crc16 & 0xFF, crc16 >> 8]


def _registers_to_bytes(registers: list[int]) -> list[int]:
    """Encode registers as big-endian byte pairs."""
    payload: list[int] = []
    for register in registers:
        payload.extend(((register >> 8) & 0xFF, register & 0xFF))
    return payload


def build_read_request(
    slave: int, function: int, address: int, count: int, frame: str, transaction_id: int = 0
) -> bytes:
    """Build a Modbus read request frame."""
    pdu = [
        slave,
        function,
        (address >> 8) & 0xFF,
        address & 0xFF,
        (count >> 8) & 0xFF,
        count & 0xFF,
    ]
    return _wrap_pdu(pdu, frame, transaction_id)


def build_write_coil_request(
    slave: int, address: int, value: bool, frame: str, transaction_id: int = 0
) -> bytes:
    """Build a write-single-coil (FC05) request frame."""
    pdu = [
        slave,
        FUNCTION_WRITE_SINGLE_COIL,
        (address >> 8) & 0xFF,
        address & 0xFF,
        0xFF if value else 0x00,
        0x00,
    ]
    return _wrap_pdu(pdu, frame, transaction_id)


def build_write_multiple_coils_request(
    slave: int, address: int, values: list[bool], frame: str, transaction_id: int = 0
) -> bytes:
    """Build a write-multiple-coils (FC15) request frame."""
    byte_count = (len(values) + 7) // 8
    packed = bytearray(byte_count)
    for index, value in enumerate(values):
        if value:
            packed[index // 8] |= 1 << (index % 8)

    pdu = [
        slave,
        FUNCTION_WRITE_MULTIPLE_COILS,
        (address >> 8) & 0xFF,
        address & 0xFF,
        (len(values) >> 8) & 0xFF,
        len(values) & 0xFF,
        byte_count,
    ]
    pdu.extend(packed)
    return _wrap_pdu(pdu, frame, transaction_id)


def build_write_register_request(
    slave: int, address: int, value: int, frame: str, transaction_id: int = 0
) -> bytes:
    """Build a write-single-register (FC06) request frame."""
    pdu = [
        slave,
        FUNCTION_WRITE_SINGLE_REGISTER,
        (address >> 8) & 0xFF,
        address & 0xFF,
        (value >> 8) & 0xFF,
        value & 0xFF,
    ]
    return _wrap_pdu(pdu, frame, transaction_id)


def build_write_multiple_registers_request(
    slave: int, address: int, values: list[int], frame: str, transaction_id: int = 0
) -> bytes:
    """Build a write-multiple-registers (FC16) request frame."""
    payload = _registers_to_bytes(values)
    pdu = [
        slave,
        FUNCTION_WRITE_MULTIPLE_REGISTERS,
        (address >> 8) & 0xFF,
        address & 0xFF,
        (len(values) >> 8) & 0xFF,
        len(values) & 0xFF,
        len(payload),
    ]
    pdu.extend(payload)
    return _wrap_pdu(pdu, frame, transaction_id)


def _wrap_pdu(pdu: list[int], frame: str, transaction_id: int) -> bytes:
    """Wrap a PDU in the transport frame.

    The PDU list starts with the slave (unit) identifier, matching the layout
    used on the wire for both MBAP and RTU.
    """
    if frame == FRAME_MBAP:
        # MBAP length counts the unit identifier plus the PDU that follows it.
        length = len(pdu)
        header = [
            (transaction_id >> 8) & 0xFF,
            transaction_id & 0xFF,
            (MBAP_PROTOCOL_ID >> 8) & 0xFF,
            MBAP_PROTOCOL_ID & 0xFF,
            (length >> 8) & 0xFF,
            length & 0xFF,
        ]
        return bytes(header + pdu)
    crc = crc16_fn(pdu)
    return bytes(pdu + crc)


def expected_response_length(prefix: bytes, frame: str, function: int) -> int | None:
    """Return the total response length given the bytes read so far.

    Returns None when more bytes are needed to determine the length.
    """
    if frame == FRAME_MBAP:
        if len(prefix) < 6:
            return None
        length = (prefix[4] << 8) | prefix[5]
        # 6 bytes of MBAP header + the length field counts unit id + PDU.
        return 6 + length

    # RTU framing: slave(1) func(1) ... crc(2)
    if len(prefix) < 2:
        return None
    response_function = prefix[1]
    if response_function & 0x80:
        # Exception response: slave, func|0x80, exception code, crc(2)
        return 5
    if response_function in _RTU_FIXED_LENGTH:
        return _RTU_FIXED_LENGTH[response_function]
    if len(prefix) < 3:
        return None
    # Read response: slave, func, byte_count, data(byte_count), crc(2)
    return 3 + prefix[2] + 2


def expected_request_length(prefix: bytes, frame: str) -> int | None:
    """Return the total request length given the bytes read so far.

    Requests have a different layout than responses, so they get their own
    length rule. Returns None when more bytes are needed.
    """
    if frame == FRAME_MBAP:
        if len(prefix) < 6:
            return None
        length = (prefix[4] << 8) | prefix[5]
        return 6 + length

    # RTU requests are addressed by function code:
    # read: slave, func, addr(2), qty(2), crc(2)  -> 8 bytes
    # write single: slave, func, addr(2), value(2), crc(2) -> 8 bytes
    # write multiple: slave, func, addr(2), qty(2), byte_count, data, crc(2)
    if len(prefix) < 2:
        return None
    function = prefix[1]
    if function in (
        FUNCTION_WRITE_MULTIPLE_COILS,
        FUNCTION_WRITE_MULTIPLE_REGISTERS,
    ):
        if len(prefix) < 7:
            return None
        return 7 + prefix[6] + 2
    return 8


def decode_response(frame_bytes: bytes, frame: str) -> tuple[int, int, bytes] | None:
    """Decode a response frame into (slave, function, payload).

    The payload excludes the slave id, the function code and the CRC. Returns
    None when the frame is incomplete or the CRC does not match.
    """
    if frame == FRAME_MBAP:
        if len(frame_bytes) < 8:
            return None
        length = (frame_bytes[4] << 8) | frame_bytes[5]
        # Modbus TCP carries no CRC: the frame is header(6) + unit id(1) + PDU.
        # The length field counts the unit id plus the PDU, so the payload runs
        # from index 8 up to 6 + length.
        if len(frame_bytes) < 6 + length:
            return None
        slave = frame_bytes[6]
        function = frame_bytes[7]
        return slave, function, frame_bytes[8 : 6 + length]

    if len(frame_bytes) < 5:
        return None
    expected = crc16_fn(frame_bytes[:-2])
    if frame_bytes[-2] != expected[0] or frame_bytes[-1] != expected[1]:
        return None
    return frame_bytes[0], frame_bytes[1], frame_bytes[2:-2]


def parse_coil_bits(payload: bytes, count: int) -> dict[int, bool]:
    """Parse a read-coils payload into {coil_offset: state}."""
    states: dict[int, bool] = {}
    for index in range(count):
        byte_index = index // 8
        if byte_index >= len(payload):
            break
        states[index] = bool(payload[byte_index] >> (index % 8) & 0x01)
    return states


def parse_registers(payload: bytes, count: int) -> list[int]:
    """Parse a read-registers payload into a list of integers."""
    registers: list[int] = []
    for index in range(count):
        offset = index * 2
        if offset + 1 >= len(payload):
            break
        registers.append((payload[offset] << 8) | payload[offset + 1])
    return registers
