# Symi Modbus

Home Assistant custom integration for Symi Modbus relay modules over **TCP** or **serial RTU**. Each config entry creates **32 switch entities** (coils 0-31) for one slave unit on that link.

## Requirements

| Item | Value |
|------|--------|
| Version | **1.2.1** |
| Home Assistant | **2024.1.0** or newer (tested on 2026.5.x) |
| Python dependency | `pyserial` (declared in `manifest.json`) |

## Features

- TCP (hostname or IP) and serial RTU (`pyserial` + `serial_asyncio`).
- Serial setup: **enumerate local ports** (USB and other TTYs), pick from list, or **manual device path**.
- Polling interval configurable in integration **Options** (reloads entry on save).
- Transport errors: **no repeated ERROR lines** on every poll; recovery logs once; CRC issues throttled (WARNING at most about once per minute per key).
- Entities reflect **availability** when the link is down; they recover when communication succeeds again.
- Branding: root `icon.png` / `logo.png` and `brand/` assets; source artwork in `icons/icon.png` (see below).

## HACS and validation

- `hacs.json` is present for HACS default store / custom repository installs.
- GitHub Actions: `.github/workflows/hacs.yaml` (HACS validation, `ignore: brands` because icons ship in the repo) and `.github/workflows/hassfest.yaml` (Home Assistant manifest/structure checks).

## Install

**HACS:** Custom repositories → add `https://github.com/symi-daguo/symi_modbus` as Integration → install → restart Home Assistant.

**Manual:** Copy `custom_components/symi_modbus` into your configuration `custom_components/` directory and restart.

## Configuration flow

1. Choose **TCP** or **Serial**.
2. **TCP:** host and port. **Serial:** pick a detected port or **manual path**, then set baud rate, data bits, parity, stop bits, RTU/ASCII.
3. Enter **slave unit ID** (decimal; default 10 = 0x0A).
4. One config entry is created. To add **another slave on the same TCP or serial device**, run **Add integration** again with the same connection settings and a different slave address.

## Docker and serial

Serial enumeration shows devices **inside the container**. Map host devices explicitly, for example:

```yaml
devices:
  - /dev/ttyUSB0:/dev/ttyUSB0
```

Use the path **as seen in the container** (often `/dev/ttyUSB0`).

## Services

- `symi_modbus.write_coil` – supported.
- `symi_modbus.write_register` – not implemented for this hardware profile; calls are ignored with a debug log.

**`hub`:** Use the **integration entry title** shown under Settings (e.g. `Modbus TCP 0A`), not a generic placeholder.

## Brand files

Official square logo: `custom_components/symi_modbus/icons/icon.png`. Root `icon.png`, `logo.png`, and `brand/` PNGs are generated from that source for the UI and HACS. Replace `icons/icon.png` and regenerate those files if the brand changes.

## Development

- `CONTRIBUTING.md` – fork / PR workflow.
- Code style: match Home Assistant patterns; UTF-8 sources; avoid noisy logs on steady-state failures.

## License

MIT
