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
| Indigo | 2025.2 or later (API v3.4+) |
| Python | 3.13 (bundled with Indigo 2025.2) |
| Hardware | [RAMSES-ESP](https://github.com/IndaloTech/ramses_esp) USB gateway |
| MQTT broker | Any (e.g. Mosquitto running locally) |
| Heating system | Honeywell Evohome with RAMSES-II TRVs |

## Credentials — `IndigoSecrets.py` vs `IndigoSecrets_example.py`

This plugin (along with all CliveS Indigo plugins) reads sensitive values from
a shared master credentials file at:

`/Library/Application Support/Perceptive Automation/IndigoSecrets.py`

| File | Purpose | Real data? | Committed to GitHub? |
|------|---------|------------|----------------------|
| `IndigoSecrets.py` | Working file the plugin reads at runtime. Keep a backup in a password manager. | YES | **NO** — listed in `.gitignore` |
| `IndigoSecrets_example.py` | Template only — empty placeholders. Shipped in the plugin bundle. | NO | YES |

If you do not have `IndigoSecrets.py`, copy `IndigoSecrets_example.py` from
the plugin bundle to that location and fill in your values. Or skip
`IndigoSecrets.py` entirely and enter values via the plugin's configuration
dialog — `IndigoSecrets.py` wins over the dialog when both are set.

If a required value is set in NEITHER source the plugin logs an ERROR
pointing the user to either fill in the matching field or add the key to
`IndigoSecrets.py`.
## Installation

1. Go to the [Releases page](https://github.com/Highsteads/RAMSES_ESP/releases) and download `RAMSES_ESP.indigoPlugin.zip`
2. Unzip — you will get `RAMSES_ESP.indigoPlugin`
3. Double-click `RAMSES_ESP.indigoPlugin` — Indigo will install it automatically
4. In Indigo: **Plugins → Manage Plugins** — enable **RAMSES ESP**
5. Open **Plugin Config** and enter your MQTT broker details

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
| 1.2.7 | 10-May-2026 | Plugin version is now read dynamically from Info.plist (`self.pluginVersion`) — no separate Python constant. Added bundled `plugin_utils.py` with `log_startup_banner()` invoked in `__init__`, plus `MenuItems.xml` with a Show Plugin Info menu callback. Hardcoded broker IP fallback removed; PluginConfig default cleared. `_read_prefs` now logs ERROR if no broker host is configured in either IndigoSecrets.py or PluginConfig. `IndigoSecrets.py` imports split into per-key try/except so a missing single key doesn't blank the rest. PluginConfig version note refreshed (was stuck at 1.1.8). |
| 1.2.6 | 05-May-2026 | Add 5-minute delay before sending "gateway offline" Pushover notification — prevents spurious alerts on brief gateway hiccups. Restored alert is only sent if the offline alert actually fired. |
| 1.2.5 | 08-Apr-2026 | Gateway offline/restored Pushover notifications via Pushover Indigo plugin. |
| 1.2.4 | 04-Apr-2026 | MQTT broker migrated from .140 to .160 after Home Assistant VM decommission; broker now runs natively on the Indigo Mac. |
| 1.1.8 | 24-Feb-2026 | Setpoint command log lines downgraded to debug-only; RAMSES ESP entries no longer interleave with EvoHome script output in event log |
| 1.1.7 | 24-Feb-2026 | Fix HomeKit showing OFF: enable SupportsHvacOperationMode + ShowCoolHeatEquipmentStateUI; re-fetch device after replacePluginPropsOnServer(); add SetHvacMode handler to lock zones to Heat |
| 1.1.6 | 24-Feb-2026 | Add hvacHeaterIsOn (flame indicator) and hvacOperationMode updates on temp refresh for HomeKit |
| 1.1.5 | 24-Feb-2026 | Seed zone_name from device name on startup for zones where 0004 has not yet been received |
| 1.1.4 | 24-Feb-2026 | Send RQ 0004 on startup to populate zone_name states |
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
