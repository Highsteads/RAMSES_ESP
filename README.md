# RAMSES ESP for Indigo

**See and control your Honeywell Evohome heating from Indigo, locally over radio, with no Honeywell account or cloud.**

**Version:** 1.14.0 | **Author:** CliveS & Claude | **Needs:** Indigo 2025.2 or later, a RAMSES-ESP gateway and an MQTT broker

**[Read the full guide](https://highsteads.github.io/RAMSES_ESP/)** — setting up, what everything means, and what to do when something goes wrong.

---

## What it does

This plugin lets [Indigo](https://www.indigodomo.com) work with a **Honeywell Evohome** heating system without going through Honeywell's servers. It listens to the radio messages your Evohome controller and radiator valves already send to each other, and sends its own when you change a temperature, so it keeps working when the internet or Honeywell's servers are down.

- **Creates a thermostat in Indigo for each Evohome zone** by itself, as soon as it hears the zone on the radio, and names it after the zone once the controller sends the name.
- **Shows each room's temperature and target temperature,** kept up to date from the Evohome controller's own regular broadcasts.
- **Sets a room's target temperature** from Indigo, a control page, a schedule, a trigger or HomeKit, the same as any other Indigo thermostat. The zone keeps that temperature until something changes it.
- **Reports on the radiator valves themselves** — the lowest battery in each zone, when a valve was last heard, and whether any has stopped answering — so a dead valve shows up in Indigo rather than as a cold room.
- **Shows when the boiler is being called for heat,** from the Evohome boiler relay (BDR91), as an on/off device with the controller's heat demand alongside.
- **Tells you when the gateway goes offline,** through the Pushover plugin if you have it.
- **Can switch the gateway off and on again** through a smart plug when it stays offline, and checks that the plug really switched.

## What it works with

| You need | What it is |
|---|---|
| **Honeywell Evohome** | The controller and its radiator valves. The plugin handles heating zones, not hot water. |
| **[RAMSES-ESP gateway](https://github.com/IndaloTech/ramses_esp)** | A small USB stick with a radio receiver tuned to the frequency Evohome uses, and a Wi-Fi chip that passes on everything it hears. It plugs into any USB power supply within radio range of your heating. |
| **An MQTT broker** | A small program, such as Mosquitto, that passes messages between devices on your network. The gateway posts what it hears there, and the plugin collects it. It can run on the Mac that runs Indigo. |

## Installing

1. Go to the [Releases page](https://github.com/Highsteads/RAMSES_ESP/releases/latest) and download `RAMSES_ESP.indigoPlugin.zip`
2. Unzip the downloaded file — you will get `RAMSES_ESP.indigoPlugin`
3. Double-click `RAMSES_ESP.indigoPlugin` — Indigo will install it automatically

## Setting it up

1. Set the gateway up to send to your MQTT broker, as the [guide](https://highsteads.github.io/RAMSES_ESP/getting-started.html) describes.
2. Open **Plugins → RAMSES ESP → Configure**, fill in **Broker Host** with the broker's network address — the four numbers, such as `192.168.1.10` — and its username and password if it has them, then click **Save**.
3. Leave **Discovered Gateway ID** empty. The plugin finds the gateway by itself, and a thermostat for each zone appears in a device folder called **RAMSES** as the Evohome controller sends out its readings.

The [full guide](https://highsteads.github.io/RAMSES_ESP/) goes through each step, explains every setting, and covers what to do if something does not work.

## What's new

**v1.14.0** — The boiler relay writes one line an hour to the Event Log instead of one per switch, a deleted relay device stays deleted, and a rare freeze on a new install is fixed.

**v1.13.0** — Each zone's weekly timetable is read from the Evohome controller every night, over the radio, and shown on the zone as **Timetable**. A new action reads them on demand.

**v1.12.0** — A new **Set Temperature for a While** action sets a zone for a number of minutes, after which Evohome puts it back on its own timetable by itself, so a stopped Indigo hands the house back to Evohome. A new **Override Ends** state shows when that will be.

**v1.11.0** — A gateway that stays connected but passes on no radio messages is now treated as offline, so the alert and the watchdog act on it. A new setpoint shows only once Evohome reports it back, and is sent again until it does. Only your own controller's messages count, so the valves' own reports no longer flick a setpoint back.

**v1.10.0** — A new **Boiler Relay** device shows when Evohome is calling the boiler for heat, by listening to the boiler relay (BDR91). It is an on/off sensor, so triggers and graphs can follow it, and it carries the controller's heat demand alongside. It says so if the relay goes quiet for an hour.

**v1.9.0** — Each zone has a new **Gateway Status** that says whether the gateway itself is alive, which the old **Online** never could. A silent valve's error now stays on the zone until the valve is heard again, instead of being wiped by the next temperature reading. The settings also save with the broker's address left blank when `IndigoSecrets.py` gives it, and the port can come from that file too.

**v1.8.0** — The power-cycle watchdog checks that the gateway's plug really switched before counting a cycle or sending an alert. If the plug is unreachable too, it does not try, and says the trouble looks like the network rather than a stuck gateway.

**v1.7.0** — A radiator valve that was already dead when the plugin started is now reported as silent, instead of reading "Not known yet" for ever. A new setting turns this off for a zone with no radiator valve.

Every version is listed in the [version history](https://highsteads.github.io/RAMSES_ESP/changelog.html).

## Acknowledgements

- The radio protocol details come from the [ramses_rf](https://github.com/zxdavb/ramses_rf) project.
- The gateway firmware is the [ramses_esp](https://github.com/IndaloTech/ramses_esp) project.
- The plugin talks to the MQTT broker with the Eclipse Paho library (EPL-2.0 / EDL-1.0).

## Authors & licence

Vibed into existence by **CliveS**, who knew what he wanted, argued until he got it, and tested it on a real house. Typed at inhuman speed by **Claude** (Anthropic), who mostly did as it was told.

© 2026 CliveS · [MIT licence](LICENSE) — copy it, fork it, bend it, break it, fix it, ship it. If it breaks, you get to keep both pieces.
