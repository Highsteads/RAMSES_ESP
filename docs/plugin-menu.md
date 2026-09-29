---
title: The plugin menu
nav_order: 10
---

# The plugin menu

These are under **Plugins → RAMSES ESP**.

| Menu item | What it does |
|---|---|
| **Toggle Timestamps in Log (on/off)** | Every line the plugin writes to the log starts with the time to the thousandth of a second, which helps when lining events up. This turns that on or off. It stays as you leave it. |
| **Show Valve Battery and Liveness** | Writes a report on the radiator valves to the Event Log: how many valves have been heard across how many zones, how long a valve can go unheard before it is called silent, how long the plugin has been listening, one sentence for each zone, any valve heard but not yet matched to a zone, and any valve that is silent, with the hours since it was last heard. |
| **Forget Valves Not Heard For 7 Days** | Drops every valve that has not been heard for a week, so a valve you have replaced stops marking its zone silent. The log names the valves it dropped. A dropped valve is picked up again if it ever transmits. |
| **Read Evohome Timetables Now** | Reads every zone's weekly timetable from the Evohome controller now instead of waiting for the nightly read. Each zone's **Timetable** state updates within about a minute. |
| **Bring Back Deleted Boiler Relays** | A relay device you delete stays deleted. This undoes that, so each deleted relay is created again the next time it is heard. |
| **Show Plugin Info** | Writes the plugin's version and details of your Mac and Indigo to the log, which is useful to include if you ask for help on the Indigo forum. |

A valve can be heard before it is matched to a zone, because only some of the messages a valve sends say which zone it belongs to. It is matched as soon as it sends one of those.
