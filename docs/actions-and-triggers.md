---
title: Actions and triggers
nav_order: 8
---

# Actions and triggers

## Changing a zone's temperature

A zone answers Indigo's standard thermostat actions, wherever you use them — the device list, a control page, a schedule, a trigger, an action group or HomeKit:

- **Set Heat Setpoint** sets the zone to the temperature you give.
- **Increase Heat Setpoint** and **Decrease Heat Setpoint** move it up or down by the amount you give.

Each one sends the zone a permanent override, which it keeps until something changes it. The temperature is kept between 8 °C and 35 °C. The [How it works](how-it-works.md) page says more.

A new temperature can only be sent once the plugin has found the gateway, is connected to the broker, and has heard at least one reading from the Evohome controller. If any of those is missing, the Event Log says which, and nothing is sent.

Actions for cooling, fans and changing the mode do nothing, because Evohome zones only heat. A request to switch a zone off, from HomeKit say, is ignored and the zone stays in Heat.

## Asking for fresh temperatures

Indigo's **Send Status Request** on a zone, and the plugin's own **Request Zone Update** action, both ask the Evohome controller to send its zone temperatures now, rather than waiting for its next regular broadcast. **Request Zone Update** is not tied to a zone, so you do not choose a device for it.

## Triggers

The plugin has no triggers of its own. Instead, use Indigo's **Device State Changed** trigger on any zone device, with any of its states. Some useful ones:

- **Valve Status** becomes **Silent** — a radiator valve has stopped answering.
- **Valve Battery** becomes **Battery low** — a valve is warning about its battery.
- **Zone Mode** changes — a zone has gone on to, or come off, a permanent override.

On the **Boiler Relay** device, Indigo's own **Sensor turns on** and **Sensor turns off** triggers follow the boiler being called for heat, and **Relay Status** becoming **Silent** means the relay has not been heard for an hour.

## From a script

A zone is an ordinary Indigo thermostat, so a Python script sets its temperature in the usual way. Put your own zone device's ID in place of `123456789`:

```python
dev = indigo.devices[123456789]
indigo.thermostat.setHeatSetpoint(dev, value=21.0)
```

And to ask the controller for fresh temperatures:

```python
plugin = indigo.server.getPlugin("uk.co.clives.ramses.esp")
plugin.executeAction("requestZoneUpdate")
```
