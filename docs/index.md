---
title: Home
nav_order: 1
---

# RAMSES ESP for Indigo

This plugin lets [Indigo](https://www.indigodomo.com) see and control a **Honeywell Evohome** heating system without going through Honeywell's servers. Nothing goes out to the internet — the plugin listens to the radio messages your Evohome controller and radiator valves already send to each other, and sends its own when you change a temperature.

To hear that radio, you need a **RAMSES-ESP gateway**. It is a small USB stick with a radio receiver tuned to the frequency Evohome uses, and a Wi-Fi chip that passes on everything it hears. You plug it into any USB power supply within radio range of your heating, and join it to your Wi-Fi. RAMSES is the name of the radio language Evohome speaks, which is where the plugin gets its name.

The gateway does not talk to Indigo directly. It posts each message to an **MQTT broker** — a small program, such as Mosquitto, that passes messages between devices on your network — and the plugin collects them from there. Many people already run one for other smart home devices, and it can run on the same Mac as Indigo.

## What it does for you

- **Creates a thermostat in Indigo for each Evohome zone** by itself, as soon as it hears the zone on the radio, with no device set-up on your part.
- **Shows each room's temperature and target temperature,** kept up to date from the controller's own regular broadcasts.
- **Sets a room's target temperature** from Indigo, a control page, a schedule, a trigger or HomeKit, the same as any other Indigo thermostat.
- **Reports on the radiator valves themselves** — their battery, when each was last heard, and whether any has stopped answering — so a dead valve shows up in Indigo rather than as a cold room.
- **Shows when the boiler is being called for heat,** by listening to the Evohome boiler relay, so a trigger or a graph can follow it.
- **Tells you when the gateway goes offline,** through the Pushover plugin if you have it.
- **Can switch the gateway off and on again** through a smart plug when it stays offline, because a gateway that has lost its Wi-Fi does not always find its own way back.

I run it on my own twelve-zone Evohome system.

## Where to go next

| If you want to... | Read |
|---|---|
| Install the plugin and see your zones appear | [Getting started](getting-started.md) |
| Know what each zone device shows in Indigo | [Your zones](devices.md) |
| Understand what the plugin is doing behind the scenes | [How it works](how-it-works.md) |
| Keep an eye on the radiator valves' batteries | [Valve health](valve-health.md) |
| See when the boiler is called for heat | [Your boiler](boiler-relay.md) |
| Have the plugin restart a stuck gateway | [Keeping the gateway running](gateway-watchdog.md) |
| Change temperatures from triggers, schedules and scripts | [Actions and triggers](actions-and-triggers.md) |
| Know what every setting does | [Settings](settings.md) |
| Know what each item in the Plugins menu does | [The plugin menu](plugin-menu.md) |
| Sort out a problem | [When something goes wrong](troubleshooting.md) |
| See what changed in each version | [Version history](changelog.md) |

## Download

The latest version is always on the [Releases page](https://github.com/Highsteads/RAMSES_ESP/releases/latest).
