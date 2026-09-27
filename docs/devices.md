---
title: Your zones
nav_order: 3
---

# Your zones

Each Evohome heating zone becomes one Indigo thermostat, called a **RAMSES Zone Thermostat**. You never add these yourself — the plugin creates one the first time it hears a reading for that zone, and puts it in a device folder called **RAMSES**. Evohome has at most twelve zones, numbered 0 to 11, and the device's address in Indigo is its zone number.

## Names

A new device is called **RAMSES Zone** followed by its number. When the Evohome controller sends out the zone's name, the plugin stores it in **Zone Name** and, if the device still has its first name, renames it to **RAMSES** followed by the zone's name, such as **RAMSES Living Room**.

The plugin asks the controller for the names each time it starts, and also picks them up whenever the controller announces them. The controller does not always answer that request, so a name can take a while to arrive. Until it does, **Zone Name** is filled in from the device's own name, leaving off a trailing word **Radiator** if there is one.

You can rename a device however you like. Once it no longer has its first name, the plugin never renames it again.

## What a zone shows

These are the ordinary thermostat readings, the same as any other Indigo thermostat:

| Shown as | What it means |
|---|---|
| **Temperature** | The room temperature Evohome is using for this zone. This is what the device list shows. |
| **Heat setpoint** | The temperature the zone is aiming for. |
| **Heating indicator** | Comes on when the room is more than 0.3 °C below its setpoint. This is the plugin's own estimate from those two numbers, not a report from the valve. |
| **Mode** | Always **Heat**. Evohome zones only heat, so the plugin keeps them in Heat even if HomeKit or anything else asks for Off. |
| **Battery level** | The lowest battery reading among the zone's radiator valves, once one has been reported. See [Valve health](valve-health.md). |

And these are the plugin's own states, which you can use in triggers and on control pages:

| Shown as | What it means |
|---|---|
| **Zone Mode** | **schedule** when the zone is following its Evohome schedule, **permanent override** when its temperature has been set by hand and stays put. Any other mode Evohome reports shows as the word **mode** followed by a code number. |
| **Zone Name** | The zone's name, as described above. |
| **Controller ID** | The radio address of your Evohome controller, such as `01:123456`. The plugin needs it before it can send a new temperature. |
| **Last Seen** | The date and time of the last reading the plugin applied to this zone. |
| **Online (broker link)** | **false** when the plugin has lost its connection to the MQTT broker, and **true** again as soon as fresh readings arrive. It is about the plugin's own connection only, so it stays **true** when the gateway itself dies while the broker is still running. Use **Gateway Status** for the gateway. |
| **Gateway Status** | **Online** while the RAMSES-ESP gateway is connected, **Offline** once the broker reports it has dropped off, and **Not known** until the gateway has first been heard, or while the plugin itself has lost the broker. Every zone shows the same value, as they all share the one gateway. Use this in a trigger to hear about a dead gateway. |

A zone also carries seven states about its radiator valves — **Valve Status**, **Valve Battery**, **Valve Battery (%)**, **Valve Last Heard**, **Valves In This Zone**, **Valve Addresses** and **Valve Summary**. The [Valve health](valve-health.md) page explains them.

A brand-new device shows 0.00 for its temperature and setpoint until its first real reading arrives.

The plugin also creates one device for the boiler relay, which the [Your boiler](boiler-relay.md) page describes.

## Deleting a zone device

If you delete a zone device, the plugin creates it again the next time it hears a reading for that zone.
