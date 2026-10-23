# Symi Modbus

Home Assistant custom integration for Symi Modbus relay modules and Symi wall panels, over
**serial RTU** or **TCP**.

One config entry describes **one Modbus master** (a serial port or a TCP endpoint). Everything
that belongs to it is a **subentry** that can be added, changed and removed on its own:

- **Modbus slaves** – every slave becomes its own device with one switch entity per coil.
- **Wall panel buses** – the panels of one brand on one serial line, one switch entity per button.
- **Button links** – a panel button and the relays it drives, the state is shared in both
  directions.

## Requirements

| Item | Value |
|------|--------|
| Version | **2.3.1** |
| Home Assistant | **2025.3.0** or newer (developed against 2026.10.2, verified on 2026.7.4) |
| Python dependency | `pyserial`, `pyserial-asyncio-fast` (declared in `manifest.json`) |

Home Assistant 2025.3 is the first release with **config subentries**, the mechanism that lets the
slaves, the panels and the links be managed separately inside one entry.

## Features

- **Serial RTU** and **TCP**, with the frame format chosen per connection:
  `Modbus TCP (MBAP)` or `Modbus RTU over TCP` for serial-to-ethernet gateways.
  A serial port always speaks RTU, the MBAP header only exists on TCP.
- **One master, many slaves**: add several slave addresses to the same connection. Each slave is
  polled on its own and gets its own device in Home Assistant.
- **Coil count per slave**, so a 16 channel module does not create 16 switches that never
  change.
- **Wall panels**: the panels of the **Symi**, **Clowire** and **LF** brands are read on their own
  serial line and every button becomes a switch entity.
- **Button links**: a panel button can drive one or more relays, and a relay can light up on one
  or more panel buttons.
- **Persistent connection** with automatic reconnect. The link is kept open between requests, so
  the device is not reset by opening the port over and over.
- **Survives outages**: when the device reboots or the network drops, the entities turn
  `unavailable`, the connection is rebuilt automatically and the entities recover on their own.
- **One silent slave does not affect the others**: the availability is tracked per slave, and a
  slave that stops answering is skipped for a few rounds instead of holding up the bus.
- **Serial port picker**: detected ports are listed, a manual device path can be entered for
  anything that is not listed.
- Polling interval configurable in the integration **Options**, fractional values are allowed.
- **Quiet logging**: a failing link logs one error per outage instead of one per poll, and the
  recovery is reported once.

## Polling

The scan interval is the period of **one round over all slaves of a master**, and it can be
changed in the integration **Options**. The default is one second, smaller values such as half a
second are allowed.

The slaves take turns, so the interval is shared between them:

| Slaves on the master | Each slave is asked |
|----------------------|--------------------|
| 1                    | every 1 second      |
| 5                    | every 200 ms        |
| 10                   | every 100 ms        |

A whole round of five slaves therefore finishes inside one second, and a single slave is
asked once per second. The number of slaves per master is not limited.

Every slave is read with **one** request that returns all of its coils at once, a 32 coil
device is read with a single frame.

A slave that does not answer times out after 0.5 s. It is then skipped for a while, and the
skip grows while it stays silent, so it cannot spend the timeout of every round. Its entities
turn `unavailable` on their own, the other slaves keep their own timing and stay available.

The panels are **event driven**, the buttons report themselves on the bus, so they are not
polled. Only the frames that drive an indicator light are sent, and they go through a queue that
keeps the order and leaves at least 50 ms between two commands, as the panel manuals ask.

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
3. Enter the **slave address** (decimal, default 10 = `0x0A`), the **number of slaves** and the
   **coil count** of the device. The number of slaves adds several slaves at once, their addresses
   follow the address that was entered.
4. The entry is created with those slaves.

Everything else is managed on the page of the entry in **Settings → Devices & services**:

| Button | What it does |
|--------|--------------|
| **Add slave** | Add one or more Modbus slaves to this master. |
| **Add panel bus** | Add the serial line with the wall panels, and pick the brand. |
| **Add button link** | Link panel buttons to relays. |

Every entry that is already there can be **changed** or **removed** on the same page. A change only
touches the entry it was made on, the other slaves, panel buses and links keep their settings.

The serial port of a panel bus is picked from the devices that are detected on the system, a path
that is not listed can be entered in the same field. A port that this integration already uses is
not offered, because two connections on one port would split the bytes between them. A port that
**another program** holds is marked, because that splits the bytes as well, and it cannot be
saved: the configuration refuses it and says why.

The devices show up as `Serial /dev/ttyUSB0`, and their entities carry the slave address, for
example `0A Line 01`, so a device can be told apart by its link and by its slave address. Every
device belongs to the slave, panel bus or link it belongs to, so it shows up once and not twice.

**Names that were changed by hand are kept.** A slave, a panel bus or a link that was renamed in
the interface keeps that name, a later change of the configuration does not put the old name back.

## Wall panels

A **panel bus** is one serial line with the panels of one brand. The brand decides which protocol
is used, the same dialects the original Node-RED node speaks:

| Brand | Protocol |
|-------|----------|
| Symi (亖米) | light weight framed protocol, `0x7E … 0x7D` with a CRC-8 |
| Clowire (克伦威尔) | Modbus like with an extra frame tail `0xAA` behind the CRC |
| LF (拉斐) | fixed eight byte frames, the indicator lights are a bit mask in register `0x1008` |

Each panel on the bus gets its own device, each button its own switch entity. The state of the
entity is the state of the indicator light: a press of the button turns the entity on, and
writing the entity writes the indicator light back to the panel.

The frames of the LF panels are written as a whole, so the integration keeps track of the state
of every button of a panel. The LF panels also need to be put into the mode where the host owns
the indicator lights, which the integration does when the bus starts.

### The codes of a panel

A panel has two dialects on the bus: the frame it sends when a button is pressed, and the frame
that carries the state it reports. The second one can use a code of its own for the state, the
protocol document only shows `0x01` for on and `0x00` for off.

The integration therefore keeps the code of every frame the panel sends and matches it against the
state of the button. A press of a button flips the state, so the code of that frame belongs to the
new state. The codes are learned per button and are stored with the entity, so the indicator
light is driven with the codes the panel understands, and they survive a restart.

The log shows what was learned:

```
Panel 1 button 1 uses the code 17 for on
Panel 1 button 1 uses the code 16 for off
```

Two presses of a button, once for on and once for off, teach the panel both of its codes. When a
panel sends the same code for both states, or sends no state at all, the codes can be filled in
by hand in the settings of the panel bus.

### Button links

A **button link** binds panel buttons to relays. The state is shared in both directions:

- a panel button that is switched on drives the relays of the link, and lights up its own
  indicator at once,
- a relay that changes lights up the panel buttons of the link.

The link knows the kind of the relay it drives:

| Mode | What the relay does | The indicator of the panel |
|------|---------------------|-----------------------------|
| **Switch** (default) | Holds its state, the state of the relay is the state of the light. | Follows the state of the relay. |
| **Scene** | Only triggers a scene once, for example a scene of a smart home. | Answers the press and keeps its state, it is not switched off again by the relay falling back. |

A scene has no lasting state, so following the relay would switch the light off again right
away. The mode is chosen per link, so a relay that holds a state and one that only triggers a
scene can be used next to each other.

One button can be linked to several relays, and one relay can be linked to several buttons, a
link holds both groups. The link only reacts to a change, a target that already shows the wanted
state is left alone, so no needless frames go on the bus.

## How a slave is read

Every slave is read with **one** request that returns all of its coils at once. A 32 coil module
is read with a single frame:

```
0A 01 00 00 00 20 3C A9
│  │  └──┬──┘ └──┬─┘ └──┬─┘
│  │     │        │      └─ CRC
│  │     │        └──────── 0x0020 = 32 coils
│  │     └───────────────── start address 0
│  └─────────────────────── 0x01 = read coils
└────────────────────────── 0x0A = slave address
```

The response carries the same shape, so one request per slave and per round is enough.

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

The whole artwork is scaled to the target size, nothing is cut off, and the corners are rounded.
The dark variants are the same artwork on a dark background.

The source artwork lives in `assets/icon_source.png`. Run `python scripts/generate_brand.py` to
regenerate every file after a brand change.

## Home Assistant guidelines

The integration follows the [integration quality scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules)
and declares the state of every rule in `custom_components/symi_modbus/quality_scale.yaml`.

| Guideline | How it is met |
|------------|---------------|
| `log-when-unavailable` | A slave that stops answering is logged once at the info level, and once when it answers again. |
| `entity-unavailable` | The availability is tracked per slave, so a silent slave only makes its own entities unavailable. |
| `has-entity-name` | The entities are named in the context of their device and carry the slave address. |
| `runtime-data` | The hub, the panel buses and the links are stored in `ConfigEntry.runtime_data`. |
| `test-before-configure` | The config flow asks the first slave for its coils before the entry is created. |
| `parallel-updates` | `PARALLEL_UPDATES = 0`, the slaves share one serial line. |
| `unique-config-entry` | A connection can only be added once. |
| `entity-unique-id` | Every entity has a unique id built from the entry, the slave and the coil. |

## Development

```bash
docker run --rm -v "$PWD:/work" -w /work homeassistant/home-assistant:stable \
  sh -c "pip install pytest-asyncio -q && python -m pytest tests/ -q --asyncio-mode=auto"
```

- `tests/` covers the frame encoding, the hub behaviour, the reconnect logic, the panel protocols
  and the links.
- `scripts/modbus_simulator.py` serves a fake Modbus slave on a TCP port or a pseudo terminal,
  which is handy to try the integration without hardware.
- `scripts/verify_load.py` runs the hub against a simulated bus with several slaves and reports the
  timing of every round, the availability per slave and the memory growth. It also measures the
  panel side with a burst of four hundred button presses.

## Changelog

### 2.4.0

- A **link knows whether it drives a switch or a scene**. A relay that only triggers a scene has
  no lasting state, so the indicator light of the panel is not tied to it and is not switched off
  again by the relay falling back. The mode is chosen per link, the default is the switch.
- A press of a **panel button lights its own indicator right away**, so the panel answers the press
  without waiting for the relay to report its state.

### 2.3.1

- The **codes a panel uses for the state it reports** are learned now. A panel can use a code of
  its own for the state, so the codes of the frames the panel sends are kept per button and the
  indicator light is driven with the code the panel understands. The learned codes are stored with
  the entity, so they survive a restart.
- A **panel bus** takes the codes for the light as well, for the panels whose codes cannot be
  learned.
- The log tells which code a button uses for which state.

### 2.3.0

- The **indicator light of a panel** is driven with the frame the protocol
  document asks for, the report frame `0x04`. Panels that only take the set
  frame `0x03` can be served with the new **indicator light frame** setting of
  a panel bus.
- The **address of a button** is learned per button now. The protocol document
  asks for the device address and the channel of the button event to be
  repeated in the answer, and every button of a panel can use its own.
- A **button press of a panel** is reported in the log at the info level, and
  the first data a panel bus receives is reported as well, so a panel that does
  not answer can be told apart from a panel that answers in a way the
  integration does not understand.
- The log of a slave tells the coils that were read.

### 2.2.4

- A serial port that **another program holds open** cannot be used any more. The configuration
  refuses to save such a port and says why, instead of letting the connection split the bytes
  with the other program.
- When a panel bus finds out that its port is held by another program, it says so in the log and
  the entities of the panels turn `unavailable`, because the states cannot be trusted.

### 2.2.3

- The check for the programs that hold a serial port open runs in the executor now, so it does
  not block the event loop of Home Assistant any more.

### 2.2.2

- The **serial port of a panel bus** is a field that can be picked from the detected devices and
  that also takes a path that was entered by hand. The first port that is free comes filled in.
- The **data bits and the stop bits** are number fields with their default filled in, so the
  value is always visible.
- The **pickers of a link** show only the entities they belong to: the buttons of the wall
  panels on one side, the coils of the Modbus slaves on the other, each in the order of their
  panels and their lines.
- A serial port that **another program holds open** is marked in the picker, because the bytes
  on such a port are split between the programs. The integration warns about it in the log as
  well.

### 2.2.1

- The **serial port of a panel bus** is a picker now. The detected devices are listed, the first
  one that this integration does not use yet is filled in, and a path that is not listed can be
  entered by hand. A port that is already in use is not offered, because two connections on one
  port would split the bytes between them.
- **Slaves are added in batches**: the form carries the first address and the number of slaves
  that follow it.
- The **device of a slave** belongs to the subentry of that slave now, so it shows up once in the
  device list instead of twice.
- A slave, a panel bus or a link that was **renamed by hand keeps its name**, a later change of
  the configuration does not put the old name back.
- Several changes that follow each other result in **one reload** of the entry, so a batch of
  slaves is set up once and not once per slave.

### 2.2.0

- The slaves, the wall panel buses and the button links become **subentries** of the config
  entry, so they can be added, changed and removed on their own from the page of the entry.
  The lowest supported Home Assistant version is 2025.3.0, the first release with subentries.
- The **wall panels** of the **Symi**, **Clowire** and **LF** brands are supported. The brand
  decides which protocol is used to read the buttons and to drive the indicator lights.
- **Button links** keep a panel button and the relays it drives in sync, in both directions. One
  button can drive several relays and one relay can light up on several buttons.
- The scan interval accepts **fractional values**, so half a second is possible as well.
- The frames that the integration sends to a panel are recognised as their own echo, so a button
  press is not mistaken for a state change.
- The brand images get an even larger corner radius.

### 2.1.1

- Fixes the configuration wizard, which failed with a 500 error because the form was shown with a
  keyword that Home Assistant does not accept. The meaning of the fields is now part of the step
  descriptions.
- The brand images get a larger corner radius.
- The lowest supported Home Assistant version is 2024.6.0, the first release with the runtime
  data of a config entry.

### 2.1.0

- The brand images show the whole artwork scaled to the target size with rounded corners.
- The config flow asks the first slave for its coils before the entry is created.
- The hub is stored in `ConfigEntry.runtime_data` and the switch platform declares
  `PARALLEL_UPDATES = 0`.
- A slave that stops answering is logged at the info level, once per outage, as the quality scale
  asks for.
- The integration declares the state of every quality scale rule in `quality_scale.yaml`.

### 2.0.0

- One config entry describes one Modbus master and all of its slaves.
- The slaves share the scan interval, five slaves with a one second interval are asked every 200 ms.
- The availability is tracked per slave, and the entities carry the slave address in their name.
- A slave that stops answering times out after 0.5 s and is skipped for a while.
- The serial connection always speaks RTU, the MBAP header only exists on TCP.
- The brand images follow the sizes Home Assistant expects since 2026.3.

## License

MIT
