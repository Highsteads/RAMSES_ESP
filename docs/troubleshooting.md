---
title: When something goes wrong
nav_order: 10
---

# When something goes wrong

Each section starts with what you see, then what it means and what to do.

## The log says "No MQTT broker host configured"

The plugin has no address for the MQTT broker, so it cannot connect. Fill in **Broker Host** in **Plugins → RAMSES ESP → Configure**, or add `MQTT_BROKER` to your `IndigoSecrets.py` file, as the [Settings](settings.md) page explains.

## The log says "MQTT connection refused" or "MQTT connection failed"

The plugin reached for the broker and could not get in.

- **"Not authorized"** or **"Bad user name or password"** — check **Username (optional)** and **Password (optional)** in the settings, or the matching lines in `IndigoSecrets.py`, which win over the settings.
- **"connection failed"** — check the broker's address and port, and that the broker is running.

The plugin tries again every minute, so once the fault is put right it connects by itself.

## No zone devices appear

The plugin is not hearing the gateway.

- Check the Event Log for a line saying the plugin connected to the broker. If there is none, see the sections above.
- Check that **Discovered Gateway ID** in the settings has been filled in. If it is still empty, the gateway is not reaching the broker — check it has power, that it is on your Wi-Fi, and that its broker settings are right, as [Getting started](getting-started.md) describes.
- Tick **Enable Debug Logging** for a few minutes. If you see nothing arriving, the gateway is not sending. If messages arrive but no zones appear, the gateway may be out of radio range of the Evohome controller.

## The log says "Second gateway seen"

Two RAMSES-ESP gateways are sending to the same broker. The plugin uses the first one it found and ignores the other.

## Setting a temperature does nothing

The Event Log says why:

- **"MQTT not connected"** — the plugin has lost the broker. See the sections above.
- **"gateway not discovered yet"** — the plugin has not heard the gateway yet.
- **"no valid controller ID"** — the plugin has not yet heard a reading from the Evohome controller. Wait for the zone's first reading, then try again.

## A zone will not go back to its schedule

That is how it is meant to work. A temperature set from Indigo is a permanent override, which stays until something changes it. The plugin has no action to put a zone back on its schedule, so do that on the Evohome controller.

## A radiator valve ignores the temperature I set

If someone has turned the dial on a radiator valve by hand, the valve goes into its own local override and ignores temperatures sent to it until the dial is set back to its automatic position.

## Turning a zone off in HomeKit does nothing

Evohome zones only heat, so the plugin keeps every zone in Heat. To stop a room heating, set a low temperature instead — the lowest the plugin sends is 8 °C.

## A zone shows "valve silent"

A radiator valve in that zone has not been heard for longer than the silence time in the settings.

- Check the valve's batteries.
- Check the valve is still paired to your Evohome controller, and to the right zone.
- If you have replaced the valve, choose **Plugins → RAMSES ESP → Forget Valves Not Heard For 7 Days** once the old one has been quiet for a week.
- If the zone has no radiator valve at all, untick **Warn when a zone's valve has never been heard at all** in the settings.

When the valve is heard again, the error clears by itself.

## Valve Status stays "Not known yet"

Either no valve in that zone has been heard yet, or the plugin restarted recently. After a restart the plugin waits until it has been listening for longer than the silence time before calling any valve silent. Choose **Plugins → RAMSES ESP → Show Valve Battery and Liveness** to see what it has heard so far.

## Valve Battery (%) shows "unknown"

No valve in that zone has sent a battery report yet. Valves send one only now and then, so give it time.

## Online (broker link) shows "false"

The plugin lost its connection to the MQTT broker. It reconnects by itself, and **Online (broker link)** goes back to **true** with the next reading.

## Gateway Status shows "Offline"

The broker has reported that the gateway dropped off the network. **Online (broker link)** can still read **true** at the same time, because the plugin's own connection to the broker is fine. Check the gateway's power and your Wi-Fi, or let the [power-cycle watchdog](gateway-watchdog.md) deal with it.

## I got a "RAMSES Gateway Offline" alert

The gateway has been off the network for five minutes. Check its power and your Wi-Fi. If it does not come back by itself, switching its power off and on usually brings it back, which the [power-cycle watchdog](gateway-watchdog.md) can do for you.

## The watchdog says it is "not cycling" because the plug is unreachable

The gateway's smart plug is disabled, in error, or offline in Indigo, so the watchdog did not try to switch it. As the plug and the gateway usually share a network, this normally means the Wi-Fi itself is down rather than the gateway being stuck. When the network comes back, the gateway usually comes back with it.

## The log says the watchdog's plug device is "not found"

The plug chosen in **Gateway Power Plug** no longer exists in Indigo. Choose it again in **Plugins → RAMSES ESP → Configure**.

## The log says the gateway timestamp is "pre-NTP"

The gateway has not yet set its own clock, so the plugin uses the Mac's time for **Last Seen**. There is nothing to do.

## Still stuck?

Choose **Plugins → RAMSES ESP → Show Plugin Info**, copy the lines it writes to the Event Log, and post them on the [Indigo forum](https://forums.indigodomo.com) with a description of what you see. You can also [raise an issue on GitHub](https://github.com/Highsteads/RAMSES_ESP/issues).
