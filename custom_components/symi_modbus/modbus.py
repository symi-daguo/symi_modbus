"""Modbus hub: one connection (master) polling one or more slaves."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from time import monotonic
from typing import Callable, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONF_BAUDRATE,
    CONF_BYTESIZE,
    CONF_COIL_COUNT,
    CONF_DELAY,
    CONF_FRAME,
    CONF_HOST,
    CONF_NAME,
    CONF_PARITY,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_SERIAL,
    CONF_SLAVES,
    CONF_STOPBITS,
    CONF_TCP,
    CONF_TYPE,
    DEFAULT_COIL_COUNT,
    DEFAULT_SCAN_INTERVAL,
    FRAME_MBAP,
    FRAME_RTU,
)
from .connection import ModbusConnection
from .frames import (
    FUNCTION_READ_COILS,
    FUNCTION_WRITE_MULTIPLE_COILS,
    FUNCTION_WRITE_SINGLE_COIL,
    build_read_request,
    build_write_coil_request,
    build_write_multiple_coils_request,
    parse_coil_bits,
)

_LOGGER = logging.getLogger(__name__)

CRC_WARN_INTERVAL = 60.0

# Callbacks receive (states, slave).
StateCallback = Callable[[dict[int, bool], int], None]
# Callbacks receive (available, slave).
AvailabilityCallback = Callable[[bool, int], None]

# A slave that stops answering is skipped for a while, so it does not spend
# the read timeout of every round. The longer it stays silent, the longer it
# is left alone.
FAILURES_BEFORE_SKIP = 2
MAX_SKIP_ROUNDS = 60
# The shortest time between two polls of the same slave.
MIN_POLL_INTERVAL = 0.1


class ModbusHub:
    """Poll the slaves behind one Modbus master (serial port or TCP endpoint).

    Every slave is polled on its own schedule slot and a failing slave never
    blocks the others, so one dead device cannot stall the whole bus.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the hub from a config entry."""
        self._hass = hass
        self._entry = entry
        self._config = entry.data
        self._name = self._config.get(CONF_NAME, "Symi Modbus")
        self._type = self._config[CONF_TYPE]
        self._callbacks: list[StateCallback] = []
        self._availability_callbacks: list[AvailabilityCallback] = []
        self._scan_interval = entry.options.get(
            CONF_SCAN_INTERVAL,
            self._config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        self._delay = self._config.get(CONF_DELAY, 0)
        if self._type == CONF_SERIAL:
            # A serial line always carries RTU frames, the MBAP header only
            # exists on TCP.
            self._frame = FRAME_RTU
        else:
            self._frame = self._config.get(CONF_FRAME, FRAME_MBAP)
        self._coil_count = int(self._config.get(CONF_COIL_COUNT, DEFAULT_COIL_COUNT))
        self._slaves: dict[int, dict] = {}
        self._slave_data: dict[int, dict[int, bool]] = {}
        self._unsub_poll = None
        self._in_error = False
        self._link_was_down: dict[int, bool] = {}
        self._slave_available: dict[int, bool] = {}
        self._slave_failures: dict[int, int] = {}
        self._slave_skip_until: dict[int, int] = {}
        self._poll_order: list[int] = []
        self._poll_index = 0
        self._round = 0
        self._crc_last_log: dict[str, float] = {}
        self._transaction_id = 0

        self._connection = ModbusConnection(
            connection_type=self._type,
            host=self._config.get(CONF_HOST),
            port=self._config.get(CONF_PORT),
            baudrate=int(self._config.get(CONF_BAUDRATE, 9600)),
            bytesize=int(self._config.get(CONF_BYTESIZE, 8)),
            parity=str(self._config.get(CONF_PARITY, "N")),
            stopbits=int(self._config.get(CONF_STOPBITS, 1)),
            frame=self._frame,
        )

    @property
    def name(self) -> str:
        """Return the name of this hub."""
        return self._name

    @property
    def endpoint(self) -> str:
        """Return a readable description of the connection."""
        if self._type == CONF_TCP:
            return f"{self._config.get(CONF_HOST)}:{self._config.get(CONF_PORT)}"
        return str(self._config.get(CONF_PORT))

    @property
    def entry_id(self) -> str:
        """Return the id of the config entry behind this hub."""
        return self._entry.entry_id

    @property
    def connection_type(self) -> str:
        """Return the connection type key (tcp / serial)."""
        return self._type

    @property
    def frame(self) -> str:
        """Return the frame format in use."""
        return self._frame

    @property
    def coil_count(self) -> int:
        """Return the number of coils exposed per slave."""
        return self._coil_count

    @property
    def slaves(self) -> dict[int, dict]:
        """Return the registered slaves and their coil ranges."""
        return self._slaves

    def get_state(self, slave: int, address: int) -> bool | None:
        """Return the last known state of a coil, or None when unknown."""
        return self._slave_data.get(slave, {}).get(address)

    def is_slave_available(self, slave: int) -> bool:
        """Return whether the slave answered the last poll.

        An entity that is added after the first poll reads the state here, so
        it does not wait for the next availability change.
        """
        return self._slave_available.get(slave, False)

    def add_callback(self, callback_func: StateCallback) -> None:
        """Register a state callback function."""
        self._callbacks.append(callback_func)

    def remove_callback(self, callback_func: StateCallback) -> None:
        """Remove a state callback registered earlier."""
        try:
            self._callbacks.remove(callback_func)
        except ValueError:
            pass

    def add_availability_callback(self, callback_func: AvailabilityCallback) -> None:
        """Register callback for slave availability (True = link up)."""
        self._availability_callbacks.append(callback_func)

    def remove_availability_callback(self, callback_func: AvailabilityCallback) -> None:
        """Remove an availability callback registered earlier."""
        try:
            self._availability_callbacks.remove(callback_func)
        except ValueError:
            pass

    def _notify_availability(self, available: bool, slave: int) -> None:
        """Notify listeners when the availability of one slave changes.

        The availability is tracked per slave, so a slave that stops
        answering does not take the other slaves down with it.
        """
        if self._slave_available.get(slave) == available:
            return
        self._slave_available[slave] = available
        for callback in self._availability_callbacks:
            try:
                callback(available, slave)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Availability callback failed")

    def _log_error(self, error_text: str, error_state: bool = True) -> None:
        """Log error transitions without repeating the same message every poll."""
        if self._in_error != error_state:
            if error_state:
                _LOGGER.error("%s (%s)", error_text, self._name)
            else:
                _LOGGER.info("%s (%s)", error_text, self._name)
            self._in_error = error_state

    def _note_link_up(self, slave: int) -> None:
        """Report that a slave answers again, once per outage."""
        if self._link_was_down.get(slave):
            _LOGGER.info(
                "Slave %s on %s answers again", slave, self._name
            )
            self._link_was_down[slave] = False

    def _note_link_down(self, reason: str, slave: int) -> None:
        """Report that a slave stopped answering, once per outage."""
        if not self._link_was_down.get(slave):
            _LOGGER.error("%s (%s)", reason, self._name)
            self._link_was_down[slave] = True
        self._in_error = True

    def _throttled_warning(self, key: str, message: str) -> None:
        """Log a warning at most once per minute per key."""
        now = monotonic()
        last = self._crc_last_log.get(key, 0.0)
        if now - last >= CRC_WARN_INTERVAL:
            self._crc_last_log[key] = now
            _LOGGER.warning("%s (%s)", message, self._name)

    def register_slave(self, slave: int, start: int = 0, count: int | None = None) -> None:
        """Register a slave unit and the coil range to poll for it."""
        coil_count = int(count if count is not None else self._coil_count)
        self._slaves[slave] = {"start": int(start), "count": coil_count}
        if slave not in self._poll_order:
            self._poll_order.append(slave)
        _LOGGER.debug(
            "Registered slave %s, coils %s-%s",
            slave,
            int(start),
            int(start) + coil_count - 1,
        )

    def register_slaves(self, slaves: dict[int | str, dict]) -> None:
        """Register every slave of this hub.

        Slave keys are stored as strings in the config entry, so they are
        normalised to integers here.
        """
        for slave, options in slaves.items():
            self.register_slave(
                int(slave),
                start=int(options.get("start", 0)),
                count=int(options.get("count", self._coil_count)),
            )

    async def async_setup(self) -> bool:
        """Set up the modbus hub."""
        _LOGGER.debug("Setting up Modbus hub %s (%s)", self._name, self._type)
        self.register_slaves(self._config.get(CONF_SLAVES, {}))

        self._unsub_poll = async_track_time_interval(
            self._hass,
            self.async_poll_slaves,
            self._poll_interval(),
        )
        return True

    def _poll_interval(self) -> timedelta:
        """Return the time between two polls of the same slave.

        The scan interval is the period of one round over all slaves, so the
        slaves of a master share it. Five slaves with a five second interval
        are asked every second, one slave with the same interval every five
        seconds.
        """
        slaves = max(len(self._slaves), 1)
        seconds = max(self._scan_interval / slaves, MIN_POLL_INTERVAL)
        return timedelta(seconds=seconds)

    def _next_transaction_id(self) -> int:
        """Return an incrementing transaction id for MBAP frames."""
        self._transaction_id = (self._transaction_id + 1) & 0xFFFF
        return self._transaction_id

    async def async_req_state(self, slave: int) -> dict[int, bool] | None:
        """Read the coil states of one slave."""
        options = self._slaves.get(slave)
        if options is None:
            return None

        request = build_read_request(
            slave,
            FUNCTION_READ_COILS,
            options["start"],
            options["count"],
            self._frame,
            self._next_transaction_id(),
        )
        payload = await self._connection.async_request(request, FUNCTION_READ_COILS)
        if payload is None:
            self._notify_availability(False, slave)
            self._note_link_down(
                f"No response from slave {slave} on {self._name}", slave
            )
            return None

        self._note_link_up(slave)
        self._notify_availability(True, slave)

        # Read-coils payload: byte count followed by the packed bits.
        if not payload:
            return None
        byte_count = payload[0]
        states = parse_coil_bits(payload[1 : 1 + byte_count], options["count"])
        return states

    def handle_state(self, states: dict[int, bool], slave: int) -> None:
        """Store new states and push them to the listeners."""
        if slave not in self._slave_data:
            _LOGGER.info(
                "Slave %s answered, %s coil(s) read", slave, len(states)
            )
        self._slave_data[slave] = states
        for callback in self._callbacks:
            try:
                callback(states, slave)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("State callback failed")

    async def async_poll_slaves(self, now: Optional[object] = None) -> None:
        """Poll the next slave of this master.

        The slaves take turns, so a slave that stops answering only costs its
        own slot and the other slaves keep their own timing. A slave that
        stays silent is skipped for a while, so it does not spend the read
        timeout of every round.
        """
        self._round += 1
        slave = self._next_slave()
        if slave is None:
            return

        try:
            states = await self.async_req_state(slave)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Polling slave %s failed", slave)
            return

        if states is None:
            self._register_failure(slave)
            return

        self._clear_failure(slave)
        self.handle_state(states, slave)

        if self._delay > 0:
            await asyncio.sleep(self._delay / 1000)

    def _next_slave(self) -> Optional[int]:
        """Return the next slave that is due for a poll."""
        if not self._slaves:
            return None

        for _ in range(len(self._slaves)):
            slave = self._poll_order[self._poll_index % len(self._poll_order)]
            self._poll_index += 1
            if self._slave_skip_until.get(slave, 0) > self._round:
                continue
            return slave
        return None

    def _register_failure(self, slave: int) -> None:
        """Count a failed poll and skip the slave for a while.

        The skip grows with the number of failures, so a slave that stays
        silent is only tried every few rounds and the other slaves keep
        their own timing.
        """
        failures = self._slave_failures.get(slave, 0) + 1
        self._slave_failures[slave] = failures
        if failures < FAILURES_BEFORE_SKIP:
            return
        rounds = min(2 ** (failures - FAILURES_BEFORE_SKIP + 1), MAX_SKIP_ROUNDS)
        self._slave_skip_until[slave] = self._round + rounds

    def _clear_failure(self, slave: int) -> None:
        """Forget the failures of a slave that answers again."""
        if self._slave_failures.pop(slave, None) is not None:
            self._slave_skip_until.pop(slave, None)

    async def write_coil(self, slave: int, address: int, value: bool) -> bool:
        """Write a single coil on a slave."""
        if slave not in self._slaves:
            _LOGGER.warning("Slave %s is not registered on hub %s", slave, self._name)
            return False

        request = build_write_coil_request(
            slave, address, value, self._frame, self._next_transaction_id()
        )
        payload = await self._connection.async_request(request, FUNCTION_WRITE_SINGLE_COIL)
        if payload is None:
            self._notify_availability(False, slave)
            self._note_link_down(
                f"No response from slave {slave} on {self._name}", slave
            )
            return False

        self._note_link_up(slave)
        self._notify_availability(True, slave)

        # Reflect the new value locally; the next poll confirms it.
        if slave in self._slave_data and address in self._slave_data[slave]:
            self._slave_data[slave][address] = value

        _LOGGER.info("Wrote coil %s of slave %s to %s", address, slave, value)
        return True

    async def write_coils(self, slave: int, address: int, values: list[bool]) -> bool:
        """Write several consecutive coils on a slave."""
        if slave not in self._slaves:
            _LOGGER.warning("Slave %s is not registered on hub %s", slave, self._name)
            return False

        request = build_write_multiple_coils_request(
            slave, address, values, self._frame, self._next_transaction_id()
        )
        payload = await self._connection.async_request(request, FUNCTION_WRITE_MULTIPLE_COILS)
        if payload is None:
            self._notify_availability(False, slave)
            self._note_link_down(
                f"No response from slave {slave} on {self._name}", slave
            )
            return False

        self._note_link_up(slave)
        self._notify_availability(True, slave)

        if slave in self._slave_data:
            for offset, value in enumerate(values):
                target = address + offset
                if target in self._slave_data[slave]:
                    self._slave_data[slave][target] = value

        return True

    async def async_stop(self, event: Optional[object] = None) -> None:
        """Stop the hub and close the transport."""
        if self._unsub_poll is not None:
            self._unsub_poll()
            self._unsub_poll = None
        await self._connection.async_close()
