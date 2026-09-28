---
title: How it works
nav_order: 4
---

# How it works

You do not need to know any of this to use the plugin. It is here for anyone who likes to know what is going on.

## The path a reading takes

1. Your Evohome controller and radiator valves talk to each other by radio.
2. The RAMSES-ESP gateway hears that radio and turns each message into text.
3. The gateway sends the text over your Wi-Fi to the MQTT broker.
4. The plugin collects it from the broker and updates the zone's device in Indigo.

A change you make in Indigo goes the other way: the plugin hands a message to the broker, the gateway transmits it, and the controller acts on it as it would on a change made at the controller itself.

Nothing on this path uses the internet or Honeywell's servers, so it carries on working when they are down.

## Finding the gateway

When the plugin connects to the broker, it listens for the gateway announcing itself. The first gateway it hears is the one it uses, and it saves the gateway's ID in the plugin's settings. If it hears a second gateway, it ignores it and says so in the Event Log.

If the plugin loses its connection to the broker, it tries again every minute until the broker answers.

## What it reads

The Evohome controller broadcasts the temperature and the setpoint of every zone about every three minutes, and the plugin reads four kinds of message from it:

- **the temperature of each zone,**
- **the setpoint of each zone,**
- **each zone's mode** — following its schedule, or overridden,
- **each zone's name.**

The plugin takes a zone's temperature, setpoint, mode and name only from messages the controller itself sends. The valves also send their own setpoint to the controller, and just after a change that is still the old one, so it is not used. Each radiator valve also sends out its own reading, but where a zone has two valves — one in the sun and one on a cold wall, say — the two can differ by a good deal, and taking both would make the zone's temperature jump about. The controller's figure is the one Evohome itself heats to.

Every message a radiator valve sends, whatever it is about, tells the plugin that valve is still alive. That is what the [valve health](valve-health.md) states are built from.

The plugin also listens to the boiler relay, which reports whether it is closed, and to the controller's two figures for how much heat it wants. Those make up the [Boiler Relay](boiler-relay.md) device.

**Only your own controller counts.** The plugin remembers the first Evohome controller it hears and ignores any other, so a neighbour's Evohome in radio range cannot change your zones. It says once in the Event Log when it hears another controller.

## Setting a temperature

When you set a zone's temperature from Indigo, the plugin sends it as a **permanent override**. The zone keeps that temperature until something changes it, and the Evohome schedule does not change it back at the next schedule change. The plugin has no action to put a zone back on its schedule, so do that on the Evohome controller. For a temperature that should lapse by itself, use **Set Temperature for a While**: it sends a **temporary override** with an end time, and when that passes Evohome puts the zone back on its timetable. I tested that on my own controller, and its clock ran about a minute fast, so an override may end a minute early.

A temperature is always kept between 8 °C and 35 °C. The Evohome controller will not go below about 8 °C, so the plugin does not either, which keeps Indigo showing the same figure the controller uses.

The device shows the new setpoint once the controller reports it back, usually within a few minutes. Until then the plugin sends it again every minute, three times in all, and if the controller has still not reported it after five minutes the Event Log says so. Nothing is sent while the gateway is offline, because it could never arrive: the Event Log says so once for each zone.

## The time on readings

The gateway puts a time on every message. Until the gateway has set its own clock from the internet, those times read as 1970, so the plugin uses the Mac's time instead and says so once in the Event Log.

## What goes in the log

The Event Log shows the plugin connecting, the gateway being found, each new zone device being created or renamed, a valve going silent and answering again, and anything the watchdog does. Temperature changes you make are not logged, to keep the log quiet. Tick **Enable Debug Logging** in the settings to see every message the plugin receives, which is only worth doing when chasing a problem.
