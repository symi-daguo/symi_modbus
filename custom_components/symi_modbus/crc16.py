"""Modbus RTU CRC16 (polynomial 0xA001, initial 0xFFFF)."""


def crc16_fn(data: list[int]) -> list[int]:
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
