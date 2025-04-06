"""Symi Modbus integration."""
import asyncio
import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from pymodbus.client.sync import ModbusSerialClient, ModbusTcpClient, ModbusUdpClient
from pymodbus.constants import Defaults
from pymodbus.exceptions import ModbusException
from pymodbus.transaction import ModbusRtuFramer, ModbusAsciiFramer
from pymodbus.pdu import ModbusResponse

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_DELAY,
    CONF_HOST,
    CONF_METHOD,
    CONF_NAME,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_SLAVE,
    CONF_TIMEOUT,
    CONF_TYPE,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    ATTR_ADDRESS,
    CALL_TYPE_COIL,
    CALL_TYPE_DISCRETE,
    CALL_TYPE_REGISTER_HOLDING,
    CALL_TYPE_REGISTER_INPUT,
    CALL_TYPE_WRITE_COIL,
    CALL_TYPE_WRITE_COILS,
    CALL_TYPE_WRITE_REGISTER,
    CALL_TYPE_WRITE_REGISTERS,
    CONF_BAUDRATE,
    CONF_BYTESIZE,
    CONF_CLOSE_COMM_ON_ERROR,
    CONF_PARITY,
    CONF_RETRIES,
    CONF_RETRY_ON_EMPTY,
    CONF_RTUOVERTCP,
    CONF_SERIAL,
    CONF_STOPBITS,
    CONF_TCP,
    CONF_UDP,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# Define PyModbus call attributes
PYMODBUS_CALL = {
    CALL_TYPE_COIL: {
        "attr": "bits",
        "func_name": "read_coils",
    },
    CALL_TYPE_DISCRETE: {
        "attr": "bits",
        "func_name": "read_discrete_inputs",
    },
    CALL_TYPE_REGISTER_HOLDING: {
        "attr": "registers",
        "func_name": "read_holding_registers",
    },
    CALL_TYPE_REGISTER_INPUT: {
        "attr": "registers",
        "func_name": "read_input_registers",
    },
    CALL_TYPE_WRITE_COIL: {
        "attr": "value",
        "func_name": "write_coil",
    },
    CALL_TYPE_WRITE_COILS: {
        "attr": "count",
        "func_name": "write_coils",
    },
    CALL_TYPE_WRITE_REGISTER: {
        "attr": "value",
        "func_name": "write_register",
    },
    CALL_TYPE_WRITE_REGISTERS: {
        "attr": "count",
        "func_name": "write_registers",
    },
}

class ModbusHub:
    """Thread safe wrapper class for pymodbus."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the Modbus hub."""
        self._hass = hass
        self._entry = entry
        self._config = entry.data
        self._name = self._config[CONF_NAME]
        self._type = self._config[CONF_TYPE]
        self._client = None
        self._lock = asyncio.Lock()
        self._callbacks = []
        self._in_error = False
        self._unsub_poll = None
        self._unsub_poll_slave = {}
        self._slave_data = {}
        self._polling_slaves = {}
        self._scan_interval = self._config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        
        # Calculate delay between polls
        self._delay = self._config.get(CONF_DELAY, 0)
        
        # Keep track of slaves to poll
        self._slaves_to_poll = {}
    
    @property
    def name(self) -> str:
        """Return the name of this hub."""
        return self._name

    async def async_setup(self) -> bool:
        """Set up the modbus hub."""
        _LOGGER.debug("Setting up Modbus hub %s", self._name)
        try:
            result = await self._hass.async_add_executor_job(self._pymodbus_connect)
            if not result:
                return False
            
            # Start polling timer
            self._unsub_poll = async_track_time_interval(
                self._hass,
                self.async_poll_slaves,
                timedelta(seconds=self._scan_interval),
            )
            
            return True
        except ModbusException as exception:
            _LOGGER.error("Modbus connection failed: %s", exception)
            return False

    def add_callback(self, callback_func):
        """Register a callback function."""
        self._callbacks.append(callback_func)

    def _log_error(self, error_text: str, error_state=True) -> None:
        """Log error message and set error state."""
        if self._in_error != error_state:
            if error_state:
                _LOGGER.error(error_text)
            else:
                _LOGGER.info(error_text)
            self._in_error = error_state

    def _pymodbus_connect(self) -> bool:
        """Connect to modbus device and return True if successful."""
        try:
            if self._type == CONF_SERIAL:
                port = self._config[CONF_PORT]
                baudrate = self._config.get(CONF_BAUDRATE, 9600)
                bytesize = self._config.get(CONF_BYTESIZE, 8)
                parity = self._config.get(CONF_PARITY, "N")
                stopbits = self._config.get(CONF_STOPBITS, 1)
                method = self._config.get(CONF_METHOD, "rtu")
                
                # Create serial client
                self._client = ModbusSerialClient(
                    method=method,
                    port=port,
                    baudrate=baudrate,
                    bytesize=bytesize,
                    parity=parity,
                    stopbits=stopbits,
                    timeout=self._config.get(CONF_TIMEOUT, 3),
                    retries=self._config.get(CONF_RETRIES, 3),
                    retry_on_empty=self._config.get(CONF_RETRY_ON_EMPTY, False),
                )
            elif self._type == CONF_TCP:
                host = self._config[CONF_HOST]
                port = self._config.get(CONF_PORT, 502)
                
                # If using RTU over TCP
                if self._config.get(CONF_RTUOVERTCP, False):
                    framer = ModbusRtuFramer
                else:
                    framer = None
                
                # Create TCP client
                if framer:
                    self._client = ModbusTcpClient(
                        host=host,
                        port=port,
                        timeout=self._config.get(CONF_TIMEOUT, 3),
                        retries=self._config.get(CONF_RETRIES, 3),
                        retry_on_empty=self._config.get(CONF_RETRY_ON_EMPTY, False),
                        framer=framer,
                    )
                else:
                    self._client = ModbusTcpClient(
                        host=host,
                        port=port,
                        timeout=self._config.get(CONF_TIMEOUT, 3),
                        retries=self._config.get(CONF_RETRIES, 3),
                        retry_on_empty=self._config.get(CONF_RETRY_ON_EMPTY, False),
                    )
            elif self._type == CONF_UDP:
                host = self._config[CONF_HOST]
                port = self._config.get(CONF_PORT, 502)
                
                # Create UDP client
                self._client = ModbusUdpClient(
                    host=host,
                    port=port,
                    timeout=self._config.get(CONF_TIMEOUT, 3),
                    retries=self._config.get(CONF_RETRIES, 3),
                    retry_on_empty=self._config.get(CONF_RETRY_ON_EMPTY, False),
                )
            else:
                _LOGGER.error("Unsupported Modbus connection type: %s", self._type)
                return False
            
            # Test connection
            self._client.connect()
            if not self._client.socket:
                _LOGGER.error("Failed to connect to Modbus device")
                return False
            
            return True
        except ModbusException as exception:
            _LOGGER.error("Error connecting to Modbus device: %s", exception)
            return False
    
    def _pymodbus_call(self, unit, address, value, call_type) -> Optional[ModbusResponse]:
        """Call modbus method."""
        try:
            if not self._client.is_socket_open():
                if not self._client.connect():
                    self._log_error("Failed to reconnect to modbus device")
                    return None
                else:
                    self._log_error("Reconnected to modbus device", error_state=False)
            
            call_detail = PYMODBUS_CALL[call_type]
            func = getattr(self._client, call_detail["func_name"])
            
            if call_type in (CALL_TYPE_WRITE_COIL, CALL_TYPE_WRITE_REGISTER):
                # Single write (address, value)
                result = func(address, value, unit=unit)
            elif call_type in (CALL_TYPE_WRITE_COILS, CALL_TYPE_WRITE_REGISTERS):
                # Multiple write (address, [values])
                result = func(address, value, unit=unit)
            else:
                # Read (address, count)
                count = len(value) if isinstance(value, list) else int(value)
                result = func(address, count, unit=unit)
            
            if not hasattr(result, call_detail["attr"]):
                self._log_error(f"No {call_detail['attr']} in result: {result}")
                return None
            
            self._log_error("Successful modbus call", error_state=False)
            return result
        except ModbusException as exception:
            self._log_error(f"Error during modbus call: {exception}")
            return None
    
    async def async_pymodbus_call(self, unit, address, value, call_type) -> Optional[ModbusResponse]:
        """Call modbus method."""
        async with self._lock:
            return await self._hass.async_add_executor_job(
                self._pymodbus_call, unit, address, value, call_type
            )
    
    def register_slaves_to_poll(self, slave, addresses):
        """Register slaves and addresses to poll."""
        if slave not in self._slaves_to_poll:
            self._slaves_to_poll[slave] = {"addresses": []}
        
        self._slaves_to_poll[slave]["addresses"].extend(addresses)
        
        # Calculate start and count for efficient polling
        self._slaves_to_poll[slave]["start"] = min(self._slaves_to_poll[slave]["addresses"])
        self._slaves_to_poll[slave]["count"] = max(self._slaves_to_poll[slave]["addresses"]) - min(self._slaves_to_poll[slave]["addresses"]) + 1
        
        _LOGGER.debug("Registered polling for slave %s, addresses: %s", slave, addresses)
    
    async def async_poll_slaves(self, now=None):
        """Poll all registered slaves."""
        for slave, config in self._slaves_to_poll.items():
            start = config["start"]
            count = config["count"]
            
            # Request coil states
            result = await self.async_pymodbus_call(
                slave, start, count, CALL_TYPE_COIL
            )
            
            if result is None:
                continue
            
            # Process the result
            states = {}
            for i in range(count):
                if i < len(result.bits):
                    states[start + i] = result.bits[i]
                else:
                    states[start + i] = False
            
            # Store data
            self._slave_data[slave] = states
            
            # Notify callbacks
            for callback_func in self._callbacks:
                callback_func(states, slave)
            
            # Small delay between polls if configured
            if self._delay > 0:
                await asyncio.sleep(self._delay / 1000)
    
    @callback
    async def async_stop(self, event=None):
        """Stop the hub."""
        if self._unsub_poll is not None:
            self._unsub_poll()
            self._unsub_poll = None
            
        await self.async_close()
    
    async def async_close(self):
        """Close the connection."""
        if self._client:
            try:
                await self._hass.async_add_executor_job(self._pymodbus_close)
            except Exception as exception:  # pylint: disable=broad-except
                _LOGGER.error("Error closing Modbus connection: %s", exception)
            self._client = None
        return True
    
    def _pymodbus_close(self):
        """Close the Modbus connection."""
        try:
            self._client.close()
        except Exception as exception:  # pylint: disable=broad-except
            _LOGGER.error("Error closing Modbus connection: %s", exception)
        
    async def write_coil(self, slave, address, value):
        """Write to a coil."""
        result = await self.async_pymodbus_call(slave, address, value, CALL_TYPE_WRITE_COIL)
        return result is not None

def setup_client(config, name):
    """Set up the Modbus client."""
    client = None
    delay_ms = config.get(CONF_DELAY, DEFAULT_DELAY_MS)

    if config[CONF_TYPE] == CONF_SERIAL:
        method = config[CONF_METHOD]
        if method == "rtu":
            framer = ModbusRtuFramer
        else:
            framer = ModbusAsciiFramer
        client = ModbusSerialClient(
            method=method,
            port=config[CONF_PORT],
            baudrate=config[CONF_BAUDRATE],
            stopbits=config[CONF_STOPBITS],
            bytesize=config[CONF_BYTESIZE],
            parity=config[CONF_PARITY],
            timeout=TIMEOUT,
            retry_on_empty=True,
        )
    elif config[CONF_TYPE] == CONF_TCP:
        host = config[CONF_HOST]
        port = config[CONF_PORT]
        # Check if RTU over TCP is enabled
        if config.get(CONF_RTUOVERTCP, False):
            framer = ModbusRtuFramer
        else:
            framer = None

        # Initialize the client with or without framer parameter based on its value
        if framer is not None:
            client = ModbusTcpClient(
                host=host,
                port=port,
                timeout=TIMEOUT,
                retries=RETRIES,
                retry_on_empty=True,
                framer=framer,
            )
        else:
            client = ModbusTcpClient(
                host=host,
                port=port,
                timeout=TIMEOUT,
                retries=RETRIES,
                retry_on_empty=True,
            )

    return client, delay_ms 