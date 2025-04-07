"""Symi Modbus integration."""
import asyncio
import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple, Callable, Set

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

from .const import (
    ATTR_ADDRESS,
    CONF_BAUDRATE,
    CONF_BYTESIZE,
    CONF_PARITY,
    CONF_RETRIES,
    CONF_RETRY_ON_EMPTY,
    CONF_RTUOVERTCP,
    CONF_SERIAL,
    CONF_STOPBITS,
    CONF_TCP,
    CONF_UDP,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_DELAY_MS,
    DOMAIN,
)
from .crc16 import crc16_fn

_LOGGER = logging.getLogger(__name__)

class ModbusHub:
    """Thread safe wrapper class for modbus communication."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the Modbus hub."""
        self._hass = hass
        self._entry = entry
        self._config = entry.data
        self._name = self._config[CONF_NAME]
        self._type = self._config[CONF_TYPE]
        self._lock = asyncio.Lock()
        self._callbacks = []
        self._scan_interval = self._config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        self._delay = self._config.get(CONF_DELAY, DEFAULT_DELAY_MS)
        self._slave_data = {}
        self._slaves_to_poll = {}
        self._unsub_poll = None
        self._in_error = False
        
        # Connection details
        if self._type == CONF_TCP:
            self._host = self._config[CONF_HOST]
            self._port = self._config.get(CONF_PORT, 502)
        elif self._type == CONF_SERIAL:
            # For future serial support
            self._port = self._config[CONF_PORT]
            self._baudrate = self._config.get(CONF_BAUDRATE, 9600)
            self._bytesize = self._config.get(CONF_BYTESIZE, 8)
            self._parity = self._config.get(CONF_PARITY, "N")
            self._stopbits = self._config.get(CONF_STOPBITS, 1)
            self._rtu = self._config.get(CONF_METHOD, "rtu") == "rtu"
        
    @property
    def name(self) -> str:
        """Return the name of this hub."""
        return self._name

    async def async_setup(self) -> bool:
        """Set up the modbus hub."""
        _LOGGER.debug("Setting up Modbus hub %s", self._name)
        
        # Start polling timer
        self._unsub_poll = async_track_time_interval(
            self._hass,
            self.async_poll_slaves,
            timedelta(seconds=self._scan_interval),
        )
        
        return True

    def add_callback(self, callback_func: Callable):
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
    
    async def async_send(self, data):
        """Send data over TCP connection."""
        if self._type != CONF_TCP:
            _LOGGER.error("Only TCP connections are currently supported")
            return None
        
        try:
            coro = asyncio.open_connection(self._host, self._port)
            reader, writer = await asyncio.wait_for(coro, 1)
        except Exception as e:
            self._log_error(f"TCP connection failed: {e}")
            return None
        
        writer.write(bytes(data))
        try:
            read = reader.read(20)
            buf = await asyncio.wait_for(read, 0.5)
            if len(buf) > 2:
                return buf
            else:
                self._log_error("Received insufficient data")
                return None
        except Exception as e:
            self._log_error(f"Response timeout: {e}")
            return None
        finally:
            writer.close()
    
    def register_slaves_to_poll(self, slave, addresses):
        """Register slaves and addresses to poll."""
        if slave not in self._slaves_to_poll:
            self._slaves_to_poll[slave] = {"addresses": []}
        
        # Add new addresses
        for address in addresses:
            if address not in self._slaves_to_poll[slave]["addresses"]:
                self._slaves_to_poll[slave]["addresses"].append(address)
        
        # Calculate start and count for efficient polling
        self._slaves_to_poll[slave]["start"] = min(self._slaves_to_poll[slave]["addresses"])
        max_addr = max(self._slaves_to_poll[slave]["addresses"])
        self._slaves_to_poll[slave]["count"] = max_addr - self._slaves_to_poll[slave]["start"] + 1
        
        _LOGGER.debug("Registered polling for slave %s, addresses: %s", slave, self._slaves_to_poll[slave]["addresses"])
    
    async def async_req_state(self, slave):
        """Request coil states from a slave."""
        start = self._slaves_to_poll[slave]["start"]
        count = self._slaves_to_poll[slave]["count"]
        
        # Create Modbus read coils request
        data = [slave, 1, 0, start, 0, count]
        for crc in crc16_fn(data):
            data.append(crc)
        
        async with self._lock:
            response = await self.async_send(data)
            return response
    
    def handle_state(self, data):
        """Process state data from response."""
        if len(data) < 3 or data[1] != 1:
            return False
        
        slave = data[0]
        if slave not in self._slaves_to_poll:
            return False
        
        states = {}
        start = self._slaves_to_poll[slave]["start"]
        for i in range(data[2]):
            bits = data[i+3]
            for j in range(8):
                addr = start + j + i*8
                states[addr] = True if bits >> j & 0x01 else False
        
        # Store data
        self._slave_data[slave] = states
        
        # Notify callbacks
        for callback_func in self._callbacks:
            callback_func(states, slave)
        
        return True
    
    def check_crc(self, data):
        """Check CRC of response data."""
        if len(data) < 3:
            return False
        crc = crc16_fn(data[:-2])
        return (data[-2] == crc[0]) & (data[-1] == crc[1])
    
    async def async_poll_slaves(self, now=None):
        """Poll all registered slaves."""
        for slave in self._slaves_to_poll:
            response = await self.async_req_state(slave)
            
            if response is None:
                continue
            
            if not self.check_crc(response):
                _LOGGER.warning("CRC check failed for slave %s", slave)
                continue
            
            self.handle_state(response[:-2])
            
            # Small delay between polls if configured
            if self._delay > 0:
                await asyncio.sleep(self._delay / 1000)
    
    async def write_coil(self, slave, address, value):
        """Write to a coil."""
        data = [slave, 5, 0, address, 0, 0]
        if value:
            data[4] = 0xff
        
        for crc in crc16_fn(data):
            data.append(crc)
        
        async with self._lock:
            response = await self.async_send(data)
            if response is None:
                return False
            
            if not self.check_crc(response):
                _LOGGER.warning("CRC check failed for write response")
                return False
            
            # Update the state in our local cache
            if slave in self._slave_data and address in self._slave_data[slave]:
                self._slave_data[slave][address] = value
            
            return True
    
    @callback
    async def async_stop(self, event=None):
        """Stop the hub."""
        if self._unsub_poll is not None:
            self._unsub_poll()
            self._unsub_poll = None 