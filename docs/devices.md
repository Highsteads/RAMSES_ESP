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
| **Zone Mode** | **schedule** when the zone is following its Evohome schedule, **permanent override** when its temperature has been set and stays put, and **temporary override** when it has been set until a time, after which Evohome goes back to the schedule. Evohome's other two kinds show as **advanced override** and **countdown override**. |
| **Changed By** | Who last changed the zone's temperature: *indigo* (Indigo sent it), *timetable* (the zone went back to its Evohome timetable) or *manual* (somebody changed it at the controller, on a valve's wheel or in the app). A change counts as Indigo's only if it matches something the plugin sent in the last 15 minutes: the same temperature, the same kind of setting and the same end time. Somebody holding a room for good at the temperature Indigo has just set therefore shows as *manual*. Blank until the first change after installing 1.15.0. |
| **Changed At** | When that change was reported, such as *2026-10-05 18:42:10*. |
| **Override Ends** | When a temporary override runs out, such as *2026-10-05 21:30*. Blank for any other mode. |
| **Timetable** | The zone's weekly timetable as stored on the Evohome controller, in words, such as *Every day: 5am 17, 9am 18, noon 20, 7pm 21, 9pm 20, 10pm 16.* This is what the zone follows whenever nothing overrides it. Read at 3:15am each day. |
| **Timetable Data** | The same timetable in a form other plugins can read. EvoHome Heating Controller uses it to check the timetable against its own plans. |
| **Timetable Read** | When the timetable was last read, such as *2026-10-05 03:15*. |
| **Zone Name** | The zone's name, as described above. |
| **Controller ID** | The radio address of your Evohome controller, such as `01:123456`. The plugin needs it before it can send a new temperature. |
| **Last Seen** | The date and time of the last reading of any kind the plugin applied to this zone: a temperature, a setpoint or a mode. |
| **Temperature Last Reported** | The date and time the controller last reported this zone's temperature. **Last Seen** moves on setpoint reports too, which arrive whether or not the temperature does, so this is the one to use to tell a current temperature from an old one. Blank until the first temperature arrives. |
| **Temperature Last Reported (seconds)** | The same moment as a count of seconds since 1 January 1970. The date and time above follow the clock on the wall, which repeats an hour when the clocks go back in October, so another plugin working out how old a reading is should use this one. Blank until the first temperature arrives after installing 1.17.0. |
| **Online (broker link)** | **false** when the plugin has lost its connection to the MQTT broker, and **true** again as soon as fresh readings arrive. It is about the plugin's own connection only, so it stays **true** when the gateway itself dies while the broker is still running. Use **Gateway Status** for the gateway. |
| **Gateway Status** | **Online** while the RAMSES-ESP gateway is connected, **Offline** once the broker reports it has dropped off, and **Not known** until the gateway has first been heard, or while the plugin itself has lost the broker. Every zone shows the same value, as they all share the one gateway. Use this in a trigger to hear about a dead gateway. |

A zone also carries seven states about its radiator valves — **Valve Status**, **Valve Battery**, **Valve Battery (%)**, **Valve Last Heard**, **Valves In This Zone**, **Valve Addresses** and **Valve Summary**. The [Valve health](valve-health.md) page explains them.

A brand-new device shows 0.00 for its temperature and setpoint until its first real reading arrives, and **Temperature Last Reported** stays blank until then, so the 0.00 can be told apart from a real reading.

The plugin also creates one device for the boiler relay, which the [Your boiler](boiler-relay.md) page describes.

## Deleting a zone device

If you delete a zone device, the plugin creates it again the next time it hears a reading for that zone.
