---
title: Your boiler
nav_order: 6
---

# Your boiler

Evohome fires the boiler through a small wireless relay, usually a **Honeywell BDR91** fitted near the boiler. The controller tells the relay when the house needs heat, the relay closes, and the boiler runs. From version 1.10.0 the plugin listens to that relay too, so Indigo can see when the boiler is being called for heat.

## The Boiler Relay device

You never add this device yourself. The plugin creates it the first time it hears the relay on the radio, calls it **Boiler Relay**, and puts it in the **RAMSES** device folder beside your zones. Its address in Indigo is the relay's radio address, such as `13:123456`.

It is an ordinary Indigo on/off sensor. It shows **on** while the relay is closed and the controller is calling for heat, and **off** while it is open. That gives it Indigo's usual on and off icons, and a trigger can use **turns on** and **turns off** like any other sensor.

The relay announces a switch the moment it happens, so the device changes within a few seconds. In a test on 27 September 2026 the relay reported closing one second after the controller asked for heat, and opening one second after it stopped, and Indigo showed each within five seconds.

It is read-only. The Evohome controller decides when the boiler runs, so turning the device on or off from Indigo does nothing except say so in the Event Log.

If your system has more than one relay, for example one for hot water, each gets its own device. The first one heard is called **Boiler Relay** and the others are named after their address. Rename them however you like.

## What it shows

| Shown as | What it means |
|---|---|
| **On / off** | Whether the relay is closed and calling the boiler for heat. This is what the device list shows. |
| **Boiler Call For Heat** | The same answer in words: **Calling for heat**, **Not calling for heat**, or **Not known yet** until the relay first reports. |
| **Relay Summary** | One plain sentence, such as *Calling the boiler for heat since 7:05am*. |
| **Relay Last Switched** | When the relay was last seen to switch. It stays blank until a switch has actually been seen, so the first report after installing does not invent one. |
| **Relay Last Heard** | When the relay last sent anything at all. Updated at most every ten minutes, to keep the SQL Logger quiet. |
| **Relay Status** | **Answering** while the relay is being heard, **Silent** once it has not been heard for an hour, and **Not known yet** before it has been heard. |
| **Heat Demand (%)** | How much heat the controller wants overall, from 0 to 100. |
| **Relay Demand (%)** | How much of each heating cycle the controller is asking the relay to run the boiler for. |
| **Relay Address** | The relay's radio address. |

The controller sends the two demand figures about every twenty minutes, and they read **unknown** until the first ones arrive. They are only shown when there is one relay on the system: with more than one, the radio messages do not say which relay fires the boiler, so the plugin leaves them off rather than put them on the wrong device.

## When the relay goes quiet

As well as announcing each switch, the relay repeats its state every ten minutes, whether the boiler is running or not. If it has not been heard for an hour, the plugin marks it **Silent**, sets the device's error state to **relay silent**, and says so once in the Event Log. Device Health Monitor and anything else that watches error states will see it. The error clears as soon as the relay is heard again.

The hour only starts counting when the plugin starts, so a restart never makes a working relay look silent.

A silent relay usually means the gateway has stopped hearing it, rather than that the relay has failed. Check **Gateway Status** on any zone first.

## What it does not show

The relay only says when the boiler is being called for heat. The boiler's own thermostat still decides whether the burner is lit at that moment, and a combi boiler also fires for hot water without the relay closing at all. So **on** means *Evohome wants heat*, not *gas is burning*.

## Deleting the device

If you delete a relay device, it stays deleted: the plugin remembers its address and does not create it again, even after a restart. That is the way to be rid of a relay you do not want, such as a neighbour's or a hot-water relay you have no use for. **Plugins → RAMSES ESP → Bring Back Deleted Boiler Relays** undoes it, and each deleted relay is created again the next time it is heard.

## What goes in the Event Log

Once an hour in which the boiler was called for heat, one line says for how long and in how many calls, such as *Boiler Relay: the boiler was called for heat for 20 minutes between 7am and 8am, in 5 separate calls.* A quiet hour writes nothing. Each switch on and off is still on the device, and in the plugin's own log with debug logging on, but no longer in the Event Log, where in winter it added about twelve lines an hour.
