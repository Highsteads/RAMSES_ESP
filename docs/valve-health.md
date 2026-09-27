---
title: Valve health
nav_order: 5
---

# Valve health

The Evohome controller keeps announcing a zone's temperature and setpoint whether or not the radiator valve in that zone still works. So without help, a valve with a flat battery, or one that has dropped off the radio, goes unnoticed until someone finds a cold radiator. These states let you see it in Indigo first.

Every radiator valve sends messages of its own now and then — about the room temperature, how much heat it wants, and its battery. The plugin notes each valve every time it hears one of them, and files it under the right zone.

## What each zone shows about its valves

| Shown as | What it means |
|---|---|
| **Valve Status** | **Answering**, **Silent**, or **Not known yet**. Silent means a valve in this zone has not been heard for longer than the time set in the plugin's settings — six hours to start with. |
| **Valve Battery** | **Battery fine**, **Battery low**, or **Not known yet**. Battery low means a valve has sent a warning about its own battery. |
| **Valve Battery (%)** | The lowest battery percentage among the zone's valves. It shows **unknown** until a valve has reported one. |
| **Valve Last Heard** | The date and time a valve in this zone was last heard. |
| **Valves In This Zone** | How many valves the plugin has heard in this zone. |
| **Valve Addresses** | Each valve's radio address, such as `04:123456`. |
| **Valve Summary** | One plain sentence, such as "Both valves answering. Lowest battery 100%." |

Where a zone has more than one valve, every state reports the worse of them — the lowest battery, and silent if any one valve is silent — because a zone is only as healthy as its weakest valve.

The battery reading also goes into Indigo's own battery level for the device, so the device list and anything else that watches batteries see it.

## Battery readings

Valves send a battery report only now and then, so the reading can take a while to appear after you first install the plugin. The plugin keeps what it has learned in a file, so a restart does not lose it.

On my own HR92 valves, the reading has only ever been 50% or 100%, which suggests these valves report their battery in two steps rather than as a smooth gauge. Treat **Battery low** as the warning to act on.

## When a valve goes silent

When a valve has not been heard for longer than **Report a valve silent after (hours)**, the zone's **Valve Status** changes to **Silent**, the Event Log gets one warning naming the zone, and the device shows **valve silent** as an error in the device list. Anything that watches for devices in error, such as my Device Health Monitor plugin, sees it. The error stays in place while the zone's temperature and setpoint go on updating, and only clears when the valve is heard again, when the log says it is answering again.

If you would rather not have the device marked in error, untick **Mark the zone device in error when a valve goes silent**. The states still change, but there is no error and no warning in the log, and an error already showing clears the next time the zone's valve news changes.

A zone the plugin has a device for, but from which it has never heard a valve at all, is treated the same way once the plugin has been listening for longer than the silence time. That catches a valve that was already dead before the plugin started. If one of your zones has no radiator valve — underfloor heating, say, or a zone driven by a relay — untick **Warn when a zone's valve has never been heard at all**, or that zone will report a silent valve for ever.

## After a restart

A valve cannot be called silent for a stretch when the plugin was not listening. So after a restart, a valve counts as silent only once it has been heard since the restart and then gone quiet, or once the plugin has been listening for longer than the silence time. Until then its status stays **Not known yet**.

## When you replace a valve

The old valve's address stays on the zone and, once it has gone quiet for long enough, marks the zone silent. When the old valve has not been heard for a week, choose **Plugins → RAMSES ESP → Forget Valves Not Heard For 7 Days** to drop it. The plugin never forgets a valve by itself, because a valve that has died is exactly the one that goes quiet.

To see everything the plugin knows about the valves, choose **Plugins → RAMSES ESP → Show Valve Battery and Liveness**. The [plugin menu](plugin-menu.md) page explains what it writes.
