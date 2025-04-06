"""Constants for the Symi Modbus integration."""
from typing import Final

DOMAIN: Final = "symi_modbus"
DEFAULT_HUB: Final = "symi_modbus"
DEFAULT_SCAN_INTERVAL: Final = 1
DEFAULT_PORT: Final = 8899
DEFAULT_SLAVE: Final = 0x0A
DEFAULT_TCP_PORT: Final = 502
DEFAULT_DELAY_MS: Final = 0

# Device attributes
ATTR_ADDRESS: Final = "address"
ATTR_HUB: Final = "hub"
ATTR_SLAVE: Final = "slave"
ATTR_UNIT: Final = "unit"
ATTR_VALUE: Final = "value"
ATTR_STATE: Final = "state"

# Configuration attributes
CONF_BAUDRATE: Final = "baudrate"
CONF_BYTESIZE: Final = "bytesize"
CONF_CLOSE_COMM_ON_ERROR: Final = "close_comm_on_error"
CONF_DEVICE_ADDRESS: Final = "device_address"
CONF_PARITY: Final = "parity"
CONF_RETRIES: Final = "retries"
CONF_RETRY_ON_EMPTY: Final = "retry_on_empty"
CONF_RTUOVERTCP: Final = "rtuovertcp"
CONF_SERIAL: Final = "serial"
CONF_STOPBITS: Final = "stopbits"
CONF_TCP: Final = "tcp"
CONF_UDP: Final = "udp"
CONF_WRITE_TYPE: Final = "write_type"
CONF_SWITCHS: Final = "switchs"
CONF_SOURCE_ADDRESS: Final = "source_address"

# Call types
CALL_TYPE_COIL: Final = "coil"
CALL_TYPE_DISCRETE: Final = "discrete_input"
CALL_TYPE_REGISTER_HOLDING: Final = "holding"
CALL_TYPE_REGISTER_INPUT: Final = "input"
CALL_TYPE_WRITE_COIL: Final = "write_coil"
CALL_TYPE_WRITE_COILS: Final = "write_coils"
CALL_TYPE_WRITE_REGISTER: Final = "write_register"
CALL_TYPE_WRITE_REGISTERS: Final = "write_registers"
CALL_TYPE_X_COILS: Final = "coils"
CALL_TYPE_X_REGISTER_HOLDINGS: Final = "holdings"

# Service calls
SERVICE_WRITE_COIL: Final = "write_coil"
SERVICE_WRITE_REGISTER: Final = "write_register"

# Defaults
DEFAULT_MODBUS_PORT: Final = 502

# Platforms
PLATFORMS: Final = ["switch"] 