---
title: Settings
nav_order: 8
---

# Settings

Open these with **Plugins → RAMSES ESP → Configure**. They apply to the whole plugin. The zone devices have no settings of their own.

## MQTT Broker Settings

| Setting | What it does |
|---|---|
| **Broker Host** | The network address of your MQTT broker, such as `192.168.1.10`. The dialog will not save without one, unless your `IndigoSecrets.py` file gives the address, as explained below. |
| **Broker Port** | The broker's port number, 1883 to start with. It must be a whole number from 1 to 65535. You can leave it blank if your `IndigoSecrets.py` file gives both the address and the port. |
| **Username (optional)** | The broker's username, if it asks for one. |
| **Password (optional)** | The broker's password, if it asks for one. Leave it blank if the broker does not ask. |

If you change the broker's address or port, the plugin reconnects as soon as you click Save.

### Keeping the broker details in one file

If you run several of my plugins, you can keep the broker's address, port, username and password in one shared file instead of typing them into each plugin. The file is called `IndigoSecrets.py` and lives in `/Library/Application Support/Perceptive Automation/`.

A blank copy, `IndigoSecrets_example.py`, comes inside the plugin. Copy it to that folder, rename it `IndigoSecrets.py`, and fill in these lines with your own details:

```python
MQTT_BROKER   = "192.168.1.10"
MQTT_PORT     = 1883
MQTT_USERNAME = "your username"
MQTT_PASSWORD = "your password"
```

When the file has a value, it is used, whatever the Configure dialog says, and you can leave those boxes in the dialog blank. The port in the file is only used when the file gives the broker's address too. If the address is left blank in the file, everything comes from the dialog, port included, so the 1883 in the blank copy never overrides a port you typed there.

If neither the file nor the dialog gives a broker address, the plugin writes an error to the Event Log and does not connect.

## Gateway Discovery

| Setting | What it does |
|---|---|
| **Discovered Gateway ID** | The ID of the RAMSES-ESP gateway, such as `18:123456`. Leave it empty — the plugin fills it in when it first hears the gateway. To make it look for the gateway again, clear the field, click Save, and restart the plugin. If you type an ID yourself it must be in that form, two digits, a colon and six digits. |

## Gateway Power-Cycle Watchdog

The [Keeping the gateway running](gateway-watchdog.md) page explains what the watchdog does.

| Setting | What it does |
|---|---|
| **Enable Power-Cycle Watchdog** | Tick this to have the plugin switch the gateway's smart plug off and on when the gateway stays offline. It is unticked to start with. |
| **Gateway Power Plug** | The Indigo device for the smart plug the gateway is plugged into. The list shows Indigo's on/off devices. You must choose one before the dialog will save with the watchdog ticked. |
| **Cycle after offline (minutes)** | How long the gateway must be offline before the plug is switched off and on, 15 to start with. Repeat attempts are spaced this far apart too. From 5 to 1440. |
| **Plug off time (seconds)** | How long the plug stays off, 10 to start with. From 3 to 120. |
| **Max cycles per day** | The most times a day the plug is switched off and on, 3 to start with. After that the watchdog sends an alert and waits for you. From 1 to 20. |

## Valve health

The [Valve health](valve-health.md) page explains these.

| Setting | What it does |
|---|---|
| **Report a valve silent after (hours)** | How long a valve can go unheard before it is called silent, 6 to start with. From 1 to 168. A valve only transmits when it has something to say, so a short time here gives false alarms. |
| **Mark the zone device in error when a valve goes silent** | Ticked, a silent valve shows as an error on the zone device and gives one warning in the Event Log. It is ticked to start with. |
| **Warn when a zone's valve has never been heard at all** | Ticked, a zone from which no valve has ever been heard is treated as silent once the plugin has been listening long enough. Untick it if a zone has no radiator valve. It is ticked to start with. |

## Logging

| Setting | What it does |
|---|---|
| **Enable Debug Logging** | Writes every message the plugin receives to the Event Log. Only useful when chasing a problem, as it adds a great many lines. |
