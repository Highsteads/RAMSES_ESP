---
title: Version history
nav_order: 12
---

# Version history

The newest version is at the top.

## 1.16.0 — 2 October 2026

- **Each zone says when its temperature was last reported.** The new **Temperature Last Reported** state moves only when the controller sends the zone's temperature. **Last Seen** also moves when the controller sends its setpoints, which it does whether or not the temperature arrives, so a temperature that had stopped updating could still look current. EvoHome Heating Controller 1.18.0 uses the new state to leave a room alone when its temperature is out of date.
- A new zone's state stays blank until its first temperature arrives, so its starting 0.00 cannot be taken for a real reading.

## 1.15.0 — 29 September 2026

- **Each zone says who last changed its temperature.** The new **Changed By** state reads *indigo* when Indigo sent it, *timetable* when the zone went back to its Evohome timetable, and *manual* when somebody changed it at the controller, on a valve's wheel or in the app. **Changed At** says when. A change made by hand also gets one line in the Event Log, such as *Bedroom 3 Radiator was set to 21 degrees until 10pm from outside Indigo.* EvoHome Heating Controller 1.16.0 uses this to leave a room alone after somebody changes it by hand.
- **Set Temperature for a While can run until a date and time**, up to a year ahead, instead of for a number of minutes. Tested on a real controller, which took an end date eight months away without complaint. EvoHome Heating Controller 1.16.0 uses it so its summer hold ends by itself on the day heating is due back.

## 1.14.0 — 29 September 2026

- **The boiler relay writes one line an hour instead of one per switch.** In winter the relay switches about six times an hour, which put twelve lines an hour into the Event Log. Now each hour in which the boiler ran gets one line, such as *Boiler Relay: the boiler was called for heat for 20 minutes between 7am and 8am, in 5 separate calls.* A quiet hour writes nothing.
- **A relay device you delete stays deleted.** It used to come straight back from the relay's next message. A new menu item, **Bring Back Deleted Boiler Relays**, undoes it.
- **A rare freeze is fixed.** When the plugin found its gateway for the first time during a reconnect, which only happens on a new install, it could stop responding.

## 1.13.0 — 29 September 2026

- **The plugin reads each zone's timetable from the Evohome controller every night** at 3:15am, over the radio and without the cloud, and shows it on the zone as **Timetable**, for example *Every day: 5am 17, 9am 18, noon 20, 7pm 21, 9pm 20, 10pm 16.* That timetable is what the zone follows when nothing overrides it, including when Indigo is not running.
- The Event Log says when a zone's timetable has changed since the night before, and names any zone that did not answer.
- New action and menu item: **Read Evohome Timetables Now**.
- Two more states, **Timetable Data** and **Timetable Read**, so other plugins can check the timetable. EvoHome Heating Controller 1.15.0 uses them to check it against its own plans.

## 1.12.0 — 28 September 2026

- **New action: Set Temperature for a While.** It sets a zone for a number of minutes, and when the time runs out Evohome puts the zone back on its own timetable by itself. For an automation that means a stopped Indigo hands the house back to Evohome instead of holding the last temperature indefinitely. Tested on a real controller: it took the setting at once and went back to the timetable when the time was up.
- **New state: Override Ends,** the time a temporary override runs out.
- **Zone Mode names every Evohome mode:** schedule, permanent override, temporary override, advanced override and countdown override.

## 1.11.0 — 28 September 2026

Fixes made before the heating comes back on for the winter.

- **A gateway that stops passing on radio messages is noticed.** It can stay connected, and say it is online, while nothing comes through it. After 15 minutes with no message the plugin now treats it as offline: **Gateway Status** shows **Offline**, the alert is sent and the power-cycle watchdog can act. Before, only the valves going silent six hours later gave it away, and they were blamed.
- **A setpoint shows only once Evohome has it.** The plugin used to show a new temperature the moment it sent it, even when the gateway was offline and it could never arrive. It now shows it once the controller reports it back, sends it again every minute (three times in all) until then, and says so if the controller has not taken it after five minutes. Nothing is sent while the gateway is offline.
- **Only your own controller counts.** Zone temperatures, setpoints, modes and names come only from messages the controller itself sends. The valves' own setpoint reports, which just after a change still carry the old value, no longer flick the setpoint back. A neighbour's Evohome in radio range is ignored.
- The valve summary reads properly: *The valve is answering*, not *The valve answering*.
- A garbled radio message is no longer logged as an error.
- Starting up writes one line to the Event Log instead of about twenty.

## 1.10.0 — 27 September 2026

**Indigo can now see when the boiler is being called for heat.** Evohome fires the boiler through a wireless relay, usually a BDR91, and the plugin now listens to it. See [Your boiler](boiler-relay.md).

- A new **Boiler Relay** device appears in the **RAMSES** folder the first time the relay is heard. It is an on/off sensor: **on** while the relay is closed and the controller is calling for heat.
- It shows how much heat the controller wants, when the relay last switched, and a one-line summary such as *Calling the boiler for heat since 7:05am*.
- If the relay is not heard for an hour, the device says **Silent**, takes the error **relay silent**, and the Event Log says so once.
- The device is read-only. Evohome decides when the boiler runs.

## 1.9.0 — 27 September 2026

**Each zone now says whether the gateway itself is alive.** The old **Online** state only ever followed the plugin's own connection to the broker, so it went on saying **true** when the gateway died, as long as the broker was still running.

- New state on each zone, **Gateway Status**, which reads **Online**, **Offline** or **Not known**, and follows the gateway rather than the broker.
- **Online** works as it always has, and is now labelled **Online (broker link)** so nobody takes it for the gateway.
- The settings save with **Broker Host** left blank when your `IndigoSecrets.py` file gives the broker's address. Before, the dialog would not save at all.
- The broker's port can now come from `IndigoSecrets.py` too, as `MQTT_PORT`, whenever the file also gives the address.
- A silent valve's **valve silent** error now stays on the zone until the valve is heard again. Before, the next temperature reading from the controller wiped it, usually within a minute, so Device Health Monitor could easily miss it.

## 1.8.0 — 19 September 2026

**The watchdog checks that the plug really switched.** Indigo does not report an error when a command to a plug goes nowhere, so the watchdog used to count a command as a power cycle whether or not the plug moved. When my Wi-Fi dropped for about an hour and a half, taking the gateway and its plug down together, the watchdog sent six commands that never reached the plug, reported two cycles that never happened, used up the day's three, and asked for a human — and the gateway came back by itself when the Wi-Fi did.

- A cycle now only counts, and the alert saying the gateway was cycled is only sent, once the plug has been seen to switch.
- If Indigo shows the plug as disabled, in error or offline, the watchdog does not try, and says the trouble looks like the network rather than a stuck gateway.
- Attempts that cut no power no longer use up the day's cycles, and a separate alert says when the plug could not be switched.
- A plug that does not report whether it is on or off is still cycled as before.

## 1.7.0 — 13 September 2026

**A valve that was already dead when the plugin started is now reported.** Before, a zone was only judged if a valve had been heard in it at least once, so a valve that had stopped before the plugin started listening stayed at "Not known yet" for ever. My Utility Room valve did exactly that for 103 days, until someone noticed a cold radiator.

- Every zone with a device is now judged, and a zone from which no valve has ever been heard is reported as silent once the plugin has been listening long enough.
- New setting, **Warn when a zone's valve has never been heard at all**, to untick for a zone with no radiator valve.

## 1.6.0 — 12 September 2026

**Each zone reports the battery and health of its own radiator valves.** Before, a dead valve went unseen until the room went cold, and there was no valve battery reading anywhere in Indigo.

- New states on each zone: **Valve Status**, **Valve Battery**, **Valve Battery (%)**, **Valve Last Heard**, **Valves In This Zone**, **Valve Addresses** and **Valve Summary**.
- The battery reading also goes into Indigo's own battery level for the device.
- Where a zone has more than one valve, each state reports the worse of them.
- A valve not heard yet shows as "Not known yet", never as silent or flat, and a restart cannot make a valve look silent.
- New settings for how long counts as silent, and whether a silent valve marks the zone in error.
- New menu items, **Show Valve Battery and Liveness** and **Forget Valves Not Heard For 7 Days**.

## 1.5.2 — 11 September 2026

The plugin carries a note of where its code lives on GitHub, the same way other Indigo plugins do. Nothing else changed.

## 1.5.1 — 8 August 2026

The **About** item in the Plugins menu opens this project's page. It went nowhere before.

## 1.5.0 — 27 July 2026

The plugin uses version 2.1 of the library it talks to the MQTT broker with, and a refused connection now gives the broker's own reason, such as "Not authorized", instead of a number.

## 1.4.1 — 21 July 2026

A refresh of the helper file the plugin shares with my other plugins. Log lines can no longer come out with the time printed twice. Nothing else changed.

## 1.4.0 — 26 June 2026

Fixes from a thorough review of the whole plugin.

- **The watchdog cannot leave the gateway without power.** It switches the plug off and back on in one go, and always switches it back on, even if the plugin is restarting at the time.
- A gateway that was already offline when the plugin started is now seen as offline, so the watchdog can act on it.
- Stray codes in the radio messages no longer create zone devices that do not exist.
- An unknown setpoint no longer resets a zone's setpoint to zero.
- A zone that has lost its connection no longer shows as heating in HomeKit.
- The lowest temperature the plugin sends is 8 °C instead of 5 °C, matching what the Evohome controller actually uses.

## 1.3.0 — 12 June 2026

**New power-cycle watchdog.** If the gateway stays offline for longer than you choose, the plugin switches off the smart plug that powers it, waits a few seconds and switches it on again, up to a set number of times a day, with an alert each time. I added it after a Wi-Fi change knocked my gateway off the network and it never rejoined, leaving my heating readings missing for ten days.

## 1.2.11 — 10 June 2026

Tidying of the code, with no change in how the plugin works.

## 1.2.10 — 25 May 2026

The plugin no longer restarts a zone device each time it saves that device's own settings. No change in how it works.

## 1.2.9 — 23 May 2026

Every log line starts with the time to the thousandth of a second, with a menu item to turn that off.

## 1.2.8 — 13 May 2026

**Zone Mode**, **Controller ID**, **Zone Name** and **Last Seen** were given new names inside Indigo, so any trigger, control page or script that used them needed setting up again, and their stored history was lost.

## 1.2.7 — 10 May 2026

- New **Show Plugin Info** menu item.
- The plugin no longer has a built-in broker address, and says so in the log if none is set.
- The broker details can come from the shared `IndigoSecrets.py` file, with the Configure dialog as the fallback.

## 1.2.6 — 5 May 2026

The gateway offline alert waits five minutes, so a short drop-out no longer sends one, and the restored alert is only sent if the offline alert was.

## 1.2.5 — 8 April 2026

New alerts through the Pushover plugin when the gateway goes offline and when it comes back.

## 1.2.4 — 4 April 2026

The broker address can come from the shared credentials file, as my own broker moved to the Mac that runs Indigo.

## 1.2.0

Setting a temperature from Indigo sends a permanent override, so the Evohome schedule no longer changes it back at the next schedule change.

Versions 1.2.1 to 1.2.3 are not recorded.

## 1.1.8 — 24 February 2026

Temperature changes made from Indigo are no longer written to the Event Log.

## 1.1.7 — 24 February 2026

HomeKit shows the zones as heating rather than off, and a request to switch a zone off keeps it in Heat.

## 1.1.6 — 24 February 2026

The zones show whether they are heating, and their mode, for HomeKit.

## 1.1.5 — 24 February 2026

**Zone Name** is filled in from the device's name until the controller sends the real one.

## 1.1.4 — 24 February 2026

The plugin asks the controller for the zone names when it starts.

## 1.1.3 — 23 February 2026

A message from a radiator valve no longer wipes a zone's controller ID, and a temperature change that failed to send is no longer logged as sent.

## 1.1.2 — 23 February 2026

The note that the gateway's clock has not been set is an ordinary log line rather than a warning.

## 1.1.1 — 23 February 2026

Creating a new zone device no longer causes an error.

## 1.1.0 — 23 February 2026

Zones became standard Indigo thermostats, so Indigo's own **Set Heat Setpoint** action works on them, and the plugin's own setpoint action was removed.

## 1.0.5 — 22 February 2026

**Last Seen** shows the right time when the gateway's clock has not been set, and **Zone Mode** no longer starts as "unknown".

## 1.0.4 — 22 February 2026

Zones take their names from the Evohome controller.

## 1.0.3 — 22 February 2026

Zone devices are created in a **RAMSES** folder, and **Last Seen** shows local time.

## 1.0.2 — 22 February 2026

A gateway ID stored several times over is read correctly.

## 1.0.1 — 21 February 2026

The plugin reconnects properly to the broker, and the settings are checked when you save them.

## 1.0.0 — 21 February 2026

The first release.
