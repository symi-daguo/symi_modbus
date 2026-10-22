"""Tests for the Symi Modbus frame encoding and decoding."""
from __future__ import annotations

import pytest

from custom_components.symi_modbus.const import FRAME_MBAP, FRAME_RTU
from custom_components.symi_modbus.frames import (
    FUNCTION_READ_COILS,
    FUNCTION_WRITE_MULTIPLE_COILS,
    FUNCTION_WRITE_SINGLE_COIL,
    build_read_request,
    build_write_coil_request,
    build_write_multiple_coils_request,
    crc16_fn,
    decode_response,
    expected_response_length,
    parse_coil_bits,
)


def test_crc16_known_vector() -> None:
    """CRC16 of a documented request frame matches the Modbus spec."""
    # Modbus spec example: slave 0x01, func 0x03, addr 0x0000, qty 0x0001
    assert crc16_fn([0x01, 0x03, 0x00, 0x00, 0x00, 0x01]) == [0x84, 0x0A]


def test_rtu_read_request_frame() -> None:
    """RTU read request carries slave, function, address, count and CRC."""
    frame = build_read_request(0x0A, FUNCTION_READ_COILS, 0, 32, FRAME_RTU)
    assert len(frame) == 8
    assert frame[:6] == bytes([0x0A, 0x01, 0x00, 0x00, 0x00, 0x20])
    assert frame[-2:] == bytes(crc16_fn(frame[:-2]))


def test_mbap_read_request_frame() -> None:
    """MBAP read request carries the MBAP header and no CRC."""
    frame = build_read_request(0x0A, FUNCTION_READ_COILS, 0, 32, FRAME_MBAP, transaction_id=7)
    # The length field counts the unit identifier plus the PDU (1 + 5 = 6).
    assert frame[:7] == bytes([0x00, 0x07, 0x00, 0x00, 0x00, 0x06, 0x0A])
    assert len(frame) == 6 + 6
    assert frame[7] == FUNCTION_READ_COILS
    assert frame[8:] == bytes([0x00, 0x00, 0x00, 0x20])


def test_write_coil_request_value_bytes() -> None:
    """FC05 encodes ON as 0xFF00 and OFF as 0x0000."""
    on_frame = build_write_coil_request(1, 5, True, FRAME_RTU)
    assert on_frame[:6] == bytes([0x01, 0x05, 0x00, 0x05, 0xFF, 0x00])
    off_frame = build_write_coil_request(1, 5, False, FRAME_RTU)
    assert off_frame[:6] == bytes([0x01, 0x05, 0x00, 0x05, 0x00, 0x00])


def test_write_coil_high_address_uses_two_bytes() -> None:
    """Coil addresses above 255 are encoded big-endian on two bytes."""
    frame = build_write_coil_request(1, 300, True, FRAME_RTU)
    assert frame[2:4] == bytes([0x01, 0x2C])


def test_write_multiple_coils_packs_bits() -> None:
    """FC15 packs coil values into bytes, LSB first."""
    frame = build_write_multiple_coils_request(1, 0, [True, False, True], FRAME_RTU)
    assert frame[6] == 1  # byte count
    assert frame[7] == 0b00000101


def test_expected_length_mbap() -> None:
    """MBAP response length comes from the length field."""
    assert expected_response_length(b"\x00\x01\x00\x00", FRAME_MBAP, FUNCTION_READ_COILS) is None
    assert expected_response_length(b"\x00\x01\x00\x00\x00\x03", FRAME_MBAP, FUNCTION_READ_COILS) == 9


def test_expected_length_rtu_read() -> None:
    """RTU read response length is slave + func + byte count + data + CRC."""
    assert expected_response_length(b"\x0a\x01", FRAME_RTU, FUNCTION_READ_COILS) is None
    assert expected_response_length(b"\x0a\x01\x04", FRAME_RTU, FUNCTION_READ_COILS) == 9


def test_expected_length_rtu_exception() -> None:
    """An RTU exception response is a fixed five byte frame."""
    assert expected_response_length(b"\x0a\x81\x02", FRAME_RTU, FUNCTION_READ_COILS) == 5


def test_expected_length_rtu_write_single() -> None:
    """An FC05 response is a fixed eight byte frame."""
    assert expected_response_length(b"\x0a\x05\x00", FRAME_RTU, FUNCTION_WRITE_SINGLE_COIL) == 8


def test_decode_response_rejects_bad_crc() -> None:
    """A corrupted RTU frame is rejected."""
    frame = bytearray(build_read_request(0x0A, FUNCTION_READ_COILS, 0, 32, FRAME_RTU))
    frame[-1] ^= 0xFF
    assert decode_response(bytes(frame), FRAME_RTU) is None


def test_decode_response_rtu_roundtrip() -> None:
    """A valid RTU response decodes into slave, function and payload."""
    payload = bytes([0x04, 0xFF, 0x00, 0x00, 0x00])
    frame = bytes([0x0A, FUNCTION_READ_COILS]) + payload + bytes(crc16_fn(bytes([0x0A, FUNCTION_READ_COILS]) + payload))
    decoded = decode_response(frame, FRAME_RTU)
    assert decoded is not None
    slave, function, body = decoded
    assert (slave, function) == (0x0A, FUNCTION_READ_COILS)
    assert body == payload


def test_decode_response_mbap_roundtrip() -> None:
    """A valid MBAP response decodes into slave, function and payload."""
    body = bytes([0x04, 0xFF, 0x00])
    # length field counts unit id (1) + function (1) + body (3) = 5
    frame = bytes([0x00, 0x09, 0x00, 0x00, 0x00, 0x05, 0x0A, FUNCTION_READ_COILS]) + body
    decoded = decode_response(frame, FRAME_MBAP)
    assert decoded is not None
    slave, function, payload = decoded
    assert (slave, function) == (0x0A, FUNCTION_READ_COILS)
    assert payload == body


def test_expected_length_mbap_response() -> None:
    """MBAP response length counts the unit id and the PDU, with no CRC."""
    # length = unit id (1) + function (1) + byte count (1) + 4 data bytes = 7
    prefix = bytes([0x00, 0x09, 0x00, 0x00, 0x00, 0x07])
    assert expected_response_length(prefix, FRAME_MBAP, FUNCTION_READ_COILS) == 13


def test_parse_coil_bits_lsb_first() -> None:
    """Coil bits are read least significant bit first."""
    states = parse_coil_bits(bytes([0b00000101]), 3)
    assert states == {0: True, 1: False, 2: True}


def test_parse_coil_bits_truncates_short_payload() -> None:
    """A payload shorter than the requested count does not raise."""
    states = parse_coil_bits(bytes([0xFF]), 32)
    assert len(states) == 8


@pytest.mark.parametrize("frame", [FRAME_MBAP, FRAME_RTU])
def test_read_request_roundtrip(frame: str) -> None:
    """Both frame formats build without raising."""
    assert build_read_request(10, FUNCTION_READ_COILS, 0, 16, frame)
    assert build_write_multiple_coils_request(10, 0, [True, False], frame)
