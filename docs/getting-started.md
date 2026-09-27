---
title: Getting started
nav_order: 2
---

# Getting started

## What you need

- Indigo 2025.2 or later.
- A Honeywell Evohome system — the controller and its radiator valves.
- A [RAMSES-ESP](https://github.com/IndaloTech/ramses_esp) gateway, joined to your Wi-Fi and plugged into USB power within radio range of your heating.
- An MQTT broker on your network, such as Mosquitto, which can run on the Mac that runs Indigo. You need its **network address** — the four numbers separated by dots, such as `192.168.1.10` — and, if you set one up, its username and password.
- The [Pushover plugin](https://www.indigodomo.com/pluginstore/) if you want alerts on your phone when the gateway goes offline. It is optional.

## 1. Point the gateway at your broker

The gateway has to know where your MQTT broker is. You set this by plugging it into a computer with a USB cable and typing a few commands into a serial terminal (at 115200 baud). The [RAMSES-ESP project](https://github.com/IndaloTech/ramses_esp) explains how to connect and how to join it to your Wi-Fi. The broker commands are:

```
mqtt user <username>
mqtt password <password>
mqtt broker mqtt://<broker address>:1883
reset
```

Put `mqtt://` in front of the broker's address. A bare address does not connect.

## 2. Install the plugin

1. Go to the [Releases page](https://github.com/Highsteads/RAMSES_ESP/releases/latest) and download `RAMSES_ESP.indigoPlugin.zip`
2. Unzip the downloaded file — you will get `RAMSES_ESP.indigoPlugin`
3. Double-click `RAMSES_ESP.indigoPlugin` — Indigo will install it automatically

Indigo asks whether to enable the plugin. Say yes.

## 3. Tell the plugin where the broker is

Open **Plugins → RAMSES ESP → Configure** and fill in:

- **Broker Host** — the broker's network address. Leave it blank if your `IndigoSecrets.py` file already gives it, as the [Settings](settings.md) page explains.
- **Broker Port** — leave it at 1883 unless you changed it on the broker.
- **Username (optional)** and **Password (optional)** — only if your broker asks for them.

Leave **Discovered Gateway ID** empty. The plugin finds the gateway by itself and fills it in. Leave everything else as it is to start with, and click **Save**. Every setting is explained on the [Settings](settings.md) page.

## 4. Check it works

Look in the Indigo Event Log. Within a few seconds you should see the plugin connect to the broker, then a line saying **Gateway discovered**, followed by the gateway's ID, which looks like `18:123456`.

As the Evohome controller sends out its regular readings, a device appears for each zone, in a new device folder called **RAMSES**. Each starts with a name such as **RAMSES Zone 3**, and shows the room temperature once the first reading arrives.

Try changing one zone's heat setpoint in Indigo. The device shows the new target straight away, and the controller's next broadcast confirms it. **Zone Mode** changes to **permanent override** when the controller next reports that zone's mode.

If nothing appears, the [When something goes wrong](troubleshooting.md) page goes through the usual causes.

## 5. Optional extras

- Rename the zone devices to suit you — the plugin never renames a device you have renamed.
- Look at the [Valve health](valve-health.md) settings, especially if any of your zones has no radiator valve.
- If the gateway is powered from a smart plug that Indigo controls, turn on the [power-cycle watchdog](gateway-watchdog.md).
