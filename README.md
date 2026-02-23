# RAMSES ESP — Indigo Plugin

An [Indigo Domotics](https://www.indigodomo.com/) plugin for the **RAMSES-ESP** USB gateway, providing local radio control of **Honeywell Evohome** heating systems via the RAMSES-II protocol — no cloud dependency.

## Overview

The RAMSES-ESP is an ESP32-S3 + CC1101 RF USB dongle that bridges the Honeywell Evohome 868 MHz radio network to MQTT. This plugin connects to that MQTT stream and creates native Indigo thermostat devices for each Evohome zone — giving you live temperatures, setpoint control, and zone mode tracking entirely locally.

**Why local?** The Honeywell EU cloud has proven unreliable. This plugin bypasses the cloud completely — if your RAMSES-ESP gateway can hear the TRVs, the plugin works.

## Features

- **Auto-discovery** — Gateway ID and zone thermostats discovered automatically from the radio message stream
- **12-zone support** — All Evohome zones created as native Indigo thermostat devices
- **Live temperatures** — Updated from 30C9 broadcasts (every few minutes)
- **Setpoint control** — Set heat setpoints via Indigo UI, action groups, schedules, or scripts
- **Zone modes** — Tracks schedule vs permanent override (from 2349 messages)
- **Zone names** — Auto-renames devices from Evohome controller (opcode 0004)
- **RAMSES folder** — All zone devices created inside a dedicated Indigo device folder
- **Robust MQTT** — Auto-reconnects on broker restart; all devices go offline cleanly on disconnect
- **No cloud** — Fully local via MQTT; works when Honeywell EU servers are down
- **Bundled paho** — paho-mqtt 1.6.1 included; no separate installation needed

## Requirements

| Requirement | Details |
|-------------|---------|
| Indigo | 2025.1 or later (API v3.4) |
| Python | 3.11 (bundled with Indigo) |
| Hardware | [RAMSES-ESP](https://github.com/IndaloTech/ramses_esp) USB gateway |
| MQTT broker | Any (e.g. Mosquitto on Home Assistant) |
| Heating system | Honeywell Evohome with RAMSES-II TRVs |

## Installation

1. Download the latest release `.zip` or clone this repo
2. Copy `RAMSES_ESP.indigoPlugin` to:
   ```
   /Library/Application Support/Perceptive Automation/Indigo 2025.1/Plugins/
   ```
3. In Indigo: **Plugins → Manage Plugins** — enable **RAMSES ESP**
4. Open **Plugin Config** and enter your MQTT broker details

## Configuration

| Setting | Description | Default |
|---------|-------------|---------|
| Broker Host | IP address of your MQTT broker | 192.168.1.x |
| Broker Port | MQTT port | 1883 |
| Username | MQTT username (if required) | — |
| Password | MQTT password (if required) | — |
| Gateway ID | Auto-filled on first connection | (auto) |
| Debug Logging | Verbose protocol logging | Off |

Leave **Gateway ID** blank — the plugin discovers it automatically from the `RAMSES/GATEWAY/+/info` topic within seconds of connecting.

## How It Works

```
Evohome TRVs  →  868 MHz radio  →  RAMSES-ESP dongle  →  MQTT  →  Plugin  →  Indigo devices
```

The plugin subscribes to `RAMSES/GATEWAY/<gw_id>/rx` and processes three opcodes:

| Opcode | Meaning | Action |
|--------|---------|--------|
| `30C9` | Zone current temperature | Updates `temperatureInput1` state |
| `2309` | Zone setpoint | Updates `setpointHeat` state |
| `2349` | Zone mode / override | Updates `zone_mode` state |
| `0004` | Zone name | Renames the Indigo device |

Setpoint commands are published to `RAMSES/GATEWAY/<gw_id>/tx` as W 2309 RAMSES-II packets.

## Device States

Each zone device exposes these states:

| State | Type | Description |
|-------|------|-------------|
| `temperatureInput1` | Float | Current zone temperature (degC) — shown in device list |
| `setpointHeat` | Float | Current heat setpoint (degC) |
| `zone_mode` | String | `schedule` or `permanent override` |
| `zone_controller_id` | String | Evohome controller address e.g. `01:091567` |
| `zone_name` | String | Zone name from Evohome controller |
| `last_seen` | String | Timestamp of most recent message |
| `online` | String | `true` / `false` (MQTT connectivity) |

## Controlling Setpoints

Use Indigo's native **Set Heat Setpoint** thermostat action — no custom action needed.

From a Python script:
```python
dev = indigo.devices[963505712]  # Zone device ID
indigo.thermostat.setHeatSetpoint(dev, value=21.0)
```

Or directly via the plugin:
```python
plugin = indigo.server.getPlugin("uk.co.clives.ramses.esp")
plugin.executeAction("requestZoneUpdate", deviceId=dev.id)
```

## RAMSES-ESP Gateway Setup

The gateway must be configured to connect to your MQTT broker. Via USB serial (115200 baud):

```
mqtt user <username>
mqtt password <password>
mqtt broker mqtt://<broker_ip>:1883
reset
```

> **Note:** Use the `mqtt://` URL prefix — bare IP addresses cause a connection failure.

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.1.3 | 23-Feb-2026 | Fix Zone 0 controller ID being wiped by direct TRV messages; fix misleading success log after publish failure |
| 1.1.2 | 23-Feb-2026 | Downgrade pre-NTP gateway timestamp log from WARNING to INFO; remove unhelpful "Check SNTP config" advice (firmware limitation) |
| 1.1.1 | 23-Feb-2026 | Fix hvacHeaterIsOn state error on new zone device creation |
| 1.1.0 | 23-Feb-2026 | Migrate zone devices to native Indigo thermostat type; add actionControlThermostat(); remove custom setpoint action |
| 1.0.5 | 22-Feb-2026 | Fix last_seen epoch timestamp when gateway NTP not synced; fix zone_mode defaulting to "unknown" |
| 1.0.4 | 22-Feb-2026 | Fix zone name auto-rename; add 0004 opcode parsing |
| 1.0.3 | 22-Feb-2026 | Zone devices created in "RAMSES" folder; last_seen shows clean local time |
| 1.0.2 | 22-Feb-2026 | Fix gateway ID corruption when pref value contained concatenated IDs |
| 1.0.1 | 21-Feb-2026 | Fix MQTT reconnection; add validatePrefsConfigUi() |
| 1.0.0 | 21-Feb-2026 | Initial release |

## Known Limitations

- **RAMSES-III not supported** — New Honeywell firmware (post-2025) uses a different protocol; the ramses_rf library also does not support it
- **SNTP on gateway** — The RAMSES-ESP firmware accepts the `sntp server` command but does not persist it to NVS (firmware limitation); timestamps may show as 1970 epoch until this is fixed upstream — the plugin handles this gracefully by using local system time
- **Local Override mode** — If a TRV dial is turned manually, the TRV enters local override and ignores remote setpoint commands until returned to AUTO position
- **Heat-only** — Plugin supports heat zones only; DHW and cooling not implemented

## Related Projects

- [ramses_esp](https://github.com/IndaloTech/ramses_esp) — The RAMSES-ESP gateway firmware
- [ramses_rf](https://github.com/zxdavb/ramses_rf) — Python RAMSES-II protocol library (used by the HA integration)
- [ramses_cc](https://github.com/ramses-rf/ramses_cc) — Home Assistant integration using ramses_rf

## Acknowledgements

- Protocol details from the [ramses_rf](https://github.com/zxdavb/ramses_rf) project
- paho-mqtt 1.6.1 bundled from the Eclipse Paho project (EPL-2.0 / EDL-1.0)

## License

MIT — see [LICENSE](LICENSE)
