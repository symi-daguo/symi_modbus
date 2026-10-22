# Symi Modbus

Home Assistant custom integration for Symi Modbus relay modules, over **serial RTU** or **TCP**.

One config entry describes **one Modbus master** (a serial port or a TCP endpoint) together with
**all the slaves behind it**. Every slave becomes its own device with one switch entity per coil.

## Requirements

| Item | Value |
|------|--------|
| Version | **2.0.0** |
| Home Assistant | **2024.11.0** or newer (developed against 2026.10.2) |
| Python dependency | `pyserial`, `pyserial-asyncio` (declared in `manifest.json`) |

## Features

- **Serial RTU** and **TCP**, with the frame format chosen per connection:
  `Modbus TCP (MBAP)` or `Modbus RTU over TCP` for serial-to-ethernet gateways.
  A serial port always speaks RTU, the MBAP header only exists on TCP.
- **One master, many slaves**: add several slave addresses to the same connection in a single
  configuration flow. Each slave is polled on its own and gets its own device in Home Assistant.
- **Coil count per slave**, so a 16 channel module does not create 16 switches that never
  change.
- **Persistent connection** with automatic reconnect. The link is kept open between requests, so
  the device is not reset by opening the port over and over.
- **Survives outages**: when the device reboots or the network drops, the entities turn
  `unavailable`, the connection is rebuilt automatically and the entities recover on their own.
- **Serial port picker**: detected ports are listed, a manual device path can be entered for
  anything that is not listed.
- Polling interval configurable in the integration **Options**.
- **Quiet logging**: a failing link logs one error per outage instead of one per poll, and the
  recovery is reported once.

## Installation

**HACS:** Custom repositories → add `https://github.com/symi-daguo/symi_modbus` as Integration →
install → restart Home Assistant.

**Manual:** Copy `custom_components/symi_modbus` into your configuration `custom_components/`
directory and restart.

## Configuration flow

1. Choose **TCP** or **Serial**.
2. **TCP:** host, port and frame format. **Serial:** pick a detected port or enter a manual path,
   then set baud rate, data bits, parity and stop bits. The defaults are 9600 baud, 8 data bits,
   no parity and one stop bit.
3. Enter the **slave address** (decimal, default 10 = `0x0A`) and the **coil count** of that
   device. Tick *Add another slave* to add more slaves on the same connection, then enter the next
   address.
4. The entry is created with all slaves of that master.

To use a second master (another serial port or another gateway), add the integration again. Each
entry keeps its own connection, so the masters poll independently.

The devices show up as `Serial /dev/ttyUSB0 从站 0A`, so a device can be told apart by its link
and by its slave address.

## Docker and serial

The port list shows the devices **inside the container**. Map the host devices explicitly:

```yaml
devices:
  - /dev/ttyUSB0:/dev/ttyUSB0
```

Use the path **as seen in the container** (often `/dev/ttyUSB0`).

## Services

- `symi_modbus.write_coil` – write a single coil.
- `symi_modbus.write_register` – not supported by this device profile; the call is ignored.

**`hub`:** the entry title shown in Settings (e.g. `Modbus TCP 192.168.1.10:502`). Leave it empty
when only one connection is configured.

## Brand files

The integration ships its own brand images in `custom_components/symi_modbus/brand/`, the folder
Home Assistant reads since 2026.3:

| File | Size |
|------|------|
| `icon.png` / `dark_icon.png` | 256 × 256 |
| `icon@2x.png` / `dark_icon@2x.png` | 512 × 512 |
| `logo.png` / `dark_logo.png` | 256 high |
| `logo@2x.png` / `dark_logo@2x.png` | 512 high |

The source artwork lives in `assets/icon_source.png`. Run `python scripts/generate_brand.py` to
regenerate every file after a brand change.

## Development

```bash
docker run --rm -v "$PWD:/work" -w /work homeassistant/home-assistant:stable \
  sh -c "pip install pytest-asyncio -q && python -m pytest tests/ -q --asyncio-mode=auto"
```

- `tests/` covers the frame encoding, the hub behaviour, the reconnect logic and the packaging.
- `scripts/modbus_simulator.py` serves a fake Modbus slave on a TCP port or a pseudo terminal,
  which is handy to try the integration without hardware.

## License

MIT
