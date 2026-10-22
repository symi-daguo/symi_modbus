"""Constants for the Symi Modbus integration."""
from typing import Final

DOMAIN: Final = "symi_modbus"

# Re-exported from homeassistant.const so the rest of the integration has a
# single import source.
CONF_DELAY: Final = "delay"
CONF_HOST: Final = "host"
CONF_NAME: Final = "name"
CONF_PORT: Final = "port"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_SLAVE: Final = "slave"
CONF_TYPE: Final = "type"

DEFAULT_NAME: Final = "Symi Modbus"
DEFAULT_SCAN_INTERVAL: Final = 1
DEFAULT_TCP_PORT: Final = 502
DEFAULT_SLAVE: Final = 0x0A
DEFAULT_DELAY_MS: Final = 0
DEFAULT_COIL_COUNT: Final = 32
MAX_COIL_COUNT: Final = 64

# Connection types
CONF_TCP: Final = "tcp"
CONF_SERIAL: Final = "serial"

# Configuration attributes
CONF_BAUDRATE: Final = "baudrate"
CONF_BYTESIZE: Final = "bytesize"
CONF_COIL_COUNT: Final = "coil_count"
CONF_FRAME: Final = "frame"
CONF_PARITY: Final = "parity"
CONF_SLAVES: Final = "slaves"
CONF_STOPBITS: Final = "stopbits"
CONF_WRITE_TYPE: Final = "write_type"
CONF_METHOD: Final = "method"

# Frame formats
FRAME_MBAP: Final = "mbap"
FRAME_RTU: Final = "rtu"

# Serial methods
METHOD_RTU: Final = "rtu"
METHOD_ASCII: Final = "ascii"

# Write types
WRITE_SINGLE: Final = "single"
WRITE_MULTIPLE: Final = "multiple"

# Config flow: user picks this value to enter a serial device path manually.
SERIAL_PORT_MANUAL_VALUE: Final = "__symi_modbus_manual_serial_path__"

ADD_MORE_SLAVES: Final = "add_more_slaves"

# Subentry types. Every part of an installation is a subentry of the config
# entry, so the user can add, change and remove them on their own.
SUBENTRY_SLAVE: Final = "slave"
SUBENTRY_PANEL: Final = "panel"
SUBENTRY_LINKAGE: Final = "linkage"

# Panel configuration
CONF_BRAND: Final = "brand"
CONF_BUTTONS: Final = "buttons"
CONF_PANEL_IDS: Final = "panel_ids"

# Linkage configuration
CONF_PANEL_ENTITIES: Final = "panel_entities"
CONF_RELAY_ENTITIES: Final = "relay_entities"

# Panel brands
BRAND_SYMI: Final = "symi"
BRAND_CLOWIRE: Final = "clowire"
BRAND_LF: Final = "lf"

# Number of buttons a panel has, the limit of every supported brand.
MAX_PANEL_BUTTONS: Final = 8

# Service call attributes
ATTR_ADDRESS: Final = "address"
ATTR_HUB: Final = "hub"
ATTR_SLAVE: Final = "slave"
ATTR_STATE: Final = "state"
ATTR_VALUE: Final = "value"

# Service calls
SERVICE_WRITE_COIL: Final = "write_coil"
SERVICE_WRITE_REGISTER: Final = "write_register"

# Platforms
PLATFORMS: Final = ["switch"]
