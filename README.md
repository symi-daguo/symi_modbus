# Symi Modbus

<img src="custom_components/symi_modbus/brand/logo.png" alt="Symi Modbus" height="96" align="right">

[English](README.md) | [中文](README.zh-CN.md)

Home Assistant integration for **Symi Modbus relay modules** and **Symi wall panels**, over serial
RTU or TCP.

One config entry describes **one Modbus master** (a serial port or a TCP endpoint). Everything that
belongs to it is a **subentry** that can be added, changed and removed on its own: the slaves, the
wall panel buses and the links between a panel button and a relay.

| | |
|---|---|
| Version | **2.6.8** |
| Home Assistant | **2025.3.0** or newer |
| Dependencies | `pyserial`, `pyserial-asyncio-fast` |

## Highlights

- **Serial RTU and TCP**, with the frame format chosen per connection.
- **One master, many slaves** – every slave becomes its own device with one switch per coil.
- **Wall panels** – every button of a panel becomes a switch, the indicator light is driven back.
- **Button links** – a panel button drives relays, and a relay lights up the panel buttons.
  The state is shared in both directions.
- **The indicator light of a panel is driven with the codes the panel understands**, they are
  learned from the panel itself.
- **The configuration can be exported and imported**, and it travels with a backup of Home
  Assistant.
- **Quiet logging** – a failing slave is reported once per outage, not once per poll.

## Installation

**HACS** – add `https://github.com/symi-daguo/symi_modbus` as a custom repository of the type
*Integration*, install it and restart Home Assistant.

**Manual** – copy `custom_components/symi_modbus` into the `custom_components` directory of your
configuration and restart Home Assistant.

In Docker the serial devices have to be mapped into the container:

```yaml
devices:
  - /dev/ttyUSB0:/dev/ttyUSB0
```

## Quick start

All of it is done in **Settings → Devices & services**.

**1. The master.** *Add integration → Symi Modbus* opens the flow. Pick **Serial** or **TCP**, give
the line its settings and confirm the first slave. The entry that is created is the master, it
holds the connection to the bus.

**2. The slaves.** On the page of the entry the button **Add slave** opens the form of a slave.
Fill in the unit ID, the first coil and the number of coils. A slave becomes a device of its own
with one switch per coil.

**3. The panels and the links.** **Add panel bus** opens the form of the line the wall panels hang
on: the brand, the serial port, the baud rate and the addresses of the panels on that line.
**Add button link** ties a panel button to the relays of a slave.

Every part can be **changed or removed on its own**, a change only touches the part it was made
on. A name that was changed by hand is kept.

## Settings

| Setting | Where | Meaning |
|---------|-------|---------|
| Scan interval | Options of the master | The period of one round over all slaves. The default is one second, half a second is allowed. |
| Baud rate, data bits, parity, stop bits | Master, panel bus | The settings of the line. The default is 9600 baud, 8 data bits, no parity and one stop bit. |
| Slave address | Slave | The unit ID of the device, 10 is `0x0A`. |
| First coil, coil count | Slave | The coils the device has. A 32 channel module has 32. |
| Panel address, panel count | Panel bus | The addresses of the panels on that line. |
| Buttons per panel | Panel bus | How many keys a panel of that brand has, eight for Symi and LF. |
| Advanced settings | Panel bus | The frame of the indicator light and the codes of the light. Only needed when the light does not behave. |
| Mode | Button link | **Switch** (default) keeps the state of the relay, **Scene** takes the state the press gives it. |

### The keys of a panel

A panel has the keys **one to eight**, the protocol document of the vendor says so. The number of
keys of the panel bus is taken from the protocol of its brand, so the entities of the bus are
exactly the keys of the panel and no more.

The panel numbers a key with the channel of the frame. A key that drives a scene is reported with
the channel `0x1N`, where `N` is the number of the key: the upper bits say that the key is used for
a scene, the lower bits are the number of the key. Such a key is the same key as in the switch
mode, it does not become a key of its own. The channel `0x0F` is the backlight of the panel and
not a key at all.

### The order of the entities

The entities stand in the order a person expects: the coils of the slaves first, from the first
slave to the last, then the buttons of the panels, from the first panel to the last. The pickers of
a button link show the entities in that order too, so it is easy to see which coils have no button
yet.

### The indicator light of a panel

A panel reports the state of a key with `0x01` for on and `0x00` for off, the protocol document
says so. A panel that uses values of its own is learned: the integration keeps the values with
the entity, so the light is driven with the values the panel understands.

The log shows what was learned:

```
Panel 1 button 1 uses the code 1 for on
Panel 1 button 1 uses the code 0 for off
```

Two presses of a button, once for on and once for off, teach the panel both of its codes. When a
panel never reports its state, the codes can be filled in by hand in the **advanced settings** of
the panel bus.

**The codes of the light have nothing to do with the mode of a link.** The mode belongs to the link
between the button and the relay, the codes belong to the panel bus.

### The modes of a link

| Mode | What the relay does | The indicator of the panel |
|------|---------------------|-----------------------------|
| **Switch** (default) | Holds its state, the state of the relay is the state of the light. | Follows the state of the relay. |
| **Scene** | Takes the state the press of the button gives it, for example a scene of a smart home. | Answers the press and keeps its state, it is not switched off again by the relay falling back. |

### A panel bus and a master never share a port

A master asks the slaves and waits for their answer, a panel sends its report on its own, the two
would mix their bytes. **Two panel buses can share a port**: a RS485 line carries the panels of one
brand and every frame carries the address of the panel it belongs to.

## Backup, export and import

The configuration is part of the **backup of Home Assistant**, a restore brings the integration
back the way it was.

For the case where only this integration should be moved, the configuration can be written out as
text and read back. Both are in the **Configure** button of the master:

| Step | What it does |
|------|--------------|
| **Export the configuration** | Writes the connection, the slaves, the panel buses and the links as YAML into a field. |
| **Import a configuration** | Takes the YAML back. The parts of the master that are not in the text are removed. |

A link is written as the devices it belongs to and not as an entity id, so the text stays readable
and a link keeps working when the serial port is named differently on the other machine. The text
can be edited before it is imported.

## Troubleshooting

**The light of a panel does not follow the relay.** The log says which codes the panel uses and
which frame goes out. A panel that only takes the set frame `0x03` needs the **indicator light
frame** of the advanced settings.

**A panel bus is not working.** The log says why:

```
The panel bus /dev/ttyS2 cannot be opened: Could not configure port: (5, 'I/O error')
```

A port that another program holds is refused, because the bytes would be split between the
programs.

**Looking at the raw data of the bus.** The page of the integration has a **Download diagnostics**
button. The file it produces holds the last frames that went over the master line and over every
panel line, as hexadecimal, together with the codes that were learned. The log stays quiet, the
data is only there when it is asked for.

## Development

```bash
docker run --rm -v "$PWD:/work" -w /work homeassistant/home-assistant:stable \
  sh -c "pip install pytest-asyncio -q && python -m pytest tests/ -q --asyncio-mode=auto"
```

- `tests/` covers the frames, the hub, the panel protocols, the links and the configuration.
- `scripts/modbus_simulator.py` serves a fake Modbus slave on a TCP port or a pseudo terminal.
- `scripts/verify_load.py` runs the hub against a simulated bus and reports the timing of every
  round, the availability per slave and the memory growth.
- `scripts/make_release.py` builds the archive of a release.
- `scripts/generate_brand.py` regenerates the brand images from `assets/icon_source.png`.

## Changelog

### 2.6.8

- **A key of a panel that sends the same code every time flips the light of the button.** The
  protocol has two kinds of keys: one kind tells the state of the light, the other kind sends the
  same code for every press and is a trigger. Which kind a key is shows in the frames, and what was
  found out about it is kept with the entity, so the key still flips after a restart.
- **The code of a trigger is not the code of a state.** It is not learned, and the light of the
  button is driven with the codes of the protocol.
- **The state a panel reports does not flip the light of a trigger by itself.** The report of the
  panel is the answer to the light that was written, and the state follows the press.
- A **scene takes the state the press of the button gives it** and not always the state that is
  on. The relay of a scene was never switched off that way.

### 2.6.7

- The **light of a panel is driven with the set frame** `0x03`, the frame the protocol document
  asks for. The panel answers with a report frame. A report frame was used before, the panel did
  not answer it and the light stayed dark, and the answer of a panel could be taken for the press of
  a button, so the buttons of the panels on the line followed each other.
- The **cards of the configuration stand in the order a person expects**: the slaves of the line
  first, then the panel buses, then the links of the buttons, in the order of the relay they
  drive. The cards are shown in the order of their titles, so the title of every card carries the
  place it has, `01` for the first slave, `02` for the second one and so on.

### 2.6.6

- The **light of a key is driven with the code of the panel** again. A code that was never learned
  was written as a zero, and the zero is the code a panel uses for the state that is off. A button
  whose code for "on" was never learned was therefore driven with the code for off, and the light
  stayed dark when it was to be turned on.
- A **double click and a long press are not the code of a state**. The operation information of the
  protocol says what the key did, only a single click is a state. The other values were learned as
  the code for "on" and were written to the light.
- The **entities stand in the order a person expects**: the coils of the slaves first, from the
  first slave to the last, then the buttons of the panels, from the first panel to the last. An
  entity that an earlier version created had a name of its own in the registry, and such a name is
  reset now. The pickers of a button link show the entities in that order as well.

### 2.6.5

- **A panel has the keys one to eight, the protocol of the vendor says so.** The number of keys of
  a panel bus is taken from the protocol of its brand now, so the entities of the bus are exactly
  the keys of the panel and no more. The limit of 32 keys of version 2.6.1 was wrong and is gone.
- **A key that drives a scene is the same key.** Such a key is reported with the channel `0x1N`,
  where `N` is the number of the key: the upper bits of the channel say that the key is used for
  a scene, they are not a key number. The channel `0x11` was taken for the key 17 before, so keys
  that the panel does not have were in the entity list and in the links of the buttons.
- The channel `0x0F` is the backlight of the panel and not a key, it does not show up as a button
  any more.

### 2.6.4

- The **state of a press is read the way the brand of the panel reads it**, and not by flipping the
  state of the entity. The entity can be out of step because the relay wrote the light, and the
  code of the panel was then learned for the wrong state: a panel that reports the state with the
  code zero was taken for a panel that turns the light on with the code zero.
- A **code that was set by hand is the most certain one** and is used before the codes that were
  learned.
- The buttons of the **LF panels toggle their light** again. The frame of those panels carries no
  state, and the code that was learned from the first press hid the toggle.

### 2.6.3

- A frame that was **damaged on the line** is dropped. Two panels that report at the same time, or
  a panel that reports while a frame of ours goes out, damage each other, and the address byte of
  the damaged frame belongs to the other panel. The frame was taken for a button of this panel
  before, so a button of one panel could drive the panel of the other one.

### 2.6.2

- The **code of a press tells the state** of the button when it is known. The state was flipped
  before, so a code could be learned for the wrong state as soon as the light of a button was
  written by the relay. A panel that reports the state with the code zero is understood now as
  well, and two codes that cannot be told apart are not used any more.
- The **echo of a frame is told apart by the code** it carries and not by the state. A panel that
  uses a code of its own for the state was therefore taken for a press of a button, which wrote the
  relays when a batch of buttons was switched.
- Nothing is **written while a panel may still be sending**, so the frames of the integration and
  the reports of the panels do not damage each other on the line.

### 2.6.1

- A **scene is triggered with every press** of its button. A button of a panel is a toggle, so
  following its state switched the relay off on the second press and the scene did not fire.
- A panel can have **up to 32 buttons** now. The number of keys was thought to be higher than
  eight, which turned out to be wrong.
- A panel that **reports a button without an entity** says so in the log and names the number of
  buttons the panel bus has to be set to.

### 2.6.0

- **Two panel buses can share a serial port.** A RS485 line carries the panels of one brand and
  every frame carries the address of the panel it belongs to, so one connection reads the line
  for all of them and the bytes are never split.
- The **diagnostics** hold the raw data of the bus: the last frames that went over the master
  line and over every panel line, and the codes the panels use. They are downloaded from the
  page of the integration, the log stays quiet.
- The document is **shorter** and comes in **English and Chinese**.

### 2.5.0

- The **configuration can be exported and imported** as text. A link is written as the devices it
  belongs to, so it keeps working when the serial port is named differently on the other machine.
- The configuration is part of the **backup of Home Assistant**.
- The settings of the **indicator light** are folded into an **advanced settings** section.
- The **options** of a master have a menu: the polling interval, the export and the import.
- The **codes a panel uses** are kept with the entity again. They were written with a call that
  Home Assistant does not have, so they were lost on every restart.
- A panel bus is only reported as **ready when its port is really open**, and a bus that cannot be
  opened says why.
- The **diagnostics** hold the raw data of the bus.

### 2.4.2

- The codes of the indicator light say what an empty field means.
- The installation through HACS follows the release tag of the repository again.

### 2.4.1

- The **light of a panel is written again whenever the relay of the link changes**, even when the
  entity of the panel already shows the wanted state.
- The **write of a coil** is logged at the debug level.

### 2.4.0

- A **link knows whether it drives a switch or a scene**.
- A press of a **panel button lights its own indicator right away**.

### 2.3.1

- The **codes a panel uses for the state it reports** are learned now, per button, and are kept
  with the entity.

### 2.3.0

- The **indicator light of a panel** is driven with the report frame `0x04` the protocol document
  asks for, and the **address of a button** is learned per button.

### 2.0 – 2.2

- The integration was split into **one master with subentries**: the slaves, the panel buses and
  the links can be added, changed and removed on their own.
- The three **panel protocols** were brought in, the **indicator light** of a panel is driven back
  and the **codes of a panel** are learned.
- A serial port that another program holds is **refused**, because the bytes would be split
  between the programs.
- The **polling** of the slaves was made fair, a slave that does not answer is skipped for a
  while instead of holding up the bus.

## License

MIT, see [LICENSE](LICENSE).
