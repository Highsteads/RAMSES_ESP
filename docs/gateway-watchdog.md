---
title: Keeping the gateway running
nav_order: 7
---

# Keeping the gateway running

While the gateway is connected, it tells the broker it is online. If it drops off the network, the broker passes on that it has gone offline. Every zone device shows this in its **Gateway Status**, which you can use in your own triggers, and the plugin can act on it in two ways.

## Alerts on your phone

If you have the Pushover plugin installed and enabled, the plugin sends a **RAMSES Gateway Offline** alert once the gateway has been offline for five minutes, and a **RAMSES Gateway Restored** alert when it comes back. A gateway that drops out and returns within five minutes sends nothing. There is no setting for this — it is always on when the Pushover plugin is there, and the log says so when it is not.

## The power-cycle watchdog

The gateway's firmware sometimes stops trying to rejoin the Wi-Fi after a failed attempt, and then it stays offline until its power is switched off and on. I found this out when a Wi-Fi change knocked mine off the network and my heating readings stopped for ten days.

If the gateway is plugged into a smart plug that Indigo can switch, the watchdog does that for you. To use it, open **Plugins → RAMSES ESP → Configure**, tick **Enable Power-Cycle Watchdog**, and choose the plug in **Gateway Power Plug**. The [Settings](settings.md) page explains the timings.

### What it does

1. When the gateway has been offline for the time you set — 15 minutes to start with — the watchdog first checks the plug. If Indigo shows the plug as disabled, in error, or offline, it does not try, because the plug and the gateway are nearly always on the same network, so the trouble is the network rather than a stuck gateway. It says so in the Event Log.
2. Otherwise it switches the plug off, waits for the plug to report that it is off, waits the number of seconds you set, and switches it back on. It tries up to five times to get the plug back on, checking each time that the plug reports it.
3. If the gateway is still offline, it tries again once the same length of time has passed, up to the number of times a day you set — three to start with.

A cycle only counts, and the Pushover alert saying the gateway was power-cycled is only sent, once the plug has been seen to switch. If your plug does not report whether it is on or off, the watchdog cannot check, and it goes ahead without checking.

### The alerts it sends

These go through the Pushover plugin, if you have it.

| Alert | What it means |
|---|---|
| **RAMSES watchdog power-cycled gateway** | The plug was switched off and on again. It gives the number of cycles so far today. |
| **RAMSES watchdog giving up** | The gateway is still offline after the most cycles a day allows. It needs looking at by hand. |
| **RAMSES watchdog cannot cycle the plug** | The watchdog has tried as many times as a day's cycles allow without managing to switch the plug, usually because the plug is off the network too. No power has been cut. |
| **RAMSES watchdog NEEDS HELP** | The plug did not come back on after being switched off, so the gateway may be without power. Check the plug straight away. |

The daily count starts again each day, and is kept if the plugin restarts.
