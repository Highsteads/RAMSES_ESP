#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    plugin.py
# Description: RAMSES ESP gateway bridge plugin for Indigo home automation.
#              Connects to RAMSES-ESP wireless HVAC gateway via MQTT, auto-discovers
#              the gateway ID and Evohome zone thermostats from the RAMSES-II radio
#              message stream, and creates/updates Indigo custom devices for each zone.
# Author:      CliveS & Claude Opus 5, Claude Opus 5.5
# Date:        05-10-2026 22:50
# Version:     1.17.0
#
# v1.17.0 (05-10-2026): A COMMAND IS CONFIRMED BY THE SAME COMMAND COMING BACK (external audit).
#   HI-04: a 2309 broadcast confirms the temperature only; a pending command clears when a 2349
#   heard after it reports the same mode and end time (and the temperature, or a 2309 already
#   did), so a same-temperature renewal of a timed setting that never landed is resent instead of
#   being cleared by the next 2309. HI-05: _sent_log keeps (setpoint, time, until) and a change is
#   "indigo" only when mode and end time match the command too, so a person holding a room for
#   good at our temperature is "manual". HI-09: new Integer state temperatureSeenEpoch (seconds
#   since the epoch) beside temperatureSeen, whose local text repeats an hour on 25-10-2026; read
#   by EvoHome Heating Controller 1.18.1. (Claude Opus 5.5)
#
# v1.16.0 (02-10-2026): TEMPERATURE FRESHNESS. New zone state temperatureSeen, written only by
#   _apply_temp_update (controller 30C9). lastSeen also moves on 2309 setpoint and 2349 mode
#   reports, which the controller sends whether or not the temperature arrives, so a consumer
#   could not tell a frozen reading from a current one (independent review 02-10-2026). Blank on
#   a new zone until its first temperature. Measured the same day: the controller's 30C9 for all
#   12 zones comes in the same burst as its 2309. EvoHome Heating Controller 1.18.0 reads it.
#   (Claude Opus 5.5)
#
# v1.15.0 (29-09-2026): WHO CHANGED IT. Each zone carries setpointSource (indigo / timetable /
#   manual) and setpointChangedAt: a change reported within 15 minutes of a matching command of
#   ours is "indigo", a return to mode schedule is "timetable", anything else "manual" (the
#   controller's screen, a valve wheel or the app), logged at INFO once. Set Temperature for a
#   While also takes an end date ("until", YYYY-MM-DD HH:MM, up to 366 days ahead), which wins over
#   minutes - proven live: the controller accepts and echoes an end of 2027-06-01. Lets EvoHome
#   Heating Controller 1.16.0 leave hand-set rooms alone and end its summer hold on a date.
#   (Claude Opus 5.5)
#
# v1.14.0 (29-09-2026): the relay's per-switch INFO line is DEBUG, replaced by one INFO line per
#   clock hour in which the boiler ran (_account_relay_hour: 5-s passes, gaps capped at 60 s);
#   a deleted relay's address goes to prefs ignoredRelays and is never created again (menu
#   Bring Back Deleted Boiler Relays clears it); _mqtt_connect/_mqtt_disconnect no longer hold
#   mqtt_lock across loop_stop(), which could deadlock with _resubscribe_to_gateway on first
#   discovery. (Claude Opus 5.5)
#
# v1.13.0 (29-09-2026): NIGHTLY TIMETABLE READ. At 03:15 (and via action/menu readTimetables)
#   a background thread reads every zone's 0404 timetable (ramses_timetable.py; replies handed
#   over through a queue from the MQTT thread, results written by the main loop) into states
#   timetable / timetableData / timetableRead; a changed timetable is logged at INFO, a zone that
#   does not answer at WARNING and retried the next night. Only our controller's replies count.
#   (Claude Opus 5.5)
#
# v1.12.0 (28-09-2026): TEMPORARY OVERRIDES. Device action setTemporarySetpoint (props
#   setpoint, minutes 10-1440) sends W 2349 013 mode 04 with an until time (minute, hour,
#   day, month, year16 - ramses_rf ZoneMode13BPayload); Evohome lapses the zone to its
#   timetable at that time. PROVEN LIVE on 01:091567 (lapsed 19:21:01 for 19:22 - the
#   controller clock runs ~1 min fast). zoneMode names modes 00-04; new state
#   zoneOverrideUntil from the 13-byte 2349. Resends carry the same until. (Claude Opus 5.5)
#
# v1.11.0 (28-09-2026): before the heating returns. A gateway connected to MQTT but passing
#   on no radio frames for 15 min is DEAF: gatewayStatus offline, alert + watchdog armed
#   through gateway_offline_since, cleared by the next frame or a fresh presence 'online'.
#   setpointHeat is no longer written when a W 2349 leaves: it changes on the controller's
#   report, with resends every 60 s (3 in all), a WARNING after 5 min, and no sends at all
#   while the gateway is offline or deaf (ERROR once per zone per outage); a refused paho
#   publish (rc != 0) is caught. 30C9/2309/2349/0004 are taken only when SENT by our
#   controller (valves send 2309 to it with their own, possibly stale, value); the
#   controller is learned once (prefs, zone devices, first heard) and any other ignored,
#   also for valve filing and boiler demand. Garbled frames log at DEBUG; startup logs one
#   INFO line; valve summary grammar. (Claude Opus 5.5)
#
# v1.10.0 (27-09-2026): THE BOILER RELAY, AND WHEN THE BOILER IS CALLED FOR HEAT.
#   * New device type `ramsesBoilerRelay`, created the first time a relay (13:) is heard.
#     A native on/off sensor: onOffState is ON while the relay is closed. States:
#     relayStatus (unknown/on/off), relayAnswering (unknown/answering/silent), relaySummary,
#     relayLastChanged, relayLastHeard, relayAddress, heatDemand and relayDemand (the
#     controller's 3150 and 0008 for the FC domain, -1 until reported).
#   * Decoding lives in the new ramses_relay.py (no indigo import). Packets measured live on
#     27-09-2026: the BDR91 sends 3B00 00C8 then 3EF0 0000FF; the controller sends 3B00 FCC8,
#     3150 FC00 and 0008 FC00. 3EF0 byte 1 is the level, 0 open, 200 closed.
#   * A switch time is only claimed from a switch SEEN; the first report after installing
#     sets the state and leaves relayLastChanged blank.
#   * Silence (RELAY_SILENT_MINUTES) sets the error "relay silent" and warns once; the clock
#     starts at plugin start so a restart cannot invent a fault.
#   * Demand is written only when exactly one relay exists: the traffic does not say which
#     of several relays fires the boiler.
#   * lastHeard on its own is written at most every RELAY_HEARD_WRITE_EVERY seconds, so a
#     relay that reports every few minutes does not add an SQL Logger row each time.
#   * deviceStartComm and deviceDeleted branch on deviceTypeId, so the relay never gets
#     thermostat capability props or valve seeds.
#
# v1.9.0 (27-09-2026): THE GATEWAY'S OWN LIVENESS, AND IndigoSecrets FOR THE WHOLE BROKER.
#   * New zone state `gatewayStatus` (unknown/online/offline) from the gateway's retained
#     presence message and its LWT. The old `online` state follows THIS plugin's broker link
#     and stayed "true" when the gateway died with the broker up. It is unchanged in value
#     (nothing in DeviceHealthMonitor, Dashboards or the Python Scripts reads it) and only
#     relabelled "Online (broker link)". Written with clearErrorState=False so it can never
#     wipe the "valve silent" error.
#   * validatePrefsConfigUi no longer refuses a blank Broker Host when IndigoSecrets.py
#     supplies MQTT_BROKER, nor a blank port when it supplies MQTT_PORT as well.
#   * MQTT_PORT is read from IndigoSecrets.py first, but ONLY when MQTT_BROKER is set there:
#     the shared template ships MQTT_PORT = 1883 beside a blank broker, and letting that win
#     would override the port of a user who configures the broker in the dialog.
#   * EVERY ROUTINE STATE WRITE NOW KEEPS THE "valve silent" ERROR. Indigo's state writes
#     clear a device's error by default, so each controller temperature broadcast (about
#     once a minute) wiped the error _write_trv_states had just set, and Device Health
#     Monitor rarely saw it. All batch writes go through `_write_states` (batch with
#     clearErrorState=False, falling back to single documented writes if Indigo refuses
#     the argument), single writes pass clearErrorState=False, and only the valve code
#     sets or clears the error. With reporting switched off it takes back its own error.
#
# v1.8.0 (19-09-2026): THE WATCHDOG NOW PROVES THE PLUG MOVED, INSTEAD OF ASSUMING IT.
# `indigo.device.turnOff()` and `turnOn()` are fire and forget: Indigo hands the command to
# the plug's owning plugin and returns, so a command to an unreachable plug raises nothing
# at all. The old `_power_cycle_plug` read that silence as success.
#
# LIVE, AND IT IS THE WHOLE ARGUMENT FOR THE FIX: on 19-09-2026 the IoT WiFi dropped for
# about ninety minutes. The gateway went offline with everything else on it, and so did the
# plug that feeds it. The watchdog fired three power cycles, at 17:51, 18:06 and 18:21.
# ShellyDirect logged `No route to <plug>` for all six commands. The watchdog logged every
# one of them as a success, sent two Pushovers saying it had cycled the gateway, spent the
# entire daily cap on cycles that never happened, and at 18:37 sent "giving up, it needs a
# human". The gateway came back on its own at 18:46 when the WiFi returned. Not one of
# those statements was true, and the log read as though the hardware were at fault.
#
#   * The plug's OWN REPORTED STATE is now the evidence. `_power_cycle_plug` waits for the
#     device to report the switch (`WD_VERIFY_SECONDS`) and returns True seen, False did
#     not move, None publishes nothing to check. The device is re-fetched on every read —
#     a cached one reports what it held when the cycle started and confirms anything.
#   * A CYCLE COUNTS AGAINST THE DAILY CAP ONLY ONCE THE PLUG HAS MOVED, and the "cycled"
#     Pushover is sent only then. No-ops can no longer eat the budget or claim credit.
#   * A PRE-FLIGHT CHECK SKIPS AN UNREACHABLE PLUG ENTIRELY. The plug and the gateway are
#     nearly always on the same network, so when the plug is unreachable too, cutting its
#     power is impossible AND beside the point — and firing the command anyway risks the
#     owning plugin delivering it late, switching the gateway off at a moment nobody chose.
#     `_plug_unreachable_reason` asks only questions every Indigo device can answer
#     (`enabled`, `errorState`, a `deviceOnline`-style state), so it keys on no plugin ID
#     and no device name. An ABSENT state is not evidence of an offline plug, so the
#     unknown case proceeds.
#   * A DEFINITE NO IS THE ONLY NO. `_scalar_bool` accepts bool, int and str and answers
#     None for anything else, because the v2 API hands custom states back as the strings
#     "True"/"False" and `bool("False")` is True.
#   * Attempts that did not cut power escalate SEPARATELY, once per outage, saying the plug
#     could not be reached rather than blaming the gateway. The give-up alert now counts
#     the cycles that really happened.
#   * A lost OFF no longer waits out an off-window that never started, and no longer raises
#     NEEDS HELP — that alert means the gateway is stranded without power, which is the one
#     thing a command that never landed cannot have caused.
#
# v1.7.0 (13-09-2026): A VALVE THAT WAS ALREADY DEAD WHEN WE STARTED LISTENING IS NOW
# REPORTED. v1.6.0's detector had a hole the exact shape of the fault it was written for.
# `_publish_trv_states` iterated `self.trv.known_zones()` — zones the registry had heard a
# valve in at least once — so a valve that had stopped transmitting BEFORE the plugin came
# up never entered the registry, was never summarised, never written and could never set
# the error state Device Health Monitor reads. It kept the "unknown" `_seed_trv_states`
# gives a new device, which reads as patience rather than as a fault.
#
# LIVE, AND THIS IS THE WHOLE ARGUMENT FOR THE FIX: the Utility Room valve here stopped
# transmitting on 02-06-2026 and still read "unknown" on 13-09-2026 — 103 days — with a
# working detector on both sides of it. Every other zone reported 35 to 43 times a day
# throughout. It was found by hand, by a person noticing a cold radiator, which is the
# thing v1.6.0 existed to make unnecessary.
#
#   * The zones covered are now the UNION of what the registry has heard and what we hold
#     a zone device for. `unheard_summary()` in ramses_trv.py gives the verdict, so it
#     sits in the seam with the rest of the liveness logic and is driven by tests.
#   * The restart grace is UNCHANGED and still applies: never-heard is `None` until we
#     have been listening longer than the threshold, only then `False`. A reload cannot
#     raise a fault about its own downtime.
#   * `trv_expect_every_zone` (default True) turns it off for a zone that legitimately
#     has no radiator valve — underfloor, or a relay-driven zone. Default True because
#     silence about a zone we hold a device for is the fault this feature exists to
#     raise, and a permanent false warning on a valveless zone teaches its owner to
#     ignore the real one, which costs more than the warning is worth.
#   * `describe()` gained a count==0 branch, ahead of the count arithmetic that would
#     otherwise have read "All 0 valves answering".
#   * `zone_devices` is COPIED before iterating — it is mutated from deviceStartComm on
#     Indigo's dispatch thread while this runs on the worker.
#   * Tests 142 -> 157. Five deliberate breakages, all caught: the union reverted, the
#     verdict forced to unknown, the describe branch removed, the off switch ignored,
#     and the restart grace dropped.
#
# v1.6.0 (12-09-2026): PER-VALVE BATTERY AND LIVENESS. A zone device's `online` and
# `lastSeen` are about the GATEWAY's MQTT link and the CONTROLLER's periodic broadcast,
# and the controller keeps announcing a zone whether or not the TRV in it still answers
# — so a dead valve was invisible until the room went cold, and no battery reading for a
# TRV existed anywhere in Indigo. Both facts were already on the air and this plugin was
# dropping them: `_parse_ramses_message` decoded four controller opcodes and ignored
# every packet a valve sent for itself.
#
# Each zone now reports its valves: trvBattery, trvBatteryWarn, trvStatus, trvLastSeen,
# trvCount, trvIds and a plain-English trvSummary, aggregated to the WORST case because
# a zone is only as healthy as its unhappiest valve. The reading is mirrored into
# Indigo's own batteryLevel so the device list and every battery sweep see it.
#
# ZONE ATTRIBUTION IS MEASURED, NOT ASSUMED: a packet a valve addresses to the controller
# carries its zone index as payload byte 0, and its SELF-addressed packets do not — byte
# 0 is 00 there whatever the zone, so reading it would file every such valve under zone 0.
#
# FOUR THINGS THAT COULD ONLY HAVE BEEN WRONG:
#   * `trvStatus` and `trvBatteryWarn` are three-valued, not boolean. A new Boolean state
#     is born FALSE, so a zone whose valve had simply not spoken yet would have asserted
#     "silent" and "battery fine" on eleven of twelve zones — seen live, then fixed.
#   * They carry those NAMES because INDIGO WILL NOT RE-TYPE A STATE THAT ALREADY EXISTS.
#     They first shipped as Booleans; redeclaring them as Lists and calling
#     stateListOrDisplayStateIdChanged() left all twelve zones still holding a bool, and
#     the server then dropped the entire batch that wrote the word "unknown" into one —
#     silently, with nothing in the plugin log or the event log, taking the states written
#     beside it down too. A new id is created with the declared type; that is the only
#     route. Never change a shipped state's ValueType — add a new id.
#   * `SupportsBatteryLevel` is claimed only when a real reading arrives. Declaring it up
#     front creates a native batteryLevel of 0, and 0% reads to every battery sweep in
#     the house as a flat cell.
#   * Silence is only evidence if somebody was listening through it. A valve last heard
#     before this plugin came up may have been transmitting all night into a receiver
#     that was switched off, so it is judged only once heard since startup, or once we
#     have been listening longer than the threshold itself.
#
# The 1060 battery decode is UNPROVEN against this hardware — no such packet was captured
# from these HR92s in 56 minutes of listening across two captures — so every shape it misses
# returns nothing rather than a plausible number. Tests 55 -> 133, mutation sweep 30/30.
#
# v1.5.2 (11-09-2026): GITHUBINFO. The bundle now carries the standard GitHub record
# (GithubInfo: GithubUser/GithubRepo), as the Indigo Domotics and community plugins do.
# No behaviour change.
#
# v1.5.1 (08-08-2026): REQUIRED Info.plist KEY. `CFBundleURLTypes` was PRESENT but
# EMPTY, so the plugin shipped without the support URL that becomes its
# "About" menu item — one of the SIX keys the official Developer's Guide lists as
# required. An empty array satisfies "key exists" while giving users nowhere to go,
# which is why an earlier sweep that only looked for a MISSING key passed it. Found
# by an estate check auditing the VALUE rather than the key's presence.
# No plugin logic changed.
#
# v1.5.0 (27-07-2026): paho-mqtt 1.6.1 -> 2.1.0. Pinned and deferred since
# 26-06-2026; Zigbee2MQTTBridge made the same move on 16-07-2026 (v2.0.0), so
# this follows that recipe rather than rediscovering it.
# * mqtt.Client() now takes CallbackAPIVersion.VERSION2 as a REQUIRED first
#   positional. Omit it and 2.x raises, so the gateway silently never connects
#   — which on this plugin means 12 heating zones quietly stop updating.
# * VERSION2 changes the callback signatures, so all three had to move, not
#   just the constructor: _on_connect gains reason_code + properties,
#   _on_disconnect gains disconnect_flags before them. reason_code is a
#   ReasonCode object (.is_failure, readable str()), normalised to an int at
#   the _on_disconnect boundary so the clean-vs-unexpected test keeps its
#   meaning. An unconvertible code counts as unexpected — that reconnects,
#   rather than assuming a tidy shutdown.
# * The 1-5 connect-refusal label table is deleted. Under VERSION2 even a
#   3.1.1 broker's CONNACK errors arrive as MQTT-v5 reason codes, so it could
#   never have matched again; str(ReasonCode) is already readable.
# * DEPLOY TRAP, documented in requirements.txt: changing a pinned VERSION
#   needs Contents/Packages/paho* PURGED, not just the pip sentinel deleted.
#   `pip install -t` does not uninstall, so both dist-infos end up present and
#   the mixed directory can load the OLD code — which has no CallbackAPIVersion.
#   Z2M hit exactly this and the bridge came up dead.
# * Tests 34 -> 48: the conftest paho stub gained a real CallbackAPIVersion
#   enum and a paho-free FakeReasonCode (a bare module stub would have raised
#   AttributeError and hidden the very mistake these tests exist to catch).
#   10 of the 14 new cases fail against the pre-migration code.
#
# v1.4.1 (21-07-2026): shared plugin_utils.py refreshed to v1.3 — the
# estate-wide propagation of the four Appliance Monitor deep-review fixes.
# * install_timestamp_filter() is idempotent — a second call used to stack a
#   second filter, so every log line came out with two timestamps.
# * `import indigo` is soft, so the module imports outside the Indigo host and
#   can be exercised by offline tests.
# * A malformed log call keeps its arguments in the log instead of dropping
#   them, so a %-placeholder mismatch is visible.
# * New shared as_bool() — a pref re-serialised as the string "false" is
#   truthy, which is exactly the wrong answer.
#
# v1.4.0 (26-06-2026): Deep-review hardening (multi-agent review, 24 verified findings).
# - Watchdog crash-safety: the plug OFF/ON now runs inside a SINGLE main-loop tick with a
#   try/finally restore, so a reload, disable or crash mid-cycle can no longer strand the
#   gateway powered off. Daily cycle counters are persisted across reloads. The decision
#   logic is extracted to the pure, unit-tested _watchdog_decision().
# - A retained 'offline' LWT seen on FIRST gateway discovery is no longer mis-read as online
#   (otherwise the watchdog could never arm after a plugin restart during an outage).
# - Main loop wrapped for per-pass failure isolation (one bad pass logs and continues).
# - RAMSES domain codes (0xF9/FA/FC) no longer spawn spurious "RAMSES Zone 252" devices.
# - A 2349 with an unknown setpoint (raw 0x7FFF) no longer clobbers setpointHeat with 0.0.
# - hvacHeaterIsOn is cleared when a zone goes offline (HomeKit no longer shows a dead zone
#   as actively heating).
# - Setpoint floor raised 5 -> 8 degC to match the Evohome frost clamp (optimistic UI honest).
# - First test suite added (pure decoders, setpoint encoder, gateway-id sanitiser, watchdog FSM).
# - Smaller: closedPrefsConfigUi resubscribes on a CHANGED gateway ID; 0004 odd-length name
#   trim; gateway-id sanitiser shared by validate + read; emergency Pushover downgraded to
#   the reliable high tier; assorted comment/author-label corrections.
#
# v1.2.9 (23-05-2026): Millisecond timestamp [HH:MM:SS.mmm] prefix on every
# log line via plugin_utils.install_timestamp_filter() — matches Device
# Activity Monitor convention. New "Toggle Timestamps in Log" menu item.
#
# v1.2.8 Changes (13-05-2026) — BREAKING:
# - State IDs renamed from snake_case to camelCase in Devices.xml + plugin.py:
#     zone_mode          -> zoneMode
#     zone_controller_id -> zoneControllerId
#     zone_name          -> zoneName
#     last_seen          -> lastSeen
#   Indigo state IDs MUST be camelCase ASCII per CLAUDE.md rule. The
#   underscore form worked statically but would have failed if these states
#   were ever declared dynamically. EXISTING TRIGGERS / CONTROL PAGES /
#   SCRIPTS REFERENCING THE OLD STATE NAMES MUST BE UPDATED. State history
#   on existing zone devices is lost.
#
# v1.2.7 Changes (10-05-2026):
# - Version is now read dynamically from Info.plist via self.pluginVersion
#   (PLUGIN_VERSION constant removed — Info.plist is the single source of truth)
# - Added log_startup_banner() via bundled plugin_utils.py
# - Added MenuItems.xml + showPluginInfo callback (re-runs the banner on demand)
# - Hardcoded broker IP fallback removed; PluginConfig default cleared. Plugin now
#   logs ERROR if neither IndigoSecrets.py MQTT_BROKER nor PluginConfig provides a host
# - IndigoSecrets.py imports split into per-key try/except so a missing key doesn't blank others
# - PluginConfig version note refreshed (was stuck at 1.1.8)
#
# v1.2.6 Changes (05-05-2026):
# - Add 5-minute delay before sending "gateway offline" Pushover notification
#   * gateway_offline_since records when offline was first detected (time.time())
#   * runConcurrentThread checks elapsed time; only alerts after GATEWAY_OFFLINE_DELAY
#   * If gateway recovers within 5 min, timer is cancelled and no alerts are sent
#   * "restored" alert is only sent if the offline alert was actually sent
#
# v1.2.5 Changes (08-04-2026):
# - Gateway offline/restored Pushover notifications
#   * _handle_info_message now checks "online"/"offline" payload for known gateway
#   * Queues "offline" or "restored" alert via pending_gateway_alert (thread-safe)
#   * runConcurrentThread drains alert and calls _send_gateway_alert on main thread
#   * Alert sent once per offline event; reset when gateway restores
#   * Every plugin reload when gateway is offline will re-alert (confirms fault still present)

try:
    import indigo
except ImportError:
    pass

try:
    import paho.mqtt.client as mqtt
    PAHO_AVAILABLE = True
except ImportError:
    PAHO_AVAILABLE = False

import json
import queue
import re
import threading
import time
from datetime import datetime, timedelta

import os as _os
import sys as _sys
_sys.path.insert(0, _os.getcwd())   # bundled plugin_utils.py
_sys.path.insert(0, "/Library/Application Support/Perceptive Automation")  # shared IndigoSecrets.py

# Per-key secrets imports — a missing single key must not blank the others.
# Master file: IndigoSecrets.py (renamed from secrets.py on 10-May-2026 to
# avoid shadowing Python's stdlib `secrets` module).
try:
    from IndigoSecrets import MQTT_BROKER
except ImportError:
    MQTT_BROKER = ""
try:
    from IndigoSecrets import MQTT_PORT
except ImportError:
    MQTT_PORT = ""
try:
    from IndigoSecrets import MQTT_USERNAME
except ImportError:
    MQTT_USERNAME = ""
try:
    from IndigoSecrets import MQTT_PASSWORD
except ImportError:
    MQTT_PASSWORD = ""

try:
    from plugin_utils import log_startup_banner
except ImportError:
    log_startup_banner = None
try:
    from plugin_utils import install_timestamp_filter
except ImportError:
    install_timestamp_filter = None
try:
    from plugin_utils import as_bool
except ImportError:
    # Local fallback so a stale bundled plugin_utils cannot break a pref read.
    def as_bool(value, default=False):
        if isinstance(value, bool):
            return value
        if value is None or value == "":
            return default
        s = str(value).strip().lower()
        if s in ("true", "1", "yes", "on", "t"):
            return True
        if s in ("false", "0", "no", "off", "f"):
            return False
        return default

# Per-valve liveness + battery. Kept in its own module with no indigo import so the
# decoding can be driven by tests without a gateway.
from ramses_trv import (            # noqa: E402
    OPCODE_BATTERY,
    TrvRegistry,
    describe,
    parse_battery,
    trv_source,
    trv_zone_from_fields,
    unheard_summary,
)

# The boiler relay (BDR91) and the controller's boiler demand. Same reason as above:
# no indigo import, so the decode is testable without a gateway.
from ramses_relay import (          # noqa: E402
    OPCODE_ACTUATOR_STATE,
    OPCODE_HEAT_DEMAND,
    OPCODE_RELAY_DEMAND,
    controller_source,
    parse_boiler_demand,
    parse_relay_state,
    relay_is_closed,
    relay_source,
)
from ramses_relay import describe as describe_relay   # noqa: E402
import ramses_timetable as timetable                  # noqa: E402

# ==============================================================================
# CONSTANTS
# ==============================================================================

# PLUGIN_VERSION is read dynamically from Info.plist by Indigo and passed to
# Plugin.__init__ as `plugin_version` (exposed as self.pluginVersion).  Do NOT
# add a hardcoded version constant here — Info.plist is the single source of truth.

# The Evohome timetables are read once a day at this local time (and on request). A full
# read of 12 zones is about 36 radio exchanges, a minute or so, measured 29-09-2026.
TIMETABLE_READ_MINUTE  = 3 * 60 + 15   # 03:15
TIMETABLE_ASK_TIMEOUT  = 4.0           # seconds to wait for each fragment
TIMETABLE_ASK_TRIES    = 3
TIMETABLE_ASK_GAP      = 0.5           # seconds between requests, to be gentle on the radio
TIMETABLE_STARTUP_WAIT = 120           # seconds after subscribing before a first-ever read

MQTT_KEEPALIVE         = 60            # seconds for MQTT keepalive ping
MQTT_RECONNECT_DELAY   = 60            # seconds between reconnect attempts
GATEWAY_OFFLINE_DELAY  = 300           # seconds to wait before sending offline Pushover alert

RAMSES_ROOT            = "RAMSES/GATEWAY"
# Discovery: the firmware publishes RAMSES/GATEWAY/<gw_id> = "online" (retained) as the
# gateway presence topic, with an MQTT LWT of "offline". The single-level '+' wildcard below
# matches ONLY that 3-segment presence topic — the deeper .../info/firmware and .../info/version
# sub-topics are intentionally NOT subscribed (the plugin doesn't use the firmware metadata).
TOPIC_INFO_WILDCARD    = "RAMSES/GATEWAY/+"

# RAMSES-II opcodes (v1.0 scope: zone thermostat messages only)
OPCODE_ZONE_NAME       = "0004"        # zone name (broadcast by controller)
OPCODE_ZONE_TEMP       = "30C9"        # current zone temperatures (broadcast)
OPCODE_ZONE_SETPOINT   = "2309"        # zone setpoints (broadcast)
OPCODE_ZONE_MODE       = "2349"        # zone mode / override

# Temperature encoding
TEMP_UNKNOWN_RAW       = 0x7FFF        # sentinel value meaning unknown / not set
TEMP_SCALE             = 100.0         # raw int / TEMP_SCALE = degrees C

# Zone mode codes (byte 3 of 2349 payload)
ZONE_MODE_SCHEDULE     = 0x00          # following schedule
ZONE_MODE_ADVANCED     = 0x01          # advanced override (until the next switch point)
ZONE_MODE_PERMANENT    = 0x02          # permanent override
ZONE_MODE_COUNTDOWN    = 0x03          # countdown override (for a number of minutes)
ZONE_MODE_TEMPORARY    = 0x04          # temporary override (until a date and time)

# A temporary override holds the setpoint until a time, then the zone goes back to the
# Evohome timetable by itself. PROVEN LIVE 28-09-2026 on controller 01:091567: a W 2349
# 013 with mode 04 was echoed at once, and when it ran out the controller broadcast
# I 2349 007 ...00FFFFFF (schedule) with the timetable setpoint. The lapse came at
# 19:21:01 for an until of 19:22, so this controller's clock runs about a minute fast.
TEMP_OVERRIDE_MIN_MINUTES = 10
TEMP_OVERRIDE_MAX_MINUTES = 24 * 60
TEMP_OVERRIDE_DEFAULT_MINUTES = 120
TEMP_OVERRIDE_MAX_DAYS    = 366          # an explicit end time may be up to a year ahead
ZONE_MODE_NAMES = {
    ZONE_MODE_SCHEDULE:  "schedule",
    ZONE_MODE_ADVANCED:  "advanced override",
    ZONE_MODE_PERMANENT: "permanent override",
    ZONE_MODE_COUNTDOWN: "countdown override",
    ZONE_MODE_TEMPORARY: "temporary override",
}

# Indigo device type ID (must match Devices.xml)
DEVICE_TYPE_ID         = "ramsesZoneThermostat"

# Evohome supports at most 12 heating zones (indices 0-11). RAMSES domain codes such as
# 0xF9 (CH), 0xFA (DHW), 0xFC (boiler relay) also appear as the "zone" byte in 30C9/2309
# broadcasts — they are NOT zones and must never spawn a spurious "RAMSES Zone 252" device.
MAX_ZONES              = 12

# Device folder name — all zone devices are created inside this Indigo folder
DEVICE_FOLDER_NAME     = "RAMSES"

# Zone state `gatewayStatus`: whether the RAMSES-ESP GATEWAY itself is alive, from the
# retained presence message it publishes ("online") and its MQTT last will ("offline").
# Deliberately separate from the older `online` state, which follows THIS plugin's link to
# the broker and so stays "true" when the gateway dies with the broker still up. Three
# values because "we cannot tell" is a real answer: before the first presence message, or
# while our own broker link is down and nothing from the gateway can reach us.
GATEWAY_STATUS_UNKNOWN = "unknown"
GATEWAY_STATUS_ONLINE  = "online"
GATEWAY_STATUS_OFFLINE = "offline"

# Main thread polling interval
MAIN_LOOP_SLEEP        = 5.0           # seconds

# Gateway timestamps earlier than this year are treated as pre-NTP-sync junk.
# The RAMSES-ESP firmware publishes epoch time (1970) until NTP syncs successfully.
EPOCH_SENTINEL_YEAR    = 2020

# Setpoint limits. The Evohome/RAMSES controller enforces a frost floor of ~8 degC, so a
# command below 8 is silently clamped to ~8 by the controller. We mirror that floor here so
# the optimistic setpointHeat shown in the UI matches what the zone actually applies.
SETPOINT_MIN_C         = 8.0
SETPOINT_MAX_C         = 35.0

# --- Per-valve tracking -------------------------------------------------------
# A zone device's `online` and `lastSeen` are about the GATEWAY and the CONTROLLER, not
# the valve: the controller keeps broadcasting a zone whether or not the TRV in it still
# answers, so a dead valve is invisible until the room goes cold. These states are about
# the valves themselves, built from the packets they send for themselves.
#
# The threshold is generous ON PURPOSE. An HR92 is a battery device that transmits when it
# has something to say, so silence is normal for a while and only a LONG silence means
# anything. MEASURED on this gateway on 12-09-2026 over a 35-minute capture of every packet:
# 10 of the 12 valves were heard at all, and the gap between one valve's consecutive packets
# had a MEDIAN of 3.3 minutes and a MAXIMUM of 20.0 minutes (38 gaps). Six hours is eighteen
# times that worst case, so an ordinary quiet spell cannot reach it and a flat cell or a lost
# valve will. Re-measure if the valves are ever replaced, or if the heating is left off for a
# season — this capture was taken in September with every zone at its summer setpoint.
TRV_STALE_HOURS_DEFAULT = 6
TRV_STALE_HOURS_MIN     = 1
TRV_STALE_HOURS_MAX     = 168
TRV_STATE_FILENAME      = "trv_state.json"
TRV_SAVE_INTERVAL       = 300          # seconds between writes of the valve record
TRV_BATTERY_UNKNOWN     = -1           # a percentage nobody has measured

# --- Power-cycle watchdog: proving a plug command actually landed -------------
# indigo.device.turnOff()/turnOn() are FIRE AND FORGET. Indigo queues the command to the
# plug's owning plugin and returns, so a command to an unreachable plug raises NOTHING.
# On 19-Sep-2026 the IoT WiFi dropped, the watchdog fired three cycles at a plug it could
# not reach, logged all six commands as successful, sent two Pushovers saying it had cycled
# the gateway, spent the whole daily cap and then asked for a human. Every claim was false.
# So the plug's own reported state is the evidence, never the absence of an exception.
# --- The boiler relay (BDR91) ---------------------------------------------------
# One device per relay heard on the air, holding whether it is calling the boiler for heat.
# Native sensor type, so onOffState gives Indigo's own on/off icon, "turns on" triggers and
# SQL Logger history. See ramses_relay.py for the packets and their decoding.
RELAY_TYPE_ID            = "ramsesBoilerRelay"
RELAY_DEVICE_NAME        = "Boiler Relay"
# MEASURED 27-09-2026: the BDR91 sent 3EF0 at 11:48:09 and again at 11:58:09 - every ten
# minutes, one report per heating cycle, whether the boiler is running or not. An hour is
# six missed reports in a row, which one lost packet or a busy moment cannot reach.
RELAY_SILENT_MINUTES     = 60
RELAY_HEARD_WRITE_EVERY  = 600          # seconds; lastHeard alone is written no more often
RELAY_DEMAND_UNKNOWN     = -1           # a percentage nobody has reported
RELAY_ERROR_TEXT         = "relay silent"
RELAY_TS_FORMAT          = "%Y-%m-%d %H:%M:%S"

# A gateway can stay connected to the broker, and keep saying it is online, while it
# passes on no radio messages at all. MEASURED 28-09-2026: the controller broadcasts
# every zone's temperature and setpoint about every 3 minutes, and the valves send in
# between, so 15 minutes of nothing is five missed broadcasts. Treated as offline.
GATEWAY_DEAF_SECONDS   = 900

# A setpoint is shown only once the controller reports it back. Until then it is resent
# every SETPOINT_RESEND_SECONDS, SETPOINT_MAX_SENDS times in all; a command still not
# reported after SETPOINT_GIVE_UP_SECONDS (more than one 3-minute broadcast) is warned
# about once. A report within SETPOINT_MATCH_C of what was sent counts - half a step of
# the controller's 0.5 degC resolution, so an old value one step away never does.
SETPOINT_RESEND_SECONDS = 60
SETPOINT_MAX_SENDS      = 3
SETPOINT_GIVE_UP_SECONDS = 300
SETPOINT_FORGET_SECONDS = 1800
SETPOINT_MATCH_C        = 0.26

# Who changed a zone (1.15.0). A setpoint or mode change the controller reports is ours
# when this plugin sent that setpoint within the last SOURCE_WINDOW_SECONDS; a change to
# "schedule" is the Evohome timetable (or one of our timed settings running out); any
# other change came from outside Indigo - the controller's screen, a valve's wheel or the
# Evohome app. EvoHomeControl leaves a room changed by hand alone for a while.
SOURCE_WINDOW_SECONDS   = 900
SOURCE_INDIGO           = "indigo"
SOURCE_TIMETABLE        = "timetable"
SOURCE_MANUAL           = "manual"

WD_VERIFY_SECONDS      = 8.0           # how long to wait for the plug to report the new state
WD_VERIFY_POLL         = 0.5           # seconds between reads while waiting


def _tri(value, yes, no):
    """A three-valued flag as the word Indigo stores. None is a real answer.

    The two callers use DIFFERENT vocabularies on purpose: Indigo builds a boolean
    sub-state per List option, so "trvStatus.silent" and "trvBatteryWarn.low" say
    what a trigger is for, where a shared yes/no would give "trvStatus.no".
    """
    if value is None:
        return "unknown"
    return yes if value else no


def _liveness(value):
    """Is the zone's valve answering? unknown / answering / silent."""
    return _tri(value, "answering", "silent")


def _battery_warn(value):
    """Is a valve warning about its battery? unknown / low / ok."""
    return _tri(value, "low", "ok")


# ==============================================================================
# PLUGIN CLASS
# ==============================================================================

class Plugin(indigo.PluginBase):

    # --------------------------------------------------------------------------
    # Lifecycle
    # --------------------------------------------------------------------------

    def __init__(self, plugin_id, plugin_display_name, plugin_version, plugin_prefs):
        super(Plugin, self).__init__(plugin_id, plugin_display_name, plugin_version, plugin_prefs)

        self.timestamp_enabled = bool(plugin_prefs.get("timestampEnabled", True))
        if install_timestamp_filter:
            self._ts_filter = install_timestamp_filter(self, enabled=self.timestamp_enabled)
        else:
            self._ts_filter = None

        # Startup banner moved to showPluginInfo on demand (revised 25-May-2026 per Jay).

        self.debug = False

        # MQTT client state
        self.mqtt_client        = None
        self.mqtt_connected     = False
        self.mqtt_lock          = threading.Lock()   # protects mqtt_client access

        # Gateway identity
        self.gateway_id         = ""                 # e.g. "18:730"
        self.gateway_subscribed = False              # True once subscribed to gw rx topic

        # Pending zone state updates from MQTT callbacks -> processed by main thread
        # Structure: {zone_idx(int): {"temp": float, "setpoint": float, "mode": str,
        #                             "mode_byte": int, "controller_id": str, "ts": str}}
        # Dict keys are overwritten on repeat updates (only latest value matters)
        self.pending_updates    = {}
        # Pending zone name updates from 0004 messages -> {zone_idx(int): name(str)}
        # Applied by main thread: stores state and optionally renames the Indigo device.
        self.pending_zone_names = {}
        self.pending_lock       = threading.Lock()   # protects pending_updates, pending_zone_names, pending_gateway_id

        # New gateway ID discovered by MQTT callback thread, pending persist by main thread.
        # Writing pluginPrefs from the MQTT callback thread triggers closedPrefsConfigUi
        # which disconnects MQTT - so we defer the prefs write to the main thread.
        self.pending_gateway_id = ""                 # guarded by pending_lock

        # Our Evohome controller. Learned once (prefs, else the zone devices, else the
        # first controller heard) and then every other controller is ignored, so a
        # neighbour's system in radio range cannot write into our zones.
        self.controller_id         = ""
        self.pending_controller_id = ""     # guarded by pending_lock; persisted by the main thread
        self._foreign_controllers  = set()  # other controllers already mentioned once

        # When a radio message last arrived, and since when we have been listening for
        # them. A gateway connected to the broker but passing on nothing is "deaf".
        self._last_rx_time         = 0.0
        self._rx_listen_since      = time.time()
        self.gateway_deaf          = False  # guarded by pending_lock

        # Setpoints sent but not yet reported back by the controller.
        # {zone_idx: {"sp": float, "first": ts, "last": ts, "sends": int}}; pending_lock.
        self.pending_setpoints     = {}
        # Zones already told they cannot be set during this outage, so it is said once.
        self._setpoint_refused     = set()
        # The last setpoint this plugin sent to each zone, and when: {zone: (setpoint, ts)}.
        # Kept after confirmation, to tell our own changes from ones made by hand.
        self._sent_log             = {}

        # Set here as well as in startup(): startup() returns early when paho is missing,
        # and the main loop reads this every pass.
        self._zone_names_requested = False
        self._mqtt_connected_before = False

        # Evohome timetables (1.13.0). One reader thread at a time; replies are handed to it
        # from the MQTT thread through a queue, and its results back to the main loop,
        # which alone writes device states.
        self._timetable_lock      = threading.Lock()
        self._timetable_replies   = queue.Queue()
        self._timetable_requested = False
        self._timetable_last_date = ""          # local date of the last completed read
        self._timetable_results   = None        # (results, failed) for the main loop; pending_lock
        self._stopping            = threading.Event()

        # Gateway online/offline monitoring
        self.gateway_online        = None   # None=unknown, True=online, False=offline
        self.gateway_alert_sent    = False  # True after offline Pushover sent; reset on restore
        self.gateway_offline_since = None   # time.time() when offline first detected; None if not offline
        self.pending_gateway_alert = None   # "restored" alert — drained by runConcurrentThread

        # Power-cycle watchdog state (prefs loaded in _read_prefs; main thread only).
        # The off/on cycle runs inside a SINGLE main-loop tick (see _power_cycle_plug) with a
        # try/finally restore, so there is no cross-tick "plug is off" state that a reload or
        # crash could strand. The daily counters are persisted so a reload can't reset the cap.
        self.wd_enabled         = False
        self.wd_plug_id         = 0      # Indigo relay device powering the gateway
        self.wd_offline_minutes = 15
        self.wd_off_seconds     = 10
        self.wd_max_cycles      = 3
        self.wd_last_cycle_ts   = 0.0    # time.time() the last cycle started (persisted)
        self.wd_cycle_day       = ""     # "YYYY-MM-DD" the daily counter belongs to (persisted)
        self.wd_cycles_today    = 0      # cycles done today, capped at wd_max_cycles (persisted)
        self.wd_gave_up_alerted = False  # one "giving up" Pushover per outage
        # A cycle only counts against wd_cycles_today once the plug has been SEEN to move.
        # These track the attempts that never happened, so an unreachable plug cannot quietly
        # eat the daily cap (19-Sep-2026).
        self.wd_no_cycle_streak  = 0     # consecutive attempts that did not cycle the plug
        self.wd_no_cycle_alerted = False # one "could not cycle" Pushover per outage

        # Known zone -> Indigo device ID mapping (rebuilt from existing devs at startup)
        self.zone_devices       = {}                 # {zone_idx(int): indigo_dev_id(int)}
        self.zone_lock          = threading.Lock()   # protects zone_devices

        # MQTT connection settings (loaded from pluginPrefs in startup / closedPrefsConfigUi)
        self.broker_host        = MQTT_BROKER
        self.broker_port        = 1883
        self.broker_username    = MQTT_USERNAME
        self.broker_password    = MQTT_PASSWORD

        # Timestamp of last _mqtt_connect() call; prevents the main-loop health check
        # from triggering a reconnect before paho's async on_connect has had time to fire.
        self._last_connect_time = 0.0

        # Per-valve liveness + battery. Written from the MQTT callback thread and read
        # from the main thread, hence its own lock — a separate one from pending_lock so
        # a radio packet never has to wait on the zone-update drain.
        self.trv          = TrvRegistry()
        self.trv_lock     = threading.Lock()
        self.trv_stale_hours = TRV_STALE_HOURS_DEFAULT
        self.trv_report_faults = True
        # Defaulted here as well as in the pref read: _publish_trv_states runs from the
        # worker and swallows its own exceptions at DEBUG, so an attribute missing on an
        # early pass would take valve tracking out silently.
        self.trv_expect_every_zone = True
        # Last summary WRITTEN per zone, so an unchanged one costs no Indigo call.
        self._trv_published  = {}
        self._trv_state_dirty = False
        self._trv_warned      = set()   # zones already warned about, so silence is said once
        self._trv_saved_at    = 0.0
        # Set in startup(); a valve cannot be called silent for a stretch nobody heard.
        self._trv_listening_since = time.time()
        # Whether Indigo accepts clearErrorState on a BATCH state write. None until the
        # first write finds out; see _write_states.
        self._batch_keeps_error = None
        # Last gatewayStatus WRITTEN per zone device ID, so an unchanged value costs no
        # Indigo call on each 5-second pass.
        self._gw_status_written = {}

        # Boiler relay. The MQTT thread records what the relay and the controller said,
        # under relay_lock; the main thread turns that into device states. The DEVICE owns
        # "when it last switched" (relayLastChanged), because it survives a restart and
        # this dict does not.
        self.relay_lock     = threading.Lock()
        self.relay_heard    = {}     # {addr: {"heard": ts, "level": pct|None, "level_ts": ts}}
        self.boiler_demand  = {"heat": None, "relay": None}   # FC domain, whole percent
        self.relay_devices  = {}     # {addr: indigo_dev_id}; guarded by relay_lock
        self._relay_written = {}     # {dev_id: last states written}, so unchanged costs nothing
        self._relay_heard_written = {}   # {dev_id: ts of the last lastHeard written}
        self._relay_warned  = set()  # dev ids already warned about as silent
        self._relay_listening_since = time.time()
        self._relay_demand_note = False   # said once that demand cannot be attributed
        self._relay_pass_error  = None    # last relay-pass fault warned about
        # Relays the user deleted, by address: never created again (1.14.0). Loaded from
        # and saved to the prefs, so a restart does not bring one back.
        self.ignored_relays     = set()
        # Burner time per relay per clock hour, for the hourly summary (1.14.0).
        # {dev_id: {"hour": datetime, "on_secs": float, "calls": int, "last": ts, "on": bool}}
        self._relay_hours       = {}

    # --------------------------------------------------------------------------

    def startup(self):
        # One summary line at the end of startup; the detail goes to DEBUG (house rule:
        # Indigo's own "Started plugin" line plus at most one of ours).
        if not PAHO_AVAILABLE:
            self.logger.error(
                "paho-mqtt library not found in Contents/Packages/ - plugin cannot run. "
                "Check that the paho/ directory was copied correctly."
            )
            return

        self._read_prefs()

        # Rebuild zone_devices index from any existing Indigo devices (e.g. after restart)
        restored = 0
        for dev in indigo.devices.iter(f"self.{DEVICE_TYPE_ID}"):
            try:
                zone_idx = int(dev.address)
                with self.zone_lock:
                    self.zone_devices[zone_idx] = dev.id
                self.logger.debug(f"  Restored Zone {zone_idx}: '{dev.name}' (dev ID {dev.id})")
                restored += 1

                # Force state-list refresh BEFORE seeding (v1.2.8 snake_case ->
                # camelCase rename means existing devices need Indigo to re-read
                # the new state IDs from Devices.xml).
                try:
                    dev.stateListOrDisplayStateIdChanged()
                    dev = indigo.devices[dev.id]
                except Exception as exc:
                    self.logger.debug(f"    state list refresh failed for '{dev.name}': {exc}")

                # Seed zoneName from device name if still empty.
                # The Evohome controller (01:) ignores RQ 0004 from an 18: gateway,
                # so opcode 0004 only arrives when the controller broadcasts it naturally
                # (on startup / name change). Until then, derive zoneName from the
                # Indigo device name by stripping a trailing " Radiator" suffix.
                # A real 0004 message will overwrite this when it eventually arrives.
                if not dev.states.get("zoneName", ""):
                    derived = dev.name
                    if derived.endswith(" Radiator"):
                        derived = derived[:-len(" Radiator")]
                    try:
                        self._write_states(dev, [{"key": "zoneName", "value": derived}])
                        self.logger.debug(f"    zoneName seeded from device name: '{derived}'")
                    except Exception as exc:
                        self.logger.warning(f"    Could not seed zoneName for '{dev.name}': {exc}")

            except (ValueError, Exception) as exc:
                self.logger.warning(f"  Could not restore zone device '{dev.name}': {exc}")

        if not self.controller_id:
            self.controller_id = self._controller_from_zone_devices()
        for dev in indigo.devices.iter(f"self.{RELAY_TYPE_ID}"):
            with self.relay_lock:
                self.relay_devices[dev.address] = dev.id
        # Silence is only meaningful once we have listened for longer than it takes.
        self._relay_listening_since = time.time()
        # Valve records are restored, but the clock that decides whether SILENCE means
        # anything starts NOW — nothing can be called silent for a stretch when this
        # plugin was not listening to it.
        self._load_trv_state()
        self._trv_listening_since = time.time()
        self.logger.info(
            f"RAMSES ESP ready: {restored} zone(s), broker {self.broker_host}:{self.broker_port}, "
            f"gateway {self.gateway_id or '(awaiting discovery)'}, "
            f"controller {self.controller_id or '(awaiting first message)'}"
        )
        # Note: MQTT connection is started in runConcurrentThread after a short delay

        # One-time flag: True once RQ 0004 has been sent to populate zoneName states.
        # Set False here so zone names are re-requested on every plugin restart.
        self._zone_names_requested = False

    # --------------------------------------------------------------------------

    def shutdown(self):
        self._stopping.set()
        self.logger.info("RAMSES ESP Plugin shutting down")
        self._save_trv_state()
        self._mqtt_disconnect()

    # --------------------------------------------------------------------------

    def runConcurrentThread(self):
        """Main plugin loop. Starts MQTT, drains pending zone updates every 5s.

        Each pass is wrapped so one unexpected error LOGS AND CONTINUES rather than
        killing the loop (and with it all zone updates + the watchdog). self.StopThread
        is always re-raised so the plugin still shuts down cleanly.
        """
        try:
            # Give startup() a moment to complete before connecting
            self.sleep(2)
            self._mqtt_connect()

            while True:
                try:
                    self._main_loop_pass()
                except self.StopThread:
                    raise
                except Exception as exc:
                    self.logger.error(f"[MainLoop] Unhandled error this pass — continuing: {exc}")
                    self.sleep(MAIN_LOOP_SLEEP)

        except self.StopThread:
            pass

    def _main_loop_pass(self):
        """One pass of the main loop: drain the MQTT-callback queues, apply the updates,
        run the watchdog, then sleep. Extracted from runConcurrentThread so the loop can
        wrap it in a single try/except for per-pass failure isolation."""
        # --- Drain pending updates from MQTT callbacks ---
        with self.pending_lock:
            updates    = dict(self.pending_updates)
            self.pending_updates.clear()
            zone_names = dict(self.pending_zone_names)
            self.pending_zone_names.clear()
            new_gw_id     = self.pending_gateway_id
            self.pending_gateway_id = ""
            new_ctrl_id   = self.pending_controller_id
            self.pending_controller_id = ""
            gateway_alert = self.pending_gateway_alert
            self.pending_gateway_alert = None

        # Persist new gateway ID to prefs (must be done on main thread)
        if new_gw_id:
            self._persist_gateway_id(new_gw_id)
        if new_ctrl_id:
            self._persist_controller_id(new_ctrl_id)

        # A gateway that is connected but passing on nothing counts as offline, so the
        # alert and the power-cycle watchdog below act on it too.
        self._check_gateway_deaf(time.time())

        # Evohome timetables: publish a finished read, then start one if it is due.
        try:
            self._apply_timetable_results(datetime.now())
            self._maybe_start_timetable_read(datetime.now())
        except Exception as exc:
            self.logger.warning(f"Timetable pass failed: {exc}")

        # Send gateway "restored" Pushover alert if queued
        if gateway_alert:
            self._send_gateway_alert(gateway_alert)

        # Send delayed "offline" alert once GATEWAY_OFFLINE_DELAY has elapsed
        with self.pending_lock:
            offline_since      = self.gateway_offline_since
            alert_already_sent = self.gateway_alert_sent
        if offline_since is not None and not alert_already_sent:
            if time.time() - offline_since >= GATEWAY_OFFLINE_DELAY:
                self._send_gateway_alert("offline")
                with self.pending_lock:
                    self.gateway_alert_sent = True

        # Power-cycle watchdog — recover a gateway that stays offline
        self._watchdog_tick(offline_since)

        # Whether the gateway itself is alive, onto every zone device. Cheap: a value
        # that has not moved writes nothing.
        try:
            self._publish_gateway_status()
        except Exception as exc:
            self.logger.debug(f"Gateway status pass failed: {exc}")

        # Per-valve liveness + battery. Cheap: a summary that has not moved writes nothing.
        try:
            self._publish_trv_states()
            if self._trv_state_dirty and time.time() - self._trv_saved_at > TRV_SAVE_INTERVAL:
                self._save_trv_state()
                self._trv_saved_at = time.time()
        except Exception as exc:
            self.logger.debug(f"Valve tracking pass failed: {exc}")

        # The boiler relay. Cheap: states that have not moved write nothing.
        try:
            self._publish_relay_states()
        except Exception as exc:
            # Said once per distinct fault: a DEBUG line would hide a relay device that
            # quietly stopped updating, which is the one thing this feature exists to show.
            if str(exc) != self._relay_pass_error:
                self._relay_pass_error = str(exc)
                self.logger.warning(f"Boiler relay update failed: {exc}")

        # Setpoints the controller has not reported back yet: resend, or give up.
        try:
            self._retry_setpoints(time.time())
        except Exception as exc:
            self.logger.warning(f"Setpoint retry pass failed: {exc}")

        # Apply zone name updates (store state + auto-rename device)
        for zone_idx, name in zone_names.items():
            try:
                self._apply_zone_name_update(zone_idx, name)
            except Exception as exc:
                self.logger.error(f"Error applying name for Zone {zone_idx}: {exc}")

        for zone_idx, data in updates.items():
            try:
                # Offline flag is set by _on_disconnect and takes priority.
                if data.get("offline"):
                    self._apply_offline_update(zone_idx)
                else:
                    # Apply setpoint/mode BEFORE temp so a same-tick temperature update's
                    # hvacHeaterIsOn calc sees the new setpoint (no one-tick-stale indicator).
                    # A 2349 (mode) carries the setpoint; a 2309 is setpoint-only — never both.
                    if "mode" in data:
                        self._apply_mode_update(zone_idx, data)
                    elif "setpoint" in data:
                        self._apply_setpoint_update(zone_idx, data)
                    if "temp" in data:
                        self._apply_temp_update(zone_idx, data)
            except Exception as exc:
                self.logger.error(f"Error applying update for Zone {zone_idx}: {exc}")

        # --- One-time zone name request ---
        # Send RQ 0004 for all zones once we have MQTT + a known controller_id.
        # Ensures zoneName states are populated immediately after startup rather
        # than waiting for the controller to broadcast 0004 on its own schedule.
        if not self._zone_names_requested and self.mqtt_connected and self.gateway_id:
            if self._request_zone_names():
                self._zone_names_requested = True

        # --- Reconnect if MQTT dropped ---
        # Guard: allow at least MQTT_RECONNECT_DELAY seconds since the last
        # connect attempt before trying again.  This prevents the health check
        # from tearing down a brand-new paho connection before on_connect fires
        # (paho's async TCP handshake can take a second or two on a LAN).
        if not self.mqtt_connected:
            secs_since_connect = time.time() - self._last_connect_time
            if secs_since_connect >= MQTT_RECONNECT_DELAY:
                self.logger.warning("MQTT not connected - attempting reconnect...")
                self._mqtt_connect()
                self.sleep(MQTT_RECONNECT_DELAY)
            else:
                # Still within the connect grace period - just keep polling
                self.sleep(MAIN_LOOP_SLEEP)
        else:
            self.sleep(MAIN_LOOP_SLEEP)

    # --------------------------------------------------------------------------
    # Plugin Prefs
    # --------------------------------------------------------------------------

    def validatePrefsConfigUi(self, values_dict):
        errors_dict = indigo.Dict()

        # Host and port may be left blank when IndigoSecrets.py supplies them, because
        # _read_prefs reads the file first and these fields only as a fallback. Refusing
        # a blank field there made the dialog unsaveable for anyone using the file.
        port_str = str(values_dict.get("mqtt_broker_port", "1883")).strip()
        if port_str or self._secret_broker_port() is None:
            try:
                port = int(port_str)
                if not (1 <= port <= 65535):
                    errors_dict["mqtt_broker_port"] = "Port must be between 1 and 65535"
            except ValueError:
                errors_dict["mqtt_broker_port"] = "Port must be a whole number"

        if not str(values_dict.get("mqtt_broker_host", "")).strip() and not MQTT_BROKER:
            errors_dict["mqtt_broker_host"] = (
                "Broker host is required (or set MQTT_BROKER in IndigoSecrets.py)"
            )

        # Validate and auto-correct the gateway ID field.
        # Valid format: NN:NNNNNN (e.g. "18:203052"). Empty = auto-discover.
        # If the user typed it multiple times (e.g. "18:20305218:20305218:..."),
        # try to extract the first valid segment automatically.
        raw_gw = values_dict.get("discovered_gateway_id", "").strip()
        if raw_gw:
            clean = self._sanitise_gateway_id(raw_gw)
            if clean:
                values_dict["discovered_gateway_id"] = clean
            else:
                errors_dict["discovered_gateway_id"] = (
                    "Gateway ID must be in format NN:NNNNNN (e.g. 18:203052). "
                    "Clear the field to let the plugin discover it automatically."
                )
        else:
            values_dict["discovered_gateway_id"] = ""

        # Power-cycle watchdog fields
        if values_dict.get("watchdog_enabled", False):
            plug_str = str(values_dict.get("watchdog_plug_device", "")).strip()
            if not plug_str or plug_str == "0" or not plug_str.isdigit():
                errors_dict["watchdog_plug_device"] = (
                    "Select the smart plug that powers the gateway"
                )
        for key, label, lo, hi in (
            ("watchdog_offline_minutes", "Offline minutes", 5, 1440),
            ("watchdog_off_seconds",     "Off seconds",     3, 120),
            ("watchdog_max_cycles",      "Max cycles/day",  1, 20),
        ):
            raw = str(values_dict.get(key, "")).strip()
            if raw:
                try:
                    val = int(raw)
                    if not (lo <= val <= hi):
                        errors_dict[key] = f"{label} must be between {lo} and {hi}"
                except ValueError:
                    errors_dict[key] = f"{label} must be a whole number"

        if len(errors_dict) > 0:
            return (False, values_dict, errors_dict)
        return (True, values_dict)

    def closedPrefsConfigUi(self, values_dict, user_cancelled):
        if user_cancelled:
            return

        old_host = self.broker_host
        old_port = self.broker_port
        old_gw   = self.gateway_id

        self._read_prefs()

        broker_changed  = (self.broker_host != old_host or self.broker_port != old_port)
        gateway_cleared = (not self.gateway_id and old_gw)
        gateway_changed = (self.gateway_id and old_gw and self.gateway_id != old_gw)

        if broker_changed:
            self.logger.info("Broker settings changed - reconnecting MQTT")
            self._mqtt_disconnect()
            self._mqtt_connect()

        if gateway_cleared:
            self.logger.info("Gateway ID cleared - will re-discover on next MQTT message")
            self.gateway_subscribed = False
        elif gateway_changed and not broker_changed:
            # Gateway ID was manually edited to a different value. The broker is unchanged
            # (so _mqtt_connect was not called above to do it for us), so drop the stale rx
            # subscription flag and resubscribe to the NEW gateway's rx topic directly.
            self.logger.info(f"Gateway ID changed {old_gw} -> {self.gateway_id} - resubscribing")
            self.gateway_subscribed = False
            self._resubscribe_to_gateway()

    # --------------------------------------------------------------------------
    # Device Lifecycle
    # --------------------------------------------------------------------------

    def deviceStartComm(self, dev):
        super(Plugin, self).deviceStartComm(dev)
        if dev.deviceTypeId == RELAY_TYPE_ID:
            self._start_relay_device(dev)
            return
        # Force Indigo to re-read Devices.xml state list. This is required
        # whenever <State> IDs in Devices.xml change (e.g. v1.2.8 snake_case
        # -> camelCase rename). Without this, existing devices keep their
        # cached state list and updateStatesOnServer() on the new state IDs
        # silently fails with "state key X not defined".
        try:
            dev.stateListOrDisplayStateIdChanged()
            dev = indigo.devices[dev.id]
        except Exception as exc:
            self.logger.debug(f"stateListOrDisplayStateIdChanged failed for '{dev.name}': {exc}")
        # Lock thermostat capabilities to heat-only on every start.
        # replacePluginPropsOnServer() triggers Indigo to rebuild the device's state list
        # based on the new props, so this must be called even if values haven't changed
        # to ensure Indigo picks up the correct capabilities after a plugin reload.
        try:
            props = dev.pluginProps
            changed = False
            capability_defaults = {
                "NumTemperatureInputs":         "1",
                "NumHumidityInputs":            "0",
                "SupportsHeatSetpoint":         True,
                "SupportsCoolSetpoint":         False,
                # SupportsHvacOperationMode must be True for the hvacOperationMode state to
                # exist. With False, the state is never created and updateStatesOnServer() fails.
                # We keep mode locked to Heat in actionControlThermostat() SetHvacMode handler.
                "SupportsHvacOperationMode":    True,
                "SupportsHvacFanMode":          False,
                # ShowCoolHeatEquipmentStateUI must be True for hvacHeaterIsOn to exist.
                # This is the "flame on" indicator used by HomeKit to show active heating.
                "ShowCoolHeatEquipmentStateUI": True,
                # SupportsBatteryLevel is DELIBERATELY NOT SET HERE. Declaring it creates
                # Indigo's native batteryLevel, which is born as 0 — and 0% reads to every
                # battery sweep in the house as a flat cell. It is set in _write_trv_states
                # the moment a real reading arrives, so the native state never exists
                # holding a number nobody measured.
            }
            for key, val in capability_defaults.items():
                if props.get(key) != val:
                    props[key] = val
                    changed = True
            if changed:
                dev.replacePluginPropsOnServer(props)
                # Re-fetch: replacePluginPropsOnServer() creates new built-in thermostat
                # states (hvacOperationMode, hvacHeaterIsOn) but the local dev object is
                # stale until refreshed. Without this, updateStatesOnServer() below fails.
                dev = indigo.devices[dev.id]

            # Ensure hvacOperationMode is always Heat.
            # Indigo defaults this to Off (0) which makes HomeKit and other integrations
            # show the device as "OFF". Evohome zones are heat-only — always in Heat mode.
            self._write_states(dev, [{"key": "hvacOperationMode",
                                       "value": indigo.kHvacMode.Heat}])
        except Exception as exc:
            self.logger.warning(f"deviceStartComm: could not set thermostat props for '{dev.name}': {exc}")

        self._seed_trv_states(dev)

    def _seed_trv_states(self, dev):
        """Give the valve states an honest starting value, once, without asserting.

        Indigo materialises a new Integer as 0 and a new List as an empty string, so a zone
        whose valve has never spoken would otherwise show a flat battery and a blank verdict.
        Seed the honest answer and never overwrite a real one.

        WRITTEN IN ITS OWN CALL, NOT ALONGSIDE hvacOperationMode. A single unacceptable value
        makes the server drop the WHOLE updateStatesOnServer batch — silently, with nothing in
        the plugin log or the event log — so a seed that goes wrong must not be able to take
        the thermostat mode with it. That is not hypothetical: it happened here, and the mode
        write rode in the same batch.
        """
        try:
            seed = []
            if not dev.states.get("trvStatus"):
                seed.append({"key": "trvStatus", "value": "unknown"})
            if not dev.states.get("trvBatteryWarn"):
                seed.append({"key": "trvBatteryWarn", "value": "unknown"})
            if not dev.states.get("trvSummary"):
                seed.append({"key": "trvSummary", "value": describe(None, time.time())})
            if dev.states.get("trvBattery", 0) in (0, None):
                seed.append({"key": "trvBattery", "value": TRV_BATTERY_UNKNOWN,
                             "uiValue": "unknown"})
            if seed:
                self._write_states(dev, seed)
        except Exception as exc:
            self.logger.warning(f"deviceStartComm: could not seed valve states for '{dev.name}': {exc}")

    def deviceStopComm(self, dev):
        super(Plugin, self).deviceStopComm(dev)

    @staticmethod
    def didDeviceCommPropertyChange(oldDevice, newDevice):
        """Suppress unnecessary deviceStopComm/deviceStartComm cycles.

        Zone devices are auto-discovered from RAMSES-II radio traffic and have
        no user-editable pluginProps that justify a comm restart. Returning
        False prevents Indigo from cycling comm on every internal
        replacePluginPropsOnServer write.
        """
        return False

    def deviceDeleted(self, dev):
        """Remove the device from the zone_devices index when deleted by the user."""
        if dev.deviceTypeId == RELAY_TYPE_ID:
            # Until 1.14.0 the address stayed in relay_heard, so the next pass created the
            # device again within seconds. A relay the user deletes now stays deleted.
            with self.relay_lock:
                if self.relay_devices.get(dev.address) == dev.id:
                    del self.relay_devices[dev.address]
                self.relay_heard.pop(dev.address, None)
                self.ignored_relays.add(dev.address)
            self._relay_written.pop(dev.id, None)
            self._relay_heard_written.pop(dev.id, None)
            self._relay_hours.pop(dev.id, None)
            self._save_ignored_relays()
            self.logger.info(f"Boiler relay {dev.address} deleted. It will not be created "
                             f"again; Plugins > RAMSES ESP > Bring Back Deleted Boiler Relays "
                             f"undoes that.")
            return
        try:
            zone_idx = int(dev.address)
            with self.zone_lock:
                if zone_idx in self.zone_devices and self.zone_devices[zone_idx] == dev.id:
                    del self.zone_devices[zone_idx]
                    self.logger.info(f"Zone {zone_idx} device deleted from index")
        except (ValueError, Exception):
            pass

    # --------------------------------------------------------------------------
    # Thermostat Actions (built-in Indigo thermostat callback)
    # --------------------------------------------------------------------------

    def actionControlThermostat(self, action, dev):
        """
        Handle built-in Indigo thermostat actions.
        Called by Indigo for SetHeatSetpoint, Increase/DecreaseHeatSetpoint,
        and status-request actions from action groups, schedules, and triggers.
        Cool setpoint / HVAC mode / fan mode are not supported (heat-only zones).
        """
        try:
            if not dev.enabled:
                self.logger.warning(f"'{dev.name}' is disabled - ignoring thermostat action")
                return

            if action.thermostatAction == indigo.kThermostatAction.SetHeatSetpoint:
                new_sp = float(action.actionValue)
                self._validate_and_publish_setpoint(dev, new_sp, "set")

            elif action.thermostatAction == indigo.kThermostatAction.IncreaseHeatSetpoint:
                new_sp = dev.heatSetpoint + float(action.actionValue)
                self._validate_and_publish_setpoint(dev, new_sp, "increase")

            elif action.thermostatAction == indigo.kThermostatAction.DecreaseHeatSetpoint:
                new_sp = dev.heatSetpoint - float(action.actionValue)
                self._validate_and_publish_setpoint(dev, new_sp, "decrease")

            elif action.thermostatAction == indigo.kThermostatAction.SetHvacMode:
                # Evohome zones are heat-only — ignore Off/Cool requests and lock to Heat.
                # HomeKit (and other integrations) may send SetHvacMode(Off) when the user
                # taps the thermostat off. We silently re-assert Heat so the zone stays on.
                requested = action.actionValue
                if requested != indigo.kHvacMode.Heat:
                    self.logger.info(
                        f"'{dev.name}' SetHvacMode({requested}) ignored "
                        f"- Evohome zones are heat-only; mode stays Heat"
                    )
                try:
                    self._write_states(dev, [
                        {"key": "hvacOperationMode", "value": indigo.kHvacMode.Heat},
                    ])
                except Exception as exc:
                    self.logger.warning(
                        f"Could not re-assert Heat mode for '{dev.name}': {exc}"
                    )

            elif action.thermostatAction in (
                indigo.kThermostatAction.RequestStatusAll,
                indigo.kThermostatAction.RequestSetpoints,
                indigo.kThermostatAction.RequestTemperatures,
                indigo.kThermostatAction.RequestMode,
                indigo.kThermostatAction.RequestEquipmentState,
            ):
                # Trigger an immediate zone refresh via RQ 30C9
                self.action_request_zone_update(action)

            else:
                # Cool setpoint / fan mode not applicable to Evohome heat zones
                if self.debug:
                    self.logger.debug(
                        f"'{dev.name}' thermostat action {action.thermostatAction} "
                        f"not supported (heat-only Evohome zone)"
                    )

        except Exception as exc:
            self.logger.error(f"Error in actionControlThermostat for '{dev.name}': {exc}")

    def _validate_and_publish_setpoint(self, dev, setpoint_c, action_str, until=None):
        """
        Clamp setpoint to valid range and publish a W 2349 permanent override.

        setpointHeat is NOT written here. Until 1.11.0 it was written the moment the
        command left, so a command lost on the radio - or sent while the gateway was
        offline - still showed as set, and anything reading setpointHeat (EvoHomeControl
        decides whether to send by it) believed it. The state now changes only when the
        controller reports the new value; _retry_setpoints resends meanwhile.
        """
        with self.pending_lock:
            gateway_online = self.gateway_online
            gateway_deaf   = self.gateway_deaf
        if gateway_online is False or gateway_deaf:
            zone_key = dev.id
            why = ("the gateway is offline" if gateway_online is False
                   else "the gateway is passing on no radio messages")
            if zone_key not in self._setpoint_refused:
                self._setpoint_refused.add(zone_key)
                self.logger.error(
                    f"Cannot {action_str} setpoint for '{dev.name}' - {why}, so Evohome "
                    f"would never receive it"
                )
            else:
                self.logger.debug(f"Cannot {action_str} setpoint for '{dev.name}' - {why}")
            return
        self._setpoint_refused.clear()
        if not self.mqtt_connected:
            self.logger.error(
                f"Cannot {action_str} setpoint for '{dev.name}' - MQTT not connected"
            )
            return
        if not self.gateway_id:
            self.logger.error(
                f"Cannot {action_str} setpoint for '{dev.name}' - gateway not discovered yet"
            )
            return

        setpoint_c = round(max(SETPOINT_MIN_C, min(float(setpoint_c), SETPOINT_MAX_C)), 2)
        zone_idx   = int(dev.address)
        published  = self._publish_setpoint(zone_idx, setpoint_c, until)

        if not published:
            # _publish_setpoint already logged the specific error; nothing more to do
            return

        self._note_setpoint_sent(zone_idx, setpoint_c, time.time(), until)

        # Debug only: the EvoHome script already logs the room action at INFO level.
        # Suppress at INFO to keep the Indigo event log clean during normal operation.
        self.logger.debug(
            f"'{dev.name}' (Zone {zone_idx}) setpoint {action_str} -> {setpoint_c:.1f} degC"
        )

    # --------------------------------------------------------------------------
    # Custom Actions (defined in Actions.xml)
    # --------------------------------------------------------------------------

    def action_set_temporary_setpoint(self, plugin_action, dev=None, callerWaitingForResult=None):
        """Set a zone's temperature for a number of minutes, after which Evohome puts the
        zone back on its own timetable by itself.

        For an automation (EvoHomeControl renews it each hour) this is the safe way to
        hold a setpoint: if Indigo, this plugin or the automation stops, the house goes
        back to the timetable instead of holding the last command for ever, which is what
        a permanent override does. Call with executeAction("setTemporarySetpoint",
        deviceId=<zone>, props={"setpoint": "20.5", "minutes": "120"}) - the deviceId is
        required, as for any device action.
        """
        if dev is None:
            try:
                dev = indigo.devices[int(plugin_action.deviceId)]
            except Exception:
                self.logger.error("Set Temporary Setpoint: no zone device given")
                return
        props = plugin_action.props or {}
        try:
            setpoint_c = float(str(props.get("setpoint", "")).strip())
        except (ValueError, TypeError):
            self.logger.error(f"Set Temporary Setpoint for '{dev.name}': the setpoint "
                              f"'{props.get('setpoint', '')}' is not a number")
            return
        # An end time ("YYYY-MM-DD HH:MM") wins over a length (1.15.0). PROVEN LIVE
        # 29-09-2026: the controller accepts an end weeks or months ahead (14 Oct and
        # 1 June 2027 were both echoed back unchanged), which lets a seasonal hold run
        # out by itself on the day heating is due back.
        end_text = str(props.get("until", "") or "").strip()
        if end_text:
            try:
                until = datetime.strptime(end_text[:16], "%Y-%m-%d %H:%M")
            except ValueError:
                self.logger.error(f"Set Temporary Setpoint for '{dev.name}': the end time "
                                  f"'{end_text}' is not YYYY-MM-DD HH:MM")
                return
            now = datetime.now()
            if not now < until <= now + timedelta(days=TEMP_OVERRIDE_MAX_DAYS):
                self.logger.error(f"Set Temporary Setpoint for '{dev.name}': the end time "
                                  f"{end_text} must be in the next {TEMP_OVERRIDE_MAX_DAYS} days")
                return
        else:
            try:
                minutes = int(float(str(props.get("minutes", TEMP_OVERRIDE_DEFAULT_MINUTES)).strip()))
            except (ValueError, TypeError):
                minutes = TEMP_OVERRIDE_DEFAULT_MINUTES
            minutes = max(TEMP_OVERRIDE_MIN_MINUTES, min(minutes, TEMP_OVERRIDE_MAX_MINUTES))
            # Whole minutes only on the wire, so round the end UP to the next minute.
            until = datetime.now().replace(second=0, microsecond=0)
            until = until + timedelta(minutes=minutes + 1)
        self._validate_and_publish_setpoint(dev, setpoint_c, "set", until=until)

    # --------------------------------------------------------------------------
    # Evohome timetables (1.13.0)
    # --------------------------------------------------------------------------

    def action_read_timetables(self, plugin_action=None):
        """Read every zone's timetable from the controller now, in the background."""
        self._timetable_requested = True
        self.logger.info("Reading the Evohome timetables now. Each room's Timetable state "
                         "updates within about a minute.")

    def menuReadTimetables(self, valuesDict=None, typeId=None):
        self.action_read_timetables()
        return True

    def _note_timetable_reply(self, fields, payload_hex):
        """MQTT thread: hand a timetable fragment from OUR controller to the reader."""
        if not self._timetable_lock.locked():
            return
        if not self._zone_frame_controller(fields):
            return
        parsed = timetable.parse_reply(payload_hex)
        if parsed:
            self._timetable_replies.put(parsed)

    def _timetable_last_read_date(self):
        """The newest local date any zone device says it was read, or ""."""
        newest = ""
        with self.zone_lock:
            dev_ids = list(self.zone_devices.values())
        for dev_id in dev_ids:
            try:
                stamp = str(indigo.devices[dev_id].states.get("timetableRead", "") or "")
            except Exception:
                continue
            newest = max(newest, stamp[:10])
        return newest

    @staticmethod
    def _timetable_due(now, last_date, requested, listening_for):
        """Whether to start a read: on request, once a day at or after 03:15, or soon
        after the very first start when nothing has ever been read."""
        if requested:
            return True
        if not last_date:
            return listening_for >= TIMETABLE_STARTUP_WAIT
        today = now.strftime("%Y-%m-%d")
        return last_date != today and now.hour * 60 + now.minute >= TIMETABLE_READ_MINUTE

    def _maybe_start_timetable_read(self, now):
        if self._timetable_lock.locked():
            return
        with self.pending_lock:
            usable = self.gateway_online is True and not self.gateway_deaf
        if not (usable and self.mqtt_connected and self.gateway_subscribed
                and self.gateway_id and self.controller_id):
            return
        if not self._timetable_last_date:
            self._timetable_last_date = self._timetable_last_read_date()
        if not self._timetable_due(now, self._timetable_last_date, self._timetable_requested,
                                   time.time() - self._rx_listen_since):
            return
        if not self._timetable_lock.acquire(blocking=False):
            return
        self._timetable_requested = False
        with self.zone_lock:
            zones = sorted(self.zone_devices)
        threading.Thread(target=self._read_timetables_worker, args=(zones,),
                         name="RAMSES-timetables", daemon=True).start()

    def _publish_raw(self, msg_str):
        """Send one RAMSES line through the gateway. True once paho has queued it."""
        with self.mqtt_lock:
            if self.mqtt_client is None or not self.mqtt_connected:
                return False
            info = self.mqtt_client.publish(self._gateway_tx_topic(),
                                            json.dumps({"msg": msg_str}), qos=0)
        rc = getattr(info, "rc", 0)
        return not (isinstance(rc, int) and rc != 0)

    def _ask_timetable_fragment(self, zone, frag, total):
        """One fragment of one zone, with retries; the (total, data) reply or None."""
        gw = self.gateway_id.replace("-", ":")
        msg = (f"RQ --- {gw} {self.controller_id} --:------ 0404 007 "
               f"{timetable.build_request(zone, frag, total)}")
        for _ in range(TIMETABLE_ASK_TRIES):
            if self._stopping.is_set():
                return None
            if not self._publish_raw(msg):
                return None
            deadline = time.time() + TIMETABLE_ASK_TIMEOUT
            while True:
                left = deadline - time.time()
                if left <= 0:
                    break
                try:
                    r_zone, r_frag, r_total, data = self._timetable_replies.get(timeout=left)
                except queue.Empty:
                    break
                if (r_zone, r_frag) == (zone, frag):
                    return r_total, data
            time.sleep(TIMETABLE_ASK_GAP)
        return None

    def _read_one_timetable(self, zone):
        first = self._ask_timetable_fragment(zone, 1, 0)
        if first is None:
            return None
        total, data = first
        fragments = [data]
        for frag in range(2, total + 1):
            time.sleep(TIMETABLE_ASK_GAP)
            nxt = self._ask_timetable_fragment(zone, frag, total)
            if nxt is None:
                return None
            fragments.append(nxt[1])
        return timetable.decode(fragments)

    def _read_timetables_worker(self, zones):
        """Background thread: read each zone in turn. Touches no Indigo device; the main
        loop publishes what it finds."""
        results, failed = {}, []
        try:
            while not self._timetable_replies.empty():
                self._timetable_replies.get_nowait()
            for zone in zones:
                if self._stopping.is_set():
                    return
                try:
                    week = self._read_one_timetable(zone)
                except ValueError as exc:
                    self.logger.debug(f"Timetable for zone {zone} could not be decoded: {exc}")
                    week = None
                if week is None:
                    failed.append(zone)
                else:
                    results[zone] = week
                time.sleep(TIMETABLE_ASK_GAP)
            with self.pending_lock:
                self._timetable_results = (results, failed)
        except Exception as exc:
            self.logger.warning(f"Reading the Evohome timetables failed: {exc}")
        finally:
            self._timetable_lock.release()

    def _apply_timetable_results(self, now):
        """Main thread: write what the reader found to the zone devices."""
        with self.pending_lock:
            done, self._timetable_results = self._timetable_results, None
        if done is None:
            return
        results, failed = done
        stamp = now.strftime("%Y-%m-%d %H:%M")
        changed = []
        for zone, week in results.items():
            dev = self._find_zone_device(zone)
            if dev is None:
                continue
            data = timetable.to_json(week)
            before = str(dev.states.get("timetableData", "") or "")
            try:
                self._write_states(dev, [
                    {"key": "timetable",     "value": timetable.describe(week)},
                    {"key": "timetableData", "value": data},
                    {"key": "timetableRead", "value": stamp},
                ])
            except Exception as exc:
                self.logger.warning(f"Could not store the timetable for '{dev.name}': {exc}")
                continue
            if before and before != data:
                changed.append(dev.name)
                self.logger.info(f"The Evohome timetable for '{dev.name}' has changed. "
                                 f"It is now: {timetable.describe(week)}")
        if failed:
            names = []
            for zone in failed:
                dev = self._find_zone_device(zone)
                names.append(f"'{dev.name}'" if dev is not None else f"zone {zone}")
            joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
            self.logger.warning(f"Could not read the Evohome timetable for {joined}. "
                                f"The plugin tries again tomorrow.")
        else:
            self._timetable_last_date = now.strftime("%Y-%m-%d")
        self.logger.debug(f"Read {len(results)} Evohome timetable(s); "
                          f"{len(changed)} changed, {len(failed)} could not be read")

    def action_request_zone_update(self, plugin_action):
        """Send RQ 30C9 to controller to request immediate zone temperature refresh."""
        if not self.mqtt_connected:
            self.logger.warning("Cannot request zone update - MQTT not connected")
            return
        if not self.gateway_id:
            self.logger.warning("Cannot request zone update - gateway not discovered yet")
            return

        # Find the controller ID from any existing zone device
        controller_id = ""
        with self.zone_lock:
            zone_ids = dict(self.zone_devices)
        for zone_idx, dev_id in zone_ids.items():
            try:
                dev = indigo.devices[dev_id]
                cid = dev.states.get("zoneControllerId", "")
                if cid and cid.startswith("01:"):
                    controller_id = cid
                    break
            except Exception:
                pass

        if not controller_id:
            self.logger.warning(
                "Cannot request zone update - no controller ID known yet "
                "(wait for first 30C9 or 2309 message to arrive)"
            )
            return

        gw_addr  = self.gateway_id.replace("-", ":")
        msg_str  = f"RQ --- {gw_addr} {controller_id} --:------ 30C9 001 00"
        payload  = json.dumps({"msg": msg_str})
        topic    = self._gateway_tx_topic()

        try:
            with self.mqtt_lock:
                if self.mqtt_client is not None and self.mqtt_connected:
                    self.mqtt_client.publish(topic, payload, qos=0)
            self.logger.info(f"Zone update requested via {topic}: {msg_str}")
        except Exception as exc:
            self.logger.error(f"Failed to publish zone update request: {exc}")

    # --------------------------------------------------------------------------
    # MQTT Client Management
    # --------------------------------------------------------------------------

    def _mqtt_connect(self):
        """Create and connect paho MQTT client. Uses loop_start() for async I/O."""
        if not PAHO_AVAILABLE:
            return

        try:
            # Cleanly stop any existing client first. loop_stop() waits for paho's thread,
            # and that thread can itself be waiting for mqtt_lock (_resubscribe_to_gateway on
            # first discovery), so the lock is released before stopping - holding it across
            # loop_stop() could freeze the plugin (1.14.0).
            with self.mqtt_lock:
                old_client = self.mqtt_client
                self.mqtt_client = None
                self.mqtt_connected = False
            if old_client is not None:
                try:
                    old_client.loop_stop()
                    old_client.disconnect()
                except Exception:
                    pass

            client_id = f"indigo-ramses-esp-{int(time.time())}"

            # paho 2.x (v1.5.0): callback_api_version is a REQUIRED first
            # positional — omit it and 2.x raises, so the gateway never connects.
            # VERSION2 also changes the connect/disconnect callback signatures;
            # see _on_connect / _on_disconnect below. clean_session stays valid
            # because the default protocol is still MQTTv311.
            client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2,
                client_id=client_id,
                clean_session=True,
                userdata=None
            )

            client.on_connect    = self._on_connect
            client.on_disconnect = self._on_disconnect
            client.on_message    = self._on_message

            if self.broker_username:
                client.username_pw_set(
                    username=self.broker_username,
                    password=self.broker_password
                )

            self._last_connect_time = time.time()
            self.logger.debug(f"Connecting to MQTT broker {self.broker_host}:{self.broker_port}")
            client.connect(
                host=self.broker_host,
                port=self.broker_port,
                keepalive=MQTT_KEEPALIVE
            )
            client.loop_start()

            with self.mqtt_lock:
                self.mqtt_client = client

        except Exception as exc:
            self.logger.error(f"MQTT connection failed: {exc}")
            self.mqtt_connected = False

    def _mqtt_disconnect(self):
        """Gracefully stop the paho client."""
        try:
            with self.mqtt_lock:
                old_client = self.mqtt_client
                self.mqtt_client = None
                self.mqtt_connected = False
            if old_client is not None:
                old_client.loop_stop()      # outside the lock - see _mqtt_connect
                old_client.disconnect()
            self.logger.debug("MQTT client disconnected")
        except Exception as exc:
            self.logger.warning(f"Error during MQTT disconnect: {exc}")

    # --------------------------------------------------------------------------
    # MQTT Callbacks (run on paho's background thread - NO Indigo API calls here)
    # --------------------------------------------------------------------------

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        """Called by paho when connection is established or fails.

        paho 2.x VERSION2 signature: `reason_code` is a ReasonCode object with
        .is_failure and a readable str(), `properties` is None on MQTT 3.1.1, and
        `flags` is a ConnectFlags dataclass (unused here).
        """
        if not reason_code.is_failure:
            self.mqtt_connected = True
            # The first connect is part of starting up; a REconnect is news.
            line = f"MQTT connected to {self.broker_host}:{self.broker_port}"
            if self._mqtt_connected_before:
                self.logger.info(line)
            else:
                self.logger.debug(line)
            self._mqtt_connected_before = True
            # Always subscribe to gateway discovery topic
            client.subscribe(TOPIC_INFO_WILDCARD, qos=0)
            self.logger.debug(f"Subscribed to {TOPIC_INFO_WILDCARD}")

            # If gateway already known from prefs, also subscribe to its rx topic now
            if self.gateway_id and not self.gateway_subscribed:
                rx_topic = f"{RAMSES_ROOT}/{self.gateway_id}/rx"
                client.subscribe(rx_topic, qos=0)
                self.gateway_subscribed = True
                self._rx_listen_since = time.time()
                self.logger.debug(f"Subscribed to {rx_topic}")
        else:
            self.mqtt_connected = False
            # str(ReasonCode) is already readable ("Not authorized", "Bad user
            # name or password", ...). Under VERSION2 even a 3.1.1 broker's
            # CONNACK errors arrive as MQTT-v5 reason codes, so the old 1-5 int
            # label table could never have matched again — deleted in v1.5.0.
            self.logger.error(f"MQTT connection refused: {reason_code}")

    def _on_disconnect(self, client, userdata, disconnect_flags,
                       reason_code, properties=None):
        """Called by paho when disconnected. paho 2.x VERSION2 signature."""
        self.mqtt_connected = False
        self.gateway_subscribed = False
        # Normalise the ReasonCode to an int at the boundary so the clean-vs-
        # unexpected test keeps its old meaning (0 = clean). A ReasonCode that
        # will not convert is treated as unexpected, which is the safe way round:
        # it reconnects rather than assuming a tidy shutdown.
        try:
            rc_val = int(reason_code.value)
        except (AttributeError, TypeError, ValueError):
            rc_val = 0 if reason_code in (0, None) else 1
        if rc_val != 0:
            self.logger.warning(
                f"MQTT unexpected disconnect ({reason_code}) - will reconnect "
                f"in {MQTT_RECONNECT_DELAY}s"
            )
        else:
            self.logger.info("MQTT disconnected cleanly")

        # Queue offline status for all zone devices (applied by main thread)
        with self.pending_lock:
            with self.zone_lock:
                for zone_idx in self.zone_devices:
                    if zone_idx not in self.pending_updates:
                        self.pending_updates[zone_idx] = {}
                    self.pending_updates[zone_idx]["offline"] = True

    def _on_message(self, client, userdata, msg):
        """Called by paho for every received MQTT message. Must not call Indigo API."""
        try:
            topic   = msg.topic
            payload = msg.payload.decode("utf-8", errors="replace")

            if self.debug:
                self.logger.debug(f"MQTT rx [{topic}]: {payload[:200]}")

            parts = topic.split("/")
            # RAMSES/GATEWAY/<gw_id>          -> 3 parts: presence/status topic (payload="online")
            # RAMSES/GATEWAY/<gw_id>/info/...  -> 5 parts: firmware info (NOT subscribed - never seen here)
            # RAMSES/GATEWAY/<gw_id>/rx        -> 4 parts: radio message stream
            if len(parts) == 3 and parts[0] == "RAMSES" and parts[1] == "GATEWAY":
                self._handle_info_message(topic, payload, parts)
            elif topic.endswith("/rx"):
                self._handle_rx_message(payload)

        except Exception as exc:
            self.logger.error(f"Error in _on_message: {exc}")

    # --------------------------------------------------------------------------
    # Gateway Discovery
    # --------------------------------------------------------------------------

    def _handle_info_message(self, topic, payload, parts):
        """
        Extract gateway ID from RAMSES/GATEWAY/<gw_id> presence topic.
        The firmware publishes this with payload "online" (retained) when it connects.
        Topic parts (pre-split by caller): ['RAMSES', 'GATEWAY', '<gw_id>']
        """
        try:
            discovered_id = parts[2].strip()
            if not discovered_id:
                return

            if self.gateway_id == discovered_id:
                payload_lower = payload.strip().lower()
                with self.pending_lock:
                    if payload_lower == "offline":
                        self.gateway_online = False
                        # Start the delay timer only on the first "offline" detection.
                        # runConcurrentThread sends the alert after GATEWAY_OFFLINE_DELAY
                        # seconds — if the gateway recovers before then, the timer is
                        # cancelled and no alert is sent.
                        if self.gateway_offline_since is None and not self.gateway_alert_sent:
                            self.gateway_offline_since = time.time()
                    elif payload_lower == "online":
                        prev_online = self.gateway_online
                        was_deaf    = self.gateway_deaf
                        self.gateway_online = True
                        self.gateway_offline_since = None   # cancel any pending offline timer
                        # A gateway that has just (re)joined gets a fresh listening window
                        # before it can be called deaf again - after a power cycle, say.
                        self.gateway_deaf = False
                        self._rx_listen_since = time.time()
                        # Send "restored" only if the offline alert was actually sent
                        if (prev_online is False or was_deaf) and self.gateway_alert_sent:
                            self.pending_gateway_alert = "restored"
                            self.gateway_alert_sent    = False
                return

            if self.gateway_id:
                self.logger.warning(
                    f"Second gateway seen: '{discovered_id}' "
                    f"(already using '{self.gateway_id}') - ignoring"
                )
                return

            self.logger.info(f"Gateway discovered: {discovered_id}")
            self._set_gateway_id(discovered_id)

            # Honour the retained presence payload on first discovery. A gateway that has
            # died leaves a RETAINED 'offline' LWT on this topic; treating it as online would
            # mean that after a plugin restart during an outage gateway_offline_since is never
            # set and the power-cycle watchdog can never arm. So inspect the payload here too.
            payload_lower = payload.strip().lower()
            with self.pending_lock:
                if payload_lower == "offline":
                    self.gateway_online = False
                    if self.gateway_offline_since is None and not self.gateway_alert_sent:
                        self.gateway_offline_since = time.time()
                else:
                    self.gateway_online = True

        except Exception as exc:
            self.logger.error(f"Error in _handle_info_message: {exc}")

    # --------------------------------------------------------------------------
    # Our controller, the radio stream, and setpoint confirmation (1.11.0)
    # --------------------------------------------------------------------------

    def _controller_from_zone_devices(self):
        """The controller every zone device already names, or "" if they disagree or
        none does. Seeds the learned controller on an install that predates 1.11.0,
        so the first controller heard after an upgrade never gets to decide."""
        seen = set()
        with self.zone_lock:
            dev_ids = list(self.zone_devices.values())
        for dev_id in dev_ids:
            try:
                cid = str(indigo.devices[dev_id].states.get("zoneControllerId", "")).strip()
            except Exception:
                continue
            if cid.startswith("01:"):
                seen.add(cid)
        if len(seen) == 1:
            cid = seen.pop()
            with self.pending_lock:
                self.pending_controller_id = cid
            return cid
        return ""

    def _zone_frame_controller(self, fields):
        """The sender, when a zone frame was SENT by our controller; "" otherwise.

        MQTT thread. A frame from another controller is a neighbour's system and is
        ignored, mentioned once per controller. With no controller known yet, the first
        one heard becomes ours and is saved to the prefs by the main thread."""
        src = controller_source(fields)
        if not src:
            return ""
        if not self.controller_id:
            self.controller_id = src
            with self.pending_lock:
                self.pending_controller_id = src
            return src
        if src != self.controller_id:
            if src not in self._foreign_controllers:
                self._foreign_controllers.add(src)
                self.logger.info(
                    f"Another Evohome controller ({src}) is in radio range - its "
                    f"messages are ignored; ours is {self.controller_id}"
                )
            return ""
        return src

    def _persist_controller_id(self, cid):
        """Save the learned controller to the prefs. Main thread only."""
        try:
            prefs = self.pluginPrefs
            if prefs.get("controller_id") == cid:
                return
            prefs["controller_id"] = cid
            self.pluginPrefs = prefs
            self.logger.info(f"Evohome controller {cid} saved; other controllers are ignored")
        except Exception as exc:
            self.logger.warning(f"Could not save controller ID to prefs: {exc}")

    def _note_rx(self, now):
        """A radio message arrived. MQTT thread. Ends a deaf spell if there was one."""
        self._last_rx_time = now
        if not self.gateway_deaf:
            return
        with self.pending_lock:
            if not self.gateway_deaf:
                return
            self.gateway_deaf = False
            self.gateway_offline_since = None
            if self.gateway_alert_sent:
                self.pending_gateway_alert = "restored"
                self.gateway_alert_sent    = False
        self.logger.info("Radio messages are arriving from the gateway again")

    @staticmethod
    def _gateway_is_deaf(now, connected, online, subscribed, last_rx, listen_since,
                         limit=GATEWAY_DEAF_SECONDS):
        """True when the gateway says it is online and we are listening, but nothing
        has arrived for longer than the limit. Only a gateway that claims to be online
        can be deaf: an offline one is already handled by its last will."""
        if not (connected and online is True and subscribed):
            return False
        return now - max(last_rx, listen_since) > limit

    def _check_gateway_deaf(self, now):
        """Main thread. Declare the gateway deaf once, and arm the offline alert and the
        power-cycle watchdog through gateway_offline_since, exactly as a last will does."""
        with self.pending_lock:
            online = self.gateway_online
            if self.gateway_deaf:
                if self.gateway_offline_since is None:
                    self.gateway_offline_since = now
                return
        if not self._gateway_is_deaf(now, self.mqtt_connected, online,
                                     self.gateway_subscribed, self._last_rx_time,
                                     self._rx_listen_since):
            return
        quiet = now - max(self._last_rx_time, self._rx_listen_since)
        with self.pending_lock:
            self.gateway_deaf = True
            if self.gateway_offline_since is None:
                self.gateway_offline_since = now
        self.logger.warning(
            f"The gateway says it is online but has passed on no radio messages for "
            f"{quiet / 60:.0f} minutes, so it is being treated as offline. Evohome cannot "
            f"be sent anything until messages arrive again."
        )
        # Cheap, and rules out our own subscription having been lost.
        self._resubscribe_to_gateway()

    def _note_setpoint_sent(self, zone_idx, setpoint_c, now, until=None):
        """Record a command waiting for the controller to report it. A new value for
        the zone replaces the old one; a repeat of the same value counts as a resend.
        A temporary override keeps its end time, so a resend is the same command.
        The sent log keeps the whole command (1.17.0), so a change at the same
        temperature but a different mode or end time is not mistaken for ours."""
        self._sent_log[zone_idx] = (setpoint_c, now, until)
        with self.pending_lock:
            rec = self.pending_setpoints.get(zone_idx)
            if rec and abs(rec["sp"] - setpoint_c) < 0.01 and rec.get("until") == until:
                rec["last"]  = now
                rec["sends"] += 1
            else:
                self.pending_setpoints[zone_idx] = {
                    "sp": setpoint_c, "first": now, "last": now, "sends": 1, "until": until,
                    "sp_ok": False}

    @staticmethod
    def _command_mode(until):
        """The zone mode and end time ("YYYY-MM-DD HH:MM", or "") the controller reports
        once it has taken a command: temporary with that end, or permanent with none."""
        if until is None:
            return ZONE_MODE_NAMES[ZONE_MODE_PERMANENT], ""
        return ZONE_MODE_NAMES[ZONE_MODE_TEMPORARY], until.strftime("%Y-%m-%d %H:%M")

    @staticmethod
    def _heard_after(rec, data, key="rx"):
        """A report counts only when it was heard after the command first left. A frame
        heard earlier can still be waiting in pending_updates when the command goes.
        "rx" stamps a 2349 (mode) frame, "sp_rx" a 2309 (setpoint) frame."""
        rx = data.get(key) if data else None
        return rx is None or rx >= rec["first"]

    def _confirm_setpoint(self, zone_idx, reported_c, data=None):
        """The controller's 2309 reported this zone's setpoint. That carries the
        temperature only, so it confirms the temperature only: the command stays
        pending until a 2349 reports the same mode and end time (1.17.0). EvoHomeControl
        renews a timed setting at the same temperature, and the 2309 broadcast used to
        clear a renewal that had never landed."""
        with self.pending_lock:
            rec = self.pending_setpoints.get(zone_idx)
            if not rec or abs(rec["sp"] - reported_c) >= SETPOINT_MATCH_C:
                return
            if not self._heard_after(rec, data, "sp_rx"):
                return
            rec["sp_ok"] = True
        self.logger.debug(f"Zone {zone_idx}: controller reports {reported_c:.1f} degC; "
                          f"waiting for its zone mode report")

    def _confirm_mode(self, zone_idx, data):
        """The controller's 2349 reported this zone's mode: clear the pending command
        when it reports the same command back - mode and end time always, and the
        temperature too, or a 2309 since the command has already reported it."""
        with self.pending_lock:
            rec = self.pending_setpoints.get(zone_idx)
            if not rec or not self._heard_after(rec, data):
                return
            want_mode, want_until = self._command_mode(rec.get("until"))
            if data.get("mode") != want_mode or (data.get("until") or "") != want_until:
                return
            reported = data.get("setpoint")
            if reported is None:
                if not rec.get("sp_ok"):
                    return
            elif abs(rec["sp"] - reported) >= SETPOINT_MATCH_C:
                return
            del self.pending_setpoints[zone_idx]
        self.logger.debug(f"Zone {zone_idx}: controller confirmed {rec['sp']:.1f} degC, "
                          f"{want_mode}{' until ' + want_until if want_until else ''}")

    def _retry_setpoints(self, now):
        """Main thread. Resend an unconfirmed command, give up on one that never takes,
        and forget one left over from a long outage (the caller will send afresh)."""
        with self.pending_lock:
            items = {z: dict(r) for z, r in self.pending_setpoints.items()}
            usable = self.gateway_online is not False and not self.gateway_deaf
        for zone_idx, rec in items.items():
            age = now - rec["first"]
            if age >= SETPOINT_FORGET_SECONDS:
                with self.pending_lock:
                    self.pending_setpoints.pop(zone_idx, None)
                self.logger.debug(f"Zone {zone_idx}: unconfirmed setpoint forgotten")
                continue
            if not usable or not self.mqtt_connected:
                continue
            if rec["sends"] < SETPOINT_MAX_SENDS:
                if now - rec["last"] >= SETPOINT_RESEND_SECONDS:
                    if self._publish_setpoint(zone_idx, rec["sp"], rec.get("until")):
                        self._note_setpoint_sent(zone_idx, rec["sp"], now, rec.get("until"))
                        self.logger.debug(f"Zone {zone_idx}: setpoint resent "
                                          f"(attempt {rec['sends'] + 1})")
                continue
            if age >= SETPOINT_GIVE_UP_SECONDS:
                with self.pending_lock:
                    self.pending_setpoints.pop(zone_idx, None)
                dev = self._find_zone_device(zone_idx)
                name = dev.name if dev is not None else f"Zone {zone_idx}"
                self.logger.warning(
                    f"Evohome has not confirmed {rec['sp']:.1f} degC for '{name}' after "
                    f"{rec['sends']} attempts over {age / 60:.0f} minutes. The controller "
                    f"may not have received it."
                )

    def _set_gateway_id(self, gw_id):
        """Store gateway ID and queue persist to prefs (done by main thread). Subscribe to rx."""
        self.gateway_id = gw_id

        # Queue prefs write for the main thread - writing pluginPrefs from the MQTT
        # callback thread triggers closedPrefsConfigUi which disconnects MQTT.
        with self.pending_lock:
            self.pending_gateway_id = gw_id

        self._resubscribe_to_gateway()

    def _persist_gateway_id(self, gw_id):
        """Save gateway ID to plugin prefs. Called from main thread only."""
        try:
            prefs = self.pluginPrefs
            prefs["discovered_gateway_id"] = gw_id
            self.pluginPrefs = prefs
            self.logger.info(f"Gateway ID saved to plugin prefs: {gw_id}")
        except Exception as exc:
            self.logger.warning(f"Could not save gateway ID to prefs: {exc}")

    def _resubscribe_to_gateway(self):
        """Subscribe to RAMSES/GATEWAY/<gw_id>/rx once gateway ID is known."""
        if not self.gateway_id or not self.mqtt_connected:
            return

        rx_topic = f"{RAMSES_ROOT}/{self.gateway_id}/rx"
        try:
            with self.mqtt_lock:
                if self.mqtt_client is not None:
                    self.mqtt_client.subscribe(rx_topic, qos=0)
                    self.gateway_subscribed = True
                    self._rx_listen_since = time.time()
                    self.logger.debug(f"Subscribed to {rx_topic}")
        except Exception as exc:
            self.logger.error(f"Failed to subscribe to {rx_topic}: {exc}")

    # --------------------------------------------------------------------------
    # RAMSES-II Message Parsing
    # --------------------------------------------------------------------------

    def _handle_rx_message(self, json_str):
        """Parse JSON payload from rx topic and dispatch RAMSES message."""
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as exc:
            self.logger.warning(f"Invalid JSON on rx topic: {exc}")
            return

        msg_str = data.get("msg", "").strip()
        ts      = data.get("ts", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        if not msg_str:
            return

        self._note_rx(time.time())

        self._parse_ramses_message(msg_str, ts)

    def _parse_ramses_message(self, msg_str, ts):
        """
        Parse RAMSES-II message string and dispatch to opcode handlers.

        Message format (9+ whitespace-separated fields):
          [0]  aaa    = RSSI or '---'
          [1]  XX     = verb: 'I', 'RQ', 'RP', 'W'
          [2]  bbb    = sequence '---'
          [3]  DEV1   = device address e.g. '01:123456'
          [4]  DEV2   = device address or '--:------'
          [5]  DEV3   = device address or '--:------'
          [6]  CODE   = 4-char hex opcode e.g. '30C9'
          [7]  nnn    = payload length (decimal bytes)
          [8]  PAYLOAD = hex-encoded payload string
        """
        try:
            fields = msg_str.split()
            if len(fields) < 9:
                if self.debug:
                    self.logger.debug(f"Short RAMSES msg ({len(fields)} fields): {msg_str}")
                return

            verb        = fields[1].strip()
            opcode      = fields[6].strip().upper()
            payload_hex = fields[8].strip().upper() if len(fields) > 8 else ""

            # Only process informational and reply messages
            if verb not in ("I", "RP"):
                return

            if self.debug:
                self.logger.debug(
                    f"RAMSES: verb={verb} opcode={opcode} "
                    f"len={fields[7]} payload={payload_hex[:40]}"
                )

            # Every packet a VALVE sends is evidence it is alive, whatever it says.
            # Done before the opcode dispatch so an opcode this plugin does not decode
            # still counts — liveness is about the sender, not the subject.
            self._note_trv_packet(fields, payload_hex, opcode)
            # Same principle for the boiler relay, and the controller's boiler demand.
            self._note_relay_packet(fields, payload_hex, opcode)

            if opcode == OPCODE_ZONE_NAME:
                self._parse_opcode_0004(fields, payload_hex, ts)
            elif opcode == OPCODE_ZONE_TEMP:
                self._parse_opcode_30c9(fields, payload_hex, ts)
            elif opcode == OPCODE_ZONE_SETPOINT:
                self._parse_opcode_2309(fields, payload_hex, ts)
            elif opcode == OPCODE_ZONE_MODE:
                self._parse_opcode_2349(fields, payload_hex, ts)
            elif opcode == timetable.OPCODE_TIMETABLE and verb == "RP":
                self._note_timetable_reply(fields, payload_hex)

        except ValueError as exc:
            # A garbled radio frame (a payload that is not hex) is weather, not a fault:
            # it used to log in red and reach the error watch.
            self.logger.debug(f"Unreadable RAMSES message '{msg_str[:80]}': {exc}")
        except Exception as exc:
            self.logger.error(
                f"Error parsing RAMSES message '{msg_str[:80]}': {exc}"
            )

    def _note_trv_packet(self, fields, payload_hex, opcode):
        """Record a valve as alive, and its battery when the packet carries one.

        Runs on the MQTT thread, so it touches nothing but the registry behind its own
        lock — no Indigo call may be made from here. Wrapped whole: liveness is a
        reporting nicety and must never cost the heating decode that follows it.
        """
        try:
            addr = trv_source(fields)
            if addr is None:
                return
            # A valve talking to ANOTHER controller is a neighbour's valve.
            dests = [f.strip() for f in fields[4:6] if f.strip().startswith("01:")]
            if self.controller_id and dests and self.controller_id not in dests:
                return
            zone = trv_zone_from_fields(fields, payload_hex, MAX_ZONES)
            pct = low = None
            if opcode == OPCODE_BATTERY:
                decoded = parse_battery(payload_hex)
                if decoded is None:
                    self.logger.debug(f"1060 from {addr}: unreadable payload {payload_hex}")
                else:
                    pct, low = decoded
                    self.logger.debug(f"1060: {addr} battery={pct} low={low}")
            with self.trv_lock:
                self.trv.record(addr, time.time(), zone=zone,
                                battery_pct=pct, battery_low=low)
                self._trv_state_dirty = True
        except Exception as exc:
            self.logger.debug(f"Could not note TRV packet: {exc}")

    def _note_relay_packet(self, fields, payload_hex, opcode):
        """Record what the boiler relay and the controller said about the boiler.

        MQTT thread: touches only relay_heard / boiler_demand, under relay_lock, and makes
        no Indigo call. Any packet from a relay proves it is alive; only a 3EF0 says
        whether it is closed. Wrapped whole so it can never cost the zone decode.
        """
        try:
            now = time.time()
            addr = relay_source(fields)
            if addr is not None and addr in self.ignored_relays:
                return
            if addr is not None:
                level = parse_relay_state(payload_hex) if opcode == OPCODE_ACTUATOR_STATE else None
                with self.relay_lock:
                    rec = self.relay_heard.setdefault(
                        addr, {"heard": None, "level": None, "level_ts": None})
                    rec["heard"] = now
                    if level is not None:
                        rec["level"] = level
                        rec["level_ts"] = now
                if opcode == OPCODE_ACTUATOR_STATE:
                    self.logger.debug(f"3EF0: relay {addr} level={level} ({payload_hex})")
                return
            ctrl = controller_source(fields)
            if (ctrl and opcode in (OPCODE_HEAT_DEMAND, OPCODE_RELAY_DEMAND)
                    and (not self.controller_id or ctrl == self.controller_id)):
                pct = parse_boiler_demand(payload_hex)
                if pct is None:
                    return
                key = "heat" if opcode == OPCODE_HEAT_DEMAND else "relay"
                with self.relay_lock:
                    self.boiler_demand[key] = pct
                self.logger.debug(f"{opcode}: boiler {key} demand {pct}%")
        except Exception as exc:
            self.logger.debug(f"Could not note relay packet: {exc}")

    def _parse_temp_bytes(self, payload_hex, byte_offset):
        """
        Extract a 16-bit big-endian signed temperature from payload_hex.

        Args:
            payload_hex:  hex string (2 chars per byte)
            byte_offset:  byte index (0-based) of the 2-byte temperature value

        Returns:
            float temperature in degrees C, or None if payload too short or value unknown (0x7FFF)
        """
        hex_start = byte_offset * 2
        if len(payload_hex) < hex_start + 4:
            return None

        raw_hex = payload_hex[hex_start : hex_start + 4]
        raw_int = int(raw_hex, 16)

        if raw_int == TEMP_UNKNOWN_RAW:
            return None

        # Convert to signed 16-bit
        if raw_int >= 0x8000:
            raw_int -= 0x10000

        return raw_int / TEMP_SCALE

    def _extract_controller_id(self, fields):
        """
        Find the Evohome controller address in DEV1/DEV2/DEV3 message fields.
        Controller device class is '01' (Evohome controller / system manager).
        """
        for field in fields[3:6]:
            if field.startswith("01:") and field != "--:------":
                return field
        return ""

    def _parse_opcode_30c9(self, fields, payload_hex, ts):
        """
        30C9 - Zone temperatures.
        Payload: repeating 3-byte blocks - [zone_idx(1 byte)][temp_degC(2 bytes)]
        A single message may contain multiple zones.

        Temperature source priority:
        - Controller-sourced 30C9 (controller_id non-empty, i.e. contains '01:xxxxxx'):
          The Evohome controller broadcasts I 30C9 036 every ~60 s covering all 12 zones.
          It reports the DESIGNATED zone-thermostat TRV's reading for each zone —
          one authoritative temperature per zone.  Always accepted.
        - TRV-sourced 30C9 (controller_id empty, packet from individual 04:xxxxxx device):
          Each TRV in a zone broadcasts its own local temperature independently.
          In multi-TRV zones these readings can differ significantly (e.g. one TRV in direct
          sunlight vs. one on a cold wall).  Accepting them causes temperatureInput1 to
          oscillate between TRVs, triggering spurious overheat detections every minute.
          IGNORED — only the controller's aggregated view is used.
        """
        controller_id = self._zone_frame_controller(fields)
        block_count   = len(payload_hex) // 6   # 3 bytes = 6 hex chars per block

        # Only the controller's own broadcast counts. A valve's 30C9 is ignored even
        # when it is addressed TO the controller, which the old check let through.
        if not controller_id:
            if self.debug:
                self.logger.debug("30C9: not sent by our controller - ignored")
            return

        for i in range(block_count):
            block_start = i * 6
            if len(payload_hex) < block_start + 6:
                break

            zone_idx = int(payload_hex[block_start : block_start + 2], 16)
            if zone_idx >= MAX_ZONES:
                continue   # domain code (0xF9/FA/FC etc.), not a real zone — never auto-create
            temp_c   = self._parse_temp_bytes(payload_hex, i * 3 + 1)

            if temp_c is None:
                continue

            if self.debug:
                self.logger.debug(f"30C9: Zone {zone_idx} = {temp_c:.2f}degC")

            with self.pending_lock:
                if zone_idx not in self.pending_updates:
                    self.pending_updates[zone_idx] = {}
                self.pending_updates[zone_idx]["temp"]          = temp_c
                self.pending_updates[zone_idx]["controller_id"] = controller_id
                self.pending_updates[zone_idx]["ts"]            = ts

    def _parse_opcode_2309(self, fields, payload_hex, ts):
        """
        2309 - Zone setpoints.
        Payload: same 3-byte block structure as 30C9.

        Only the controller's broadcast is taken. The valves send 2309 to the
        controller as well (captured 28-09-2026: I --- 04:254001 --:------ 01:091567
        2309 003 040320), reporting what THEY hold - which, just after a change, is the
        old value. Until 1.11.0 those flicked setpointHeat back to it.
        """
        controller_id = self._zone_frame_controller(fields)
        if not controller_id:
            return
        block_count   = len(payload_hex) // 6

        for i in range(block_count):
            block_start = i * 6
            if len(payload_hex) < block_start + 6:
                break

            zone_idx   = int(payload_hex[block_start : block_start + 2], 16)
            if zone_idx >= MAX_ZONES:
                continue   # domain code (0xF9/FA/FC etc.), not a real zone — never auto-create
            setpoint_c = self._parse_temp_bytes(payload_hex, i * 3 + 1)

            if setpoint_c is None:
                continue

            if self.debug:
                self.logger.debug(f"2309: Zone {zone_idx} setpoint = {setpoint_c:.2f}degC")

            with self.pending_lock:
                if zone_idx not in self.pending_updates:
                    self.pending_updates[zone_idx] = {}
                self.pending_updates[zone_idx]["setpoint"]      = setpoint_c
                self.pending_updates[zone_idx]["controller_id"] = controller_id
                self.pending_updates[zone_idx]["ts"]            = ts
                self.pending_updates[zone_idx]["sp_rx"]         = time.time()

    def _parse_opcode_2349(self, fields, payload_hex, ts):
        """
        2349 - Zone mode / override. Single zone per message (7+ bytes):
          byte 0:   zone_idx
          bytes 1-2: setpoint (same encoding as 30C9/2309)
          byte 3:   mode code (0x00=schedule, 0x02=permanent override, others)
          bytes 4+: mode-specific (until datetime - not needed for v1.0)
        """
        if len(payload_hex) < 8:   # need at least 4 bytes = 8 hex chars
            return

        controller_id = self._zone_frame_controller(fields)
        if not controller_id:
            return

        zone_idx   = int(payload_hex[0:2], 16)
        if zone_idx >= MAX_ZONES:
            return   # domain code (0xF9/FA/FC etc.), not a real zone — never auto-create
        setpoint_c = self._parse_temp_bytes(payload_hex, 1)
        mode_byte  = int(payload_hex[6:8], 16)    # byte 3 = hex chars 6-7

        mode_str = ZONE_MODE_NAMES.get(mode_byte, f"mode 0x{mode_byte:02X}")
        # A 13-byte 2349 carries the time a temporary override ends; every other mode
        # has none, which clears a time left from an earlier override.
        until_str = self._decode_2349_until(payload_hex) if mode_byte == ZONE_MODE_TEMPORARY else ""

        if self.debug:
            sp_disp = f"{setpoint_c:.2f}" if setpoint_c is not None else "unknown"
            self.logger.debug(
                f"2349: Zone {zone_idx} setpoint={sp_disp}degC mode={mode_str}"
            )

        with self.pending_lock:
            if zone_idx not in self.pending_updates:
                self.pending_updates[zone_idx] = {}
            # Only carry setpoint when it is KNOWN. An unknown setpoint (raw 0x7FFF) must not
            # clobber a valid setpointHeat with 0.0 — _apply_mode_update skips it when absent.
            if setpoint_c is not None:
                self.pending_updates[zone_idx]["setpoint"] = setpoint_c
            self.pending_updates[zone_idx]["mode"]          = mode_str
            self.pending_updates[zone_idx]["mode_byte"]     = mode_byte
            self.pending_updates[zone_idx]["until"]         = until_str
            self.pending_updates[zone_idx]["controller_id"] = controller_id
            self.pending_updates[zone_idx]["ts"]            = ts
            self.pending_updates[zone_idx]["rx"]            = time.time()

    def _parse_opcode_0004(self, fields, payload_hex, ts):
        """
        0004 - Zone name.

        Payload structure (variable length):
          byte 0:   zone_idx
          byte 1:   unknown / always 00
          bytes 2+: zone name, UTF-8 encoded, padded with 00 bytes to a fixed width (20 bytes total)

        The total payload is typically 22 bytes (44 hex chars):
          [zone_idx 1B][00 1B][name 20B]
        Name bytes after the first 0x00 are padding and should be stripped.

        Example:
          Payload: 00002C6F66666963650000000000000000000000000000
          zone_idx = 0x00 = 0
          padding  = 0x00
          name_hex = "2C6F666669636500..." -> decode -> "Living Room" (strip nulls)
        """
        if len(payload_hex) < 6:
            # Need at least zone_idx + padding + 1 char of name
            return
        if not self._zone_frame_controller(fields):
            return

        try:
            zone_idx = int(payload_hex[0:2], 16)

            # Name starts at byte 2 (hex offset 4), strip null bytes (padding).
            # Trim a trailing half-byte so an odd-length payload still decodes its valid
            # leading bytes instead of bytes.fromhex() raising and dropping the whole name.
            name_hex  = payload_hex[4:]
            if len(name_hex) % 2:
                name_hex = name_hex[:-1]
            raw_bytes = bytes.fromhex(name_hex)
            # Decode as UTF-8, strip null padding and whitespace
            name = raw_bytes.replace(b'\x00', b'').decode("utf-8", errors="replace").strip()

            if not name:
                if self.debug:
                    self.logger.debug(f"0004: Zone {zone_idx} name is empty - skipping")
                return

            if self.debug:
                self.logger.debug(f"0004: Zone {zone_idx} name = '{name}'")

            with self.pending_lock:
                self.pending_zone_names[zone_idx] = name

        except Exception as exc:
            self.logger.warning(f"Error parsing opcode 0004 payload '{payload_hex}': {exc}")

    # --------------------------------------------------------------------------
    # Zone / Indigo Device Management  (main thread only)
    # --------------------------------------------------------------------------

    def _find_zone_device(self, zone_idx):
        """
        Return the Indigo device for zone_idx, or None.
        Checks in-memory index first; falls back to iterating devices if stale.
        """
        with self.zone_lock:
            if zone_idx in self.zone_devices:
                dev_id = self.zone_devices[zone_idx]
                try:
                    return indigo.devices[dev_id]
                except KeyError:
                    # Device was deleted by the user
                    del self.zone_devices[zone_idx]

        # Fallback: scan all plugin devices by address
        for dev in indigo.devices.iter(f"self.{DEVICE_TYPE_ID}"):
            try:
                if int(dev.address) == zone_idx:
                    with self.zone_lock:
                        self.zone_devices[zone_idx] = dev.id
                    return dev
            except (ValueError, Exception):
                pass

        return None

    def _create_zone_device(self, zone_idx, controller_id):
        """
        Create a new Indigo custom device for a zone. Main thread only.
        All zones are numbered sequentially; no DHW special-casing (Combi boiler system).
        """
        device_name = f"RAMSES Zone {zone_idx}"

        self.logger.info(
            f"Auto-creating zone device: '{device_name}' (zone_idx={zone_idx}, "
            f"controller={controller_id})"
        )

        try:
            folder_id = self._get_or_create_folder(DEVICE_FOLDER_NAME)
            new_dev = indigo.device.create(
                protocol=indigo.kProtocol.Plugin,
                address=str(zone_idx),
                name=device_name,
                deviceTypeId=DEVICE_TYPE_ID,
                folder=folder_id
            )

            ts_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._write_states(new_dev, [
                {"key": "temperatureInput1", "value": 0.0,          "uiValue": "0.00 degC"},
                {"key": "setpointHeat",      "value": 0.0,          "uiValue": "0.00 degC"},
                # hvacHeaterIsOn is NOT set here: it's a built-in thermostat state that Indigo
                # only creates after deviceStartComm() fires replacePluginPropsOnServer() to lock
                # the thermostat capability props.  Indigo defaults it to False automatically.
                {"key": "zoneMode",         "value": "schedule"},
                {"key": "zoneControllerId","value": controller_id},
                {"key": "zoneName",         "value": ""},
                {"key": "lastSeen",         "value": ts_now},
                {"key": "online",            "value": "true"},
            ])

            with self.zone_lock:
                self.zone_devices[zone_idx] = new_dev.id

            self.logger.info(f"Created '{device_name}' (Indigo dev ID {new_dev.id})")
            return new_dev

        except Exception as exc:
            self.logger.error(f"Failed to create device for Zone {zone_idx}: {exc}")
            return None

    def _apply_temp_update(self, zone_idx, data):
        """Update temperatureInput1 (built-in thermostat state). Creates device if not yet known."""
        dev = self._find_zone_device(zone_idx)
        if dev is None:
            dev = self._create_zone_device(zone_idx, data.get("controller_id", ""))
        if dev is None:
            return

        temp_c        = data["temp"]
        controller_id = data.get("controller_id", "")
        ts            = self._format_ts(data.get("ts", ""))
        ts_epoch      = self._ts_epoch(data.get("ts", ""))

        # hvacHeaterIsOn: True when zone temp is meaningfully below setpoint.
        # Used by HomeKit and other integrations to show the heating-active indicator.
        # 0.3 degC hysteresis prevents rapid toggling around the setpoint.
        try:
            setpoint   = float(dev.states.get("setpointHeat", 0.0))
            is_heating = temp_c < (setpoint - 0.3) if setpoint > SETPOINT_MIN_C else False
        except Exception:
            is_heating = False

        try:
            state_updates = [
                {"key": "temperatureInput1", "value": round(temp_c, 2),
                 "uiValue": f"{temp_c:.2f} degC"},
                {"key": "hvacOperationMode", "value": indigo.kHvacMode.Heat},
                {"key": "hvacHeaterIsOn",    "value": is_heating},
                {"key": "lastSeen",         "value": ts},
                # Only a temperature report moves this; setpoint and mode reports
                # move lastSeen alone, which kept a frozen reading looking fresh.
                {"key": "temperatureSeen",  "value": ts},
                # The same moment as seconds since the epoch (1.17.0). The text above is
                # local wall-clock time, which repeats an hour when the clocks go back.
                {"key": "temperatureSeenEpoch", "value": ts_epoch},
                {"key": "online",            "value": "true"},
            ]
            # Only update zoneControllerId if non-empty — direct TRV messages
            # (e.g. 04:xxxxxx --:------ 04:xxxxxx 30C9) carry no 01: controller
            # address and must not overwrite a valid stored ID with an empty string.
            if controller_id:
                state_updates.append({"key": "zoneControllerId", "value": controller_id})
            self._write_states(dev, state_updates)
            if self.debug:
                self.logger.debug(f"Zone {zone_idx} temp -> {temp_c:.2f}degC")
        except Exception as exc:
            self.logger.error(f"Error updating Zone {zone_idx} temp state: {exc}")

    def _apply_setpoint_update(self, zone_idx, data):
        """Update setpointHeat (built-in thermostat state). Creates device if not yet known.

        Called when a 2309 (setpoint-only) message arrives. Does NOT update zoneMode —
        a 2309 packet carries no mode information. The controller broadcasts I 2309 for all
        zones every ~60 s regardless of mode; inferring 'schedule' from it would overwrite
        a valid 'permanent override' state. zoneMode is updated ONLY from 2349 broadcasts.
        If a 2349 arrives in the same poll cycle, _apply_mode_update() runs instead.
        """
        dev = self._find_zone_device(zone_idx)
        if dev is None:
            dev = self._create_zone_device(zone_idx, data.get("controller_id", ""))
        if dev is None:
            return

        setpoint_c    = data["setpoint"]
        controller_id = data.get("controller_id", "")
        ts            = self._format_ts(data.get("ts", ""))
        self._confirm_setpoint(zone_idx, setpoint_c, data)

        try:
            state_updates = [
                {"key": "setpointHeat", "value": round(setpoint_c, 2),
                 "uiValue": f"{setpoint_c:.2f} degC"},
                {"key": "lastSeen",    "value": ts},
                {"key": "online",       "value": "true"},
            ]
            if controller_id:
                state_updates.append({"key": "zoneControllerId", "value": controller_id})
            self._write_states(dev, state_updates)
            if self.debug:
                self.logger.debug(f"Zone {zone_idx} setpoint -> {setpoint_c:.2f}degC")
        except Exception as exc:
            self.logger.error(f"Error updating Zone {zone_idx} setpoint state: {exc}")

    @staticmethod
    def _change_source(new_setpoint, new_mode, sent, now, new_until=""):
        """Who made a change the controller has just reported: this plugin, the
        timetable, or someone outside Indigo.

        Ours only when the temperature, the mode AND the end time all match a command
        sent within the window (1.17.0). Matching the temperature alone called a person
        who held a room for good at the temperature Indigo had just set "indigo", and
        EvoHomeControl then overwrote them."""
        if sent is not None and new_setpoint is not None:
            sent_sp, sent_ts, sent_until = (tuple(sent) + (None,))[:3]
            want_mode, want_until = Plugin._command_mode(sent_until)
            if (abs(sent_sp - new_setpoint) < SETPOINT_MATCH_C
                    and now - sent_ts <= SOURCE_WINDOW_SECONDS
                    and new_mode == want_mode
                    and (new_until or "") == want_until):
                return SOURCE_INDIGO
        if new_mode == "schedule":
            return SOURCE_TIMETABLE
        return SOURCE_MANUAL

    def _source_states(self, dev, zone_idx, data):
        """The setpointSource / setpointChangedAt states for a 2349 that changes what
        the zone is doing, or [] when it only repeats what the device already shows."""
        new_mode = data.get("mode", "schedule")
        new_sp   = data.get("setpoint")
        new_end  = data.get("until", "")
        try:
            old_sp = float(dev.states.get("setpointHeat", ""))
        except (TypeError, ValueError):
            old_sp = None
        changed = (new_mode != dev.states.get("zoneMode", "")
                   or new_end != (dev.states.get("zoneOverrideUntil", "") or "")
                   or (new_sp is not None and (old_sp is None or abs(new_sp - old_sp) > 0.05)))
        if not changed:
            return []
        source = self._change_source(new_sp, new_mode, self._sent_log.get(zone_idx), time.time(),
                                     new_end)
        if source == SOURCE_MANUAL:
            if new_mode == "permanent override":
                how = "until it is changed back"
            elif new_end:
                try:
                    how = "until " + timetable.clock(
                        int(new_end[11:13]) * 60 + int(new_end[14:16]))
                except (ValueError, IndexError):
                    how = "for now"
            else:
                how = "until the next timetable change"
            what = f"{new_sp:g} degrees" if new_sp is not None else f"'{new_mode}'"
            self.logger.info(f"{dev.name} was set to {what} {how} from outside Indigo "
                             f"(the Evohome controller, the valve or the app).")
        return [{"key": "setpointSource",    "value": source},
                {"key": "setpointChangedAt", "value": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}]

    def _apply_mode_update(self, zone_idx, data):
        """Update zoneMode (and setpointHeat when known) from a 2349 message.

        A 2349 with an unknown setpoint (raw 0x7FFF) carries no 'setpoint' key, so only
        zoneMode is updated and the last-known setpointHeat is left untouched."""
        dev = self._find_zone_device(zone_idx)
        if dev is None:
            dev = self._create_zone_device(zone_idx, data.get("controller_id", ""))
        if dev is None:
            return

        mode_str      = data.get("mode", "schedule")
        controller_id = data.get("controller_id", "")
        ts            = self._format_ts(data.get("ts", ""))

        try:
            source_updates = self._source_states(dev, zone_idx, data)
            state_updates = source_updates + [
                {"key": "zoneMode",  "value": mode_str},
                {"key": "zoneOverrideUntil", "value": data.get("until", "")},
                {"key": "lastSeen", "value": ts},
                {"key": "online",    "value": "true"},
            ]
            self._confirm_mode(zone_idx, data)
            if "setpoint" in data:
                setpoint_c = data["setpoint"]
                state_updates.insert(0, {"key": "setpointHeat", "value": round(setpoint_c, 2),
                                         "uiValue": f"{setpoint_c:.2f} degC"})
            if controller_id:
                state_updates.append({"key": "zoneControllerId", "value": controller_id})
            self._write_states(dev, state_updates)
            if self.debug:
                self.logger.debug(f"Zone {zone_idx} mode -> {mode_str}")
        except Exception as exc:
            self.logger.error(f"Error updating Zone {zone_idx} mode state: {exc}")

    def _apply_offline_update(self, zone_idx):
        """Mark a zone device offline after an MQTT disconnect.

        Clears hvacHeaterIsOn so HomeKit (and other integrations) don't show a dead zone as
        actively heating, and leaves lastSeen as the last REAL timestamp — the online=false
        state already conveys the drop, so lastSeen is not overwritten with status text."""
        dev = self._find_zone_device(zone_idx)
        if dev is None:
            return
        try:
            self._write_states(dev, [
                {"key": "online",         "value": "false"},
                {"key": "hvacHeaterIsOn", "value": False},
            ])
        except Exception as exc:
            self.logger.error(f"Error setting Zone {zone_idx} offline: {exc}")

    def _write_states(self, dev, states):
        """Write a batch of states WITHOUT touching the device's error state.

        Indigo's state writes clear a device's error by default. The only error this
        plugin sets is "valve silent", owned by _write_trv_states, and a routine zone
        write — a controller temperature broadcast about once a minute — used to wipe it
        within the minute, so Device Health Monitor rarely saw it. Every write except the
        valve code's own setErrorStateOnServer now leaves the error alone.

        The official docs show clearErrorState only on the single-state
        updateStateOnServer. The batch call is tried with it first, because one batch is
        one SQL Logger row where single writes are one row each; if Indigo refuses the
        argument (TypeError), the states go one at a time through the documented form,
        and that choice is remembered.
        """
        if self._batch_keeps_error is not False:
            try:
                dev.updateStatesOnServer(states, clearErrorState=False)
                self._batch_keeps_error = True
                return
            except TypeError:
                if self._batch_keeps_error is True:
                    raise   # it has worked before, so this TypeError is a real fault
                self._batch_keeps_error = False
                self.logger.info(
                    "Indigo does not accept clearErrorState on a batch state write - "
                    "writing zone states one at a time so a valve error is kept"
                )
        for item in states:
            extra = {k: item[k] for k in ("uiValue", "decimalPlaces") if k in item}
            dev.updateStateOnServer(item["key"], item["value"],
                                    clearErrorState=False, **extra)

    @staticmethod
    def _gateway_status(mqtt_connected, gateway_online, deaf=False):
        """The gatewayStatus word from what we know. Our own broker link comes first:
        with it down nothing the gateway says can reach us, so any verdict is stale.
        A deaf gateway - connected, but passing on no radio messages - is offline for
        every purpose that matters."""
        if not mqtt_connected or gateway_online is None:
            return GATEWAY_STATUS_UNKNOWN
        if deaf:
            return GATEWAY_STATUS_OFFLINE
        return GATEWAY_STATUS_ONLINE if gateway_online else GATEWAY_STATUS_OFFLINE

    def _publish_gateway_status(self):
        """Write gatewayStatus to each zone device whose written value is out of date.

        Written with clearErrorState=False: a zone may be carrying the "valve silent"
        error that Device Health Monitor reads, and a gateway-status write must never
        be the thing that wipes it.
        """
        with self.pending_lock:
            gateway_online = self.gateway_online
            gateway_deaf   = self.gateway_deaf
        value = self._gateway_status(self.mqtt_connected, gateway_online, gateway_deaf)
        with self.zone_lock:
            dev_ids = list(self.zone_devices.values())
        for dev_id in dev_ids:
            if self._gw_status_written.get(dev_id) == value:
                continue
            try:
                dev = indigo.devices[dev_id]
            except KeyError:
                continue
            try:
                dev.updateStateOnServer("gatewayStatus", value, clearErrorState=False)
                self._gw_status_written[dev_id] = value
            except Exception as exc:
                self.logger.debug(f"Could not write gatewayStatus on '{dev.name}': {exc}")

    def _send_gateway_alert(self, status):
        """Send Pushover notification for gateway offline/restored. Called from main thread only."""
        if status == "offline":
            title    = "RAMSES Gateway Offline"
            message  = (f"RAMSES ESP gateway {self.gateway_id or 'unknown'} has gone offline"
                        f" — Evohome radiator control suspended")
            priority = "1"   # high
        else:
            title    = "RAMSES Gateway Restored"
            message  = f"RAMSES ESP gateway {self.gateway_id or 'unknown'} is back online"
            priority = "0"   # normal
        try:
            pushover = indigo.server.getPlugin("io.thechad.indigoplugin.pushover")
            if pushover and pushover.isEnabled():
                pushover.executeAction("send", props={
                    "msgTitle":    title,
                    "msgBody":     message,
                    "msgPriority": priority,
                    "msgSound":    "vibrate",   # vibrate only, no sound
                })
                self.logger.info(f"[Gateway] Pushover sent: {title}")
            else:
                self.logger.warning(f"[Gateway] Pushover not enabled — alert not sent: {title}")
        except Exception as exc:
            self.logger.error(f"[Gateway] Pushover send failed: {exc}")

    def _watchdog_tick(self, offline_since):
        """Gateway power-cycle watchdog. Main thread only — called every main-loop pass.

        ramses_esp firmware stops retrying WiFi after a failed reconnect (upstream issue #27,
        unfixed as of 0.6.6c) so a stuck gateway can only be recovered by cutting its power.
        If the gateway has been offline longer than the configured threshold, power-cycle the
        smart plug that feeds it. Repeat cycles are spaced a full threshold apart and capped
        per day so a genuinely dead stick is not bounced forever.

        The OFF/ON now happens inside ONE tick (see _power_cycle_plug), so the plug is never
        left off across loop iterations — a reload or crash can no longer strand it powered
        down. The decision logic lives in the pure _watchdog_decision() so it can be tested.
        """
        now = time.time()
        decision = self._watchdog_decision(now, offline_since)
        if decision == "idle":
            return

        if decision == "giveup":
            if not self.wd_gave_up_alerted:
                self.wd_gave_up_alerted = True
                self.logger.warning(
                    f"[Watchdog] Gateway still offline but daily cycle cap "
                    f"({self.wd_max_cycles}) reached — manual attention needed"
                )
                self._send_watchdog_pushover(
                    "RAMSES watchdog giving up",
                    f"Gateway still offline after {self.wd_cycles_today} power "
                    f"cycle(s) today — it needs a human.",
                    priority="1",
                )
            return

        # decision == "cycle"
        dev = self._plug_device()
        if dev is None:
            self.logger.error(
                f"[Watchdog] Configured plug device {self.wd_plug_id} not found — "
                f"reselect it in Plugins -> RAMSES ESP -> Configure"
            )
            return

        mins = int((now - offline_since) // 60)

        # Spacing applies to every ATTEMPT, cycled or not, so a plug we cannot reach is
        # retried on the normal schedule instead of every main-loop pass.
        self.wd_last_cycle_ts = now

        # The plug and the gateway are almost always on the same network. If the plug is
        # unreachable too, cutting its power is both impossible and beside the point — and
        # firing the command anyway risks the owning plugin delivering it late, switching the
        # gateway off at a moment nobody chose. Skip, and do not spend a cycle on it.
        unreachable = self._plug_unreachable_reason(dev)
        if unreachable:
            self._note_no_cycle(
                mins,
                f"its plug is unreachable ({unreachable}), so this looks like a network "
                f"fault rather than a stuck gateway",
            )
            self._persist_watchdog_state()
            return

        self._persist_watchdog_state()
        self.logger.warning(
            f"[Watchdog] Gateway offline {mins}m — power-cycling its plug "
            f"(off {self.wd_off_seconds}s, cycle #{self.wd_cycles_today + 1} of "
            f"{self.wd_max_cycles} today)"
        )

        # Only now is there anything to announce, and only if the plug actually moves.
        cycled = self._power_cycle_plug()
        if cycled is False:
            self._note_no_cycle(mins, "its plug never reported the switch, so no power was cut")
            self._persist_watchdog_state()
            return

        self.wd_cycles_today   += 1
        self.wd_no_cycle_streak = 0
        self._persist_watchdog_state()
        self._send_watchdog_pushover(
            "RAMSES watchdog power-cycled gateway",
            f"Gateway offline {mins}m — plug cycled "
            f"(#{self.wd_cycles_today} of {self.wd_max_cycles} today).",
        )

    def _note_no_cycle(self, mins, reason):
        """Record an attempt that did not cut power, and say so — once per outage.

        A cycle that never happened must not count against the daily cap: spending the budget
        on no-ops is what left the 19-Sep outage with three "cycles", none of them real, and a
        give-up alert asking for a human the gateway did not need. Warn on the first one so the
        reason is in the log, then stay quiet until the count reaches the cap, where ONE
        Pushover goes out naming the real problem.
        """
        self.wd_no_cycle_streak += 1
        if self.wd_no_cycle_streak == 1:
            self.logger.warning(f"[Watchdog] Gateway offline {mins}m but not cycling — {reason}")
        else:
            self.logger.debug(
                f"[Watchdog] Still not cycling (attempt {self.wd_no_cycle_streak}) — {reason}"
            )
        if self.wd_no_cycle_streak >= self.wd_max_cycles and not self.wd_no_cycle_alerted:
            self.wd_no_cycle_alerted = True
            self._send_watchdog_pushover(
                "RAMSES watchdog cannot cycle the plug",
                f"The gateway has been offline {mins} minutes and the watchdog has not been "
                f"able to power-cycle it: {reason}. No power has been cut.",
                priority="1",
            )

    def _watchdog_decision(self, now, offline_since):
        """Pure decision for the watchdog — returns 'idle' | 'cycle' | 'giveup'.

        Performs NO Indigo IO so it is unit-testable in isolation. It may roll the daily
        counter over to a new day and clears the give-up flag when the gateway is back online.
        """
        if not self.wd_enabled or not self.wd_plug_id:
            return "idle"
        if offline_since is None:
            # Gateway online — re-arm every per-outage latch for the next one.
            self.wd_gave_up_alerted  = False
            self.wd_no_cycle_alerted = False
            self.wd_no_cycle_streak  = 0
            return "idle"

        offline_secs = now - offline_since
        if offline_secs < self.wd_offline_minutes * 60:
            return "idle"
        # Space repeat cycles a full threshold apart (gives the gateway time to boot,
        # join WiFi and publish its LWT before we judge the cycle a failure).
        if now - self.wd_last_cycle_ts < self.wd_offline_minutes * 60:
            return "idle"

        today = time.strftime("%Y-%m-%d", time.localtime(now))
        if self.wd_cycle_day != today:
            self.wd_cycle_day    = today
            self.wd_cycles_today = 0
        if self.wd_cycles_today >= self.wd_max_cycles:
            return "giveup"
        return "cycle"

    def _plug_device(self):
        """The configured plug device, or None if it is not there. Main thread only."""
        try:
            return indigo.devices[self.wd_plug_id]
        except Exception:
            return None

    def _plug_unreachable_reason(self, dev):
        """Why the plug cannot be commanded right now, as a phrase — or "" if it can be.

        Deliberately generic: the plug could belong to any plugin, or to none, so nothing here
        keys on a plugin ID or a device name. It asks the three questions every Indigo device
        can answer, and treats only a definite NO as a reason. An absent state is not evidence
        of an offline plug, so the unknown case returns "" and the cycle goes ahead.
        """
        try:
            if getattr(dev, "enabled", None) is False:
                return "the device is disabled in Indigo"
            err = getattr(dev, "errorState", "")
            if isinstance(err, str) and err.strip():
                return f"Indigo reports '{err.strip()}'"
            # Most network-device plugins publish a reachability state. ShellyDirect and
            # several others call it deviceOnline; the v2 API can hand it back as the STRING
            # "False", which is truthy, so it goes through as_bool rather than bool().
            states = getattr(dev, "states", {}) or {}
            for key in ("deviceOnline", "online", "reachable"):
                if key in states:
                    if as_bool(states[key], default=True):
                        return ""
                    return f"its plugin reports {key}=False"
        except Exception as exc:
            self.logger.debug(f"[Watchdog] Could not read plug reachability: {exc}")
        return ""

    def _plug_is_on(self, dev=None):
        """True / False for the plug's own reported power state, or None if it does not say."""
        if dev is None:
            dev = self._plug_device()
        if dev is None:
            return None
        try:
            states = getattr(dev, "states", {}) or {}
            if "onOffState" in states:
                return self._scalar_bool(states["onOffState"])
            return self._scalar_bool(getattr(dev, "onState", None))
        except Exception as exc:
            self.logger.debug(f"[Watchdog] Could not read plug on/off state: {exc}")
        return None

    @staticmethod
    def _scalar_bool(value):
        """True / False for a real on-off value, None for anything that is not one.

        Only bool, int and str are an answer. Anything else — an absent attribute, a proxy
        object, a device that simply does not model on/off — is "cannot tell", and the caller
        must not read that as OFF. Getting this wrong turns an unanswerable question into a
        confident wrong answer, which is the whole fault this version exists to fix.
        """
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, str)):
            return as_bool(value, default=False)
        return None

    def _await_plug_state(self, want, seconds):
        """Wait for the plug to REPORT `want`. True confirmed, False did not, None cannot tell.

        The device object is re-fetched on every pass — a cached one would report the value it
        held when the cycle started and confirm anything asked of it.

        StopThread is swallowed rather than raised. This runs inside the restore path of a
        shutting-down plugin, where the plug is already back on and the real StopThread is
        halfway up the stack; a second one from here would replace it.
        """
        if self._plug_is_on() is None:
            return None                       # the plug does not report a state to wait for
        deadline = time.time() + max(0.0, float(seconds))
        while True:
            if self._plug_is_on() is want:
                return True
            if time.time() >= deadline:
                return False
            try:
                self.sleep(WD_VERIFY_POLL)
            except self.StopThread:
                self.logger.debug("[Watchdog] Shutting down mid-verify — state not confirmed")
                return None
            except Exception:
                return None

    def _power_cycle_plug(self):
        """Switch the gateway plug OFF, wait wd_off_seconds, then back ON — all within this one
        tick. Returns True if the plug was SEEN to switch off, False if it demonstrably did not,
        and None if it publishes no on/off state to check.

        A try/finally guarantees the plug is switched back ON even if self.sleep() raises
        StopThread (plugin shutting down mid-cycle), so the gateway is never stranded without
        power. Main thread only.

        turnOff()/turnOn() return without error whether or not the command reaches the plug, so
        the return value above comes from the plug's own reported state, never from the calls
        completing. See the note by WD_VERIFY_SECONDS.
        """
        if self._plug_is_on() is False:
            self.logger.warning(
                "[Watchdog] The plug is already OFF — the gateway has no power. "
                "Switching it back on."
            )
        try:
            indigo.device.turnOff(self.wd_plug_id)
        except Exception as exc:
            self.logger.error(f"[Watchdog] Failed to switch gateway plug off: {exc}")
            return False

        # Waiting for the OFF to be reported is part of the off-window, not extra to it.
        went_off = self._await_plug_state(False, WD_VERIFY_SECONDS)
        if went_off is False:
            self.logger.error(
                f"[Watchdog] The plug did not report switching off within "
                f"{WD_VERIFY_SECONDS:.0f}s — treating the command as lost, and NOT counting "
                f"this as a power cycle"
            )
        elif went_off is None:
            self.logger.info(
                f"[Watchdog] Gateway plug OFF for {self.wd_off_seconds}s "
                f"(it reports no on/off state, so this is unverified)"
            )
        else:
            self.logger.info(f"[Watchdog] Gateway plug OFF for {self.wd_off_seconds}s")

        if went_off is False:
            # The OFF never landed, so the plug still has power and there is nothing to wait
            # out or restore. Send one unverified ON anyway in case the command turns up late
            # at the owning plugin, and skip the alarm — power was never cut, so the gateway
            # is not stranded and this is not the emergency NEEDS HELP is for.
            try:
                indigo.device.turnOn(self.wd_plug_id)
            except Exception as exc:
                self.logger.debug(f"[Watchdog] Best-effort ON after a lost OFF failed: {exc}")
            return False

        try:
            self.sleep(self.wd_off_seconds)
        finally:
            # ALWAYS restore power, even if StopThread was raised during the sleep above.
            # Power IS cut at this point, so each attempt waits the full verification window:
            # a plug that will not come back on is exactly the emergency worth blocking the
            # main loop for.
            restored = False
            for attempt in range(1, 6):
                try:
                    indigo.device.turnOn(self.wd_plug_id)
                except Exception as exc:
                    self.logger.error(
                        f"[Watchdog] Failed to switch gateway plug back on "
                        f"(attempt {attempt}/5): {exc}"
                    )
                    continue
                if self._await_plug_state(True, WD_VERIFY_SECONDS) is False:
                    self.logger.error(
                        f"[Watchdog] The plug did not report switching back on "
                        f"(attempt {attempt}/5)"
                    )
                    continue
                self.logger.info("[Watchdog] Gateway plug back ON — gateway rebooting")
                restored = True
                break
            if not restored:
                self._send_watchdog_pushover(
                    "RAMSES watchdog NEEDS HELP",
                    "Could not switch the gateway plug back ON after a power cycle — the "
                    "gateway may be without power. Check the plug.",
                    priority="1",
                )
        return went_off

    def _persist_watchdog_state(self):
        """Persist the daily cycle counters so a graceful reload during an outage doesn't reset
        the per-day cap (and re-cycle the plug) or lose the cycle-spacing timer. (Indigo only
        flushes pluginPrefs on a clean shutdown, so this covers reloads, not hard crashes.)"""
        try:
            prefs = self.pluginPrefs
            prefs["wd_cycle_day"]     = self.wd_cycle_day
            prefs["wd_cycles_today"]  = str(self.wd_cycles_today)
            prefs["wd_last_cycle_ts"] = str(self.wd_last_cycle_ts)
            self.pluginPrefs = prefs
        except Exception as exc:
            self.logger.debug(f"[Watchdog] Could not persist watchdog state: {exc}")

    def _send_watchdog_pushover(self, title, message, priority="0"):
        """Pushover for watchdog events. Main thread only."""
        try:
            pushover = indigo.server.getPlugin("io.thechad.indigoplugin.pushover")
            if pushover and pushover.isEnabled():
                pushover.executeAction("send", props={
                    "msgTitle":    title,
                    "msgBody":     message,
                    "msgPriority": priority,
                    "msgSound":    "vibrate",
                })
                self.logger.info(f"[Watchdog] Pushover sent: {title}")
            else:
                self.logger.warning(f"[Watchdog] Pushover not enabled — alert not sent: {title}")
        except Exception as exc:
            self.logger.error(f"[Watchdog] Pushover send failed: {exc}")

    def _apply_zone_name_update(self, zone_idx, name):
        """
        Store zone name in device state and rename the Indigo device if it still has
        the auto-generated name (e.g. 'RAMSES Zone 3'). Main thread only.

        Renaming only happens once: if the user has already renamed the device manually
        we leave it alone. We detect the auto-generated name by checking whether it
        matches the pattern 'RAMSES Zone <N>'.
        """
        dev = self._find_zone_device(zone_idx)
        if dev is None:
            # Device may not exist yet (name arrived before first temp). Just log.
            if self.debug:
                self.logger.debug(
                    f"Zone {zone_idx} name '{name}' received but device not yet created - "
                    f"will apply when device is created"
                )
            return

        try:
            # Always store the zone name as a device state
            current_stored = dev.states.get("zoneName", "")
            if current_stored != name:
                self._write_states(dev, [{"key": "zoneName", "value": name}])
                self.logger.info(f"Zone {zone_idx} name state set to '{name}'")

            # Rename the Indigo device only if it still has the auto-generated name
            auto_name = f"RAMSES Zone {zone_idx}"
            if dev.name == auto_name:
                new_dev_name = f"RAMSES {name}"
                try:
                    dev.name = new_dev_name
                    dev.replaceOnServer()
                    self.logger.info(
                        f"Zone {zone_idx} device renamed: '{auto_name}' -> '{new_dev_name}'"
                    )
                except Exception as exc:
                    self.logger.warning(
                        f"Could not rename Zone {zone_idx} device to '{new_dev_name}': {exc}"
                    )
            elif self.debug:
                self.logger.debug(
                    f"Zone {zone_idx} device already named '{dev.name}' - not auto-renaming"
                )

        except Exception as exc:
            self.logger.error(f"Error applying zone name update for Zone {zone_idx}: {exc}")

    # --------------------------------------------------------------------------
    # TX / Command Publishing
    # --------------------------------------------------------------------------

    def _gateway_tx_topic(self):
        """Return the MQTT topic for sending commands to the RAMSES-ESP gateway."""
        return f"{RAMSES_ROOT}/{self.gateway_id}/tx"

    @staticmethod
    def _encode_2349_setpoint(zone_idx, setpoint_c, until=None):
        """Encode a W 2349 payload as a hex string.

        No until: the 7-byte permanent override - ZZ (zone) XXXX (setpoint*100, big-endian)
        02 (mode) FFFFFF (no countdown). Zone 1 @ 21.5 degC -> "01086602FFFFFF".

        With until (a local datetime): the 13-byte temporary override - the same with mode
        04, then the end time as minute, hour, day, month, year (big-endian 16-bit), the
        layout ramses_rf's ZoneMode13BPayload uses. Zone 7 @ 8.5 until 19:22 on
        28-09-2026 -> "07035204FFFFFF16131C0907EA", sent and honoured live.
        Pure + static so it can be unit-tested without a live gateway.
        """
        raw_setpoint = int(round(setpoint_c * TEMP_SCALE))
        raw_setpoint = max(0, min(raw_setpoint, TEMP_UNKNOWN_RAW - 1))
        if until is None:
            return f"{zone_idx:02X}{raw_setpoint:04X}{ZONE_MODE_PERMANENT:02X}FFFFFF"
        return (f"{zone_idx:02X}{raw_setpoint:04X}{ZONE_MODE_TEMPORARY:02X}FFFFFF"
                f"{until.minute:02X}{until.hour:02X}{until.day:02X}{until.month:02X}"
                f"{until.year:04X}")

    @staticmethod
    def _decode_2349_until(payload_hex):
        """The end time of a 13-byte 2349 as "YYYY-MM-DD HH:MM", or "" when the payload
        carries none (7 bytes, or an all-FF time)."""
        if not payload_hex or len(payload_hex) < 26:
            return ""
        dtm = payload_hex[14:26].upper()
        if dtm == "FFFFFFFFFFFF":
            return ""
        try:
            minute, hour = int(dtm[0:2], 16), int(dtm[2:4], 16) & 0x7F
            day, month, year = int(dtm[4:6], 16), int(dtm[6:8], 16), int(dtm[8:12], 16)
            return datetime(year, month, day, hour, minute).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return ""

    def _publish_setpoint(self, zone_idx, setpoint_c, until=None):
        """
        Publish a W 2349 permanent-override command to the gateway tx topic.

        RAMSES-II W 2349 permanent override format (7 bytes):
          W --- <gw_addr> <controller_id> --:------ 2349 007 ZZXXYYMMFFFFFF
        where:
          ZZ     = zone_idx as 2 hex chars
          XXYY   = setpoint * 100 as big-endian 16-bit hex (4 chars)
          MM     = mode byte: 0x02 = ZONE_MODE_PERMANENT
          FFFFFF = end datetime all-FF (indefinite, no expiry)

        Example: Zone 1, 21.5 degC -> setpoint * 100 = 2150 = 0x0866
          payload_hex = "010866 02FFFFFF"
          msg = "W --- 18:730 01:123456 --:------ 2349 007 01086602FFFFFF"

        Previously sent W 2309 (temporary override, 3 bytes) which allowed the
        Evohome schedule and EU cloud server to cancel setpoints at period
        boundaries. W 2349 permanent override prevents this (v1.2.0).
        """
        try:
            # Look up controller ID from the zone's device state
            dev = self._find_zone_device(zone_idx)
            if dev is None:
                self.logger.error(
                    f"Cannot publish setpoint - Zone {zone_idx} device not found"
                )
                return False

            controller_id = self.controller_id or dev.states.get("zoneControllerId", "")
            if not controller_id or not controller_id.startswith("01:"):
                self.logger.error(
                    f"Cannot publish setpoint for Zone {zone_idx} - "
                    f"no valid controller ID (got '{controller_id}'). "
                    f"Wait for a 30C9 or 2309 message to be received first."
                )
                return False

            # Encode the W 2349 permanent-override payload (zone + setpoint + mode + no expiry)
            payload_hex = self._encode_2349_setpoint(zone_idx, setpoint_c, until)
            length      = "013" if until is not None else "007"

            # Normalise gateway address format (wiki shows 18:730, but device may use 18-730)
            gw_addr = self.gateway_id.replace("-", ":")

            msg_str   = f"W --- {gw_addr} {controller_id} --:------ 2349 {length} {payload_hex}"
            tx_payload = json.dumps({"msg": msg_str})
            topic     = self._gateway_tx_topic()

            with self.mqtt_lock:
                if self.mqtt_client is None or not self.mqtt_connected:
                    self.logger.error(
                        f"Cannot publish setpoint for Zone {zone_idx} - MQTT not connected"
                    )
                    return False
                info = self.mqtt_client.publish(topic, tx_payload, qos=0)
            # paho returns MQTT_ERR_SUCCESS (0) once the message is queued; anything else
            # means it never left, which used to be ignored.
            rc = getattr(info, "rc", 0)
            if isinstance(rc, int) and rc != 0:
                self.logger.error(
                    f"Cannot publish setpoint for Zone {zone_idx} - the MQTT client "
                    f"refused it (code {rc})"
                )
                return False

            self.logger.debug(
                f"Zone {zone_idx}: W 2349 {setpoint_c:.1f}degC "
                f"{'until ' + until.strftime('%H:%M') if until else 'permanent override'} sent"
            )
            return True

        except Exception as exc:
            self.logger.error(
                f"Error publishing setpoint for Zone {zone_idx}: {exc}"
            )
            return False

    def _request_zone_names(self):
        """
        Send RQ 0004 for each zone to ask the controller to broadcast zone names.
        The controller responds with RP 0004 per zone, which is processed by
        _parse_opcode_0004() — populating the zoneName state on each device.
        Called once after MQTT connects when a controller_id is first available.

        Returns True if at least one RQ was sent; False if no controller_id yet.
        """
        # Find a valid controller_id from any zone device
        controller_id = ""
        for zone_idx in range(12):
            dev = self._find_zone_device(zone_idx)
            if dev:
                cid = dev.states.get("zoneControllerId", "")
                if cid.startswith("01:"):
                    controller_id = cid
                    break

        if not controller_id:
            if self.debug:
                self.logger.debug("RQ 0004: no controller_id available yet - will retry")
            return False

        success_count = 0
        for zone_idx in range(12):
            zone_hex = f"{zone_idx:02X}"
            gw_addr  = self.gateway_id.replace("-", ":")
            msg_str  = f"RQ --- {gw_addr} {controller_id} --:------ 0004 001 {zone_hex}"
            try:
                with self.mqtt_lock:
                    if self.mqtt_client and self.mqtt_connected:
                        topic = self._gateway_tx_topic()
                        self.mqtt_client.publish(topic, json.dumps({"msg": msg_str}), qos=0)
                        success_count += 1
            except Exception as exc:
                self.logger.warning(f"Error sending RQ 0004 for Zone {zone_idx}: {exc}")

        if success_count:
            self.logger.debug(
                f"Sent RQ 0004 for {success_count} zones to populate zoneName states"
            )
        return success_count > 0

    # --------------------------------------------------------------------------
    # Helpers
    # --------------------------------------------------------------------------

    def _get_or_create_folder(self, folder_name):
        """Return the Indigo device folder ID for folder_name, creating it if needed.
        Must be called from the main thread only."""
        for folder in indigo.devices.folders:
            if folder.name == folder_name:
                return folder.id
        self.logger.info(f"Creating device folder: '{folder_name}'")
        new_folder = indigo.devices.folder.create(folder_name)
        return new_folder.id

    @staticmethod
    def _sanitise_gateway_id(raw):
        """Return the first valid RAMSES gateway address (NN:NNNNNN) found in raw, or "".

        Handles the corruption where the id was typed several times with no separator, e.g.
        "18:20305218:203052" -> "18:203052" (the (?!\\d) keeps the segment NOT followed by a
        digit; ':' isn't a word char so \\b can't be used). Shared by _read_prefs and
        validatePrefsConfigUi so the two can never drift apart.
        """
        if not raw:
            return ""
        raw = raw.strip()
        if re.match(r'^\d{2}:\d{6}$', raw):
            return raw
        match = re.search(r'(\d{2}:\d{6})(?!\d)', raw)
        return match.group(1) if match else ""

    def _format_ts(self, ts_raw):
        """Convert an ISO 8601 gateway timestamp to a clean local datetime string.

        The RAMSES-ESP firmware timestamps the rx messages using its system clock.
        Until NTP synchronises successfully, the ESP32 defaults to Unix epoch (1970),
        so timestamps like "1970-01-01T05:42:17+00:00" are normal on first boot.
        Any timestamp before EPOCH_SENTINEL_YEAR is treated as invalid; a one-time
        warning is logged and the current local system time is substituted instead.

        Falls back to current local time if ts_raw cannot be parsed at all.
        """
        try:
            dt = datetime.fromisoformat(ts_raw)      # parse ISO 8601 (with tz offset)
            if dt.year < EPOCH_SENTINEL_YEAR:
                # Gateway NTP has not synced yet - ts is meaningless (epoch since boot)
                if not getattr(self, '_ntp_warn_logged', False):
                    self.logger.info(
                        f"Gateway timestamp is pre-NTP ({ts_raw[:19]}) - "
                        f"firmware NTP not synced. Using local time for lastSeen."
                    )
                    self._ntp_warn_logged = True
                return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # Valid timestamp - reset the warning flag for next time
            self._ntp_warn_logged = False
            return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _ts_epoch(ts_raw):
        """The gateway timestamp as whole seconds since the epoch, for a reader that
        needs an age it can trust across a clock change. Falls back to now exactly where
        _format_ts does: a pre-NTP (1970) time, or one that will not parse."""
        try:
            dt = datetime.fromisoformat(ts_raw)
            if dt.year < EPOCH_SENTINEL_YEAR:
                return int(time.time())
            return int(dt.timestamp())
        except Exception:
            return int(time.time())

    # --------------------------------------------------------------------------
    # Per-valve liveness + battery
    # --------------------------------------------------------------------------

    def _trv_state_path(self):
        """Where the per-valve record is kept. A FILE, not pluginPrefs.

        pluginPrefs are only flushed on a graceful shutdown, and this record is the
        difference between knowing a valve's battery straight after a restart and
        waiting hours for it to speak again — precisely the thing a hard crash would
        otherwise cost.
        """
        base = _os.path.join(indigo.server.getInstallFolderPath(),
                            "Preferences", "Plugins", self.pluginId)
        _os.makedirs(base, exist_ok=True)
        return _os.path.join(base, TRV_STATE_FILENAME)

    def _load_trv_state(self):
        try:
            with open(self._trv_state_path(), "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return
        try:
            with self.trv_lock:
                loaded = self.trv.load_dict(data)
            if loaded:
                self.logger.debug(f"  Restored {loaded} valve record(s)")
        except Exception as exc:
            self.logger.warning(f"Could not restore valve records: {exc}")

    def _save_trv_state(self):
        """Write the valve record atomically. A half-written file loses everything."""
        try:
            with self.trv_lock:
                data = self.trv.to_dict()
                self._trv_state_dirty = False
            path = self._trv_state_path()
            tmp  = f"{path}.tmp.{_os.getpid()}"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
                fh.flush()
                _os.fsync(fh.fileno())
            _os.replace(tmp, path)
        except Exception as exc:
            self.logger.debug(f"Could not save valve records: {exc}")

    def _publish_trv_states(self):
        """Push each zone's valve summary onto its device, only where it has changed.

        The zones covered are the UNION of what the registry has heard and what we hold
        a device for. Iterating known_zones() alone was a hole the exact shape of a dead
        valve: a valve that had already stopped transmitting before the plugin started
        listening never entered the registry, so its zone was never summarised, never
        written and could never set an error state. It kept the "unknown" that
        _seed_trv_states gives a new device, indefinitely, which reads as "no verdict
        yet" and is indistinguishable from a valve the gateway simply has not got round
        to hearing. Found 13-09-2026 on the Utility Room, 103 days after it died.

        zone_devices is copied rather than iterated: it is mutated from deviceStartComm
        on Indigo's dispatch thread and this runs on the worker.
        """
        now   = time.time()
        stale = self.trv_stale_hours * 3600.0
        with self.trv_lock:
            listened_long_enough = (now - self._trv_listening_since) > stale
            summaries = {z: self.trv.zone_summary(z, now, stale, self._trv_listening_since)
                         for z in sorted(self.trv.known_zones())}

        if self.trv_expect_every_zone:
            for zone in sorted(dict(self.zone_devices)):
                if summaries.get(zone) is None:
                    summaries[zone] = unheard_summary(listened_long_enough)

        for zone, summary in summaries.items():
            if summary is None or self._trv_published.get(zone) == summary:
                continue
            dev = self._find_zone_device(zone)
            if dev is None:
                continue
            try:
                self._write_trv_states(dev, summary, now)
                self._trv_published[zone] = dict(summary)
            except Exception as exc:
                self.logger.warning(f"Could not publish valve states for Zone {zone}: {exc}")

    def _write_trv_states(self, dev, summary, now):
        """Write one zone's valve states, then its error state.

        This is the ONLY code that sets or clears the zone's error. Every other state
        write goes through _write_states with clearErrorState=False (1.9.0), so the
        error now lasts until a valve verdict changes it. The error is still set last.
        """
        states = [
            {"key": "trvCount",   "value": summary["count"]},
            {"key": "trvIds",     "value": summary["addresses"]},
            {"key": "trvSummary", "value": describe(summary, now)},
        ]
        if summary["last_seen"]:
            states.append({"key": "trvLastSeen",
                           "value": datetime.fromtimestamp(summary["last_seen"])
                                            .strftime("%Y-%m-%d %H:%M:%S")})
        # Three-valued on purpose: "unknown" is a real answer and must not round to a
        # verdict either way. See the comment on these states in Devices.xml.
        states.append({"key": "trvStatus", "value": _liveness(summary["online"])})
        states.append({"key": "trvBatteryWarn", "value": _battery_warn(summary["battery_low"])})
        if summary["battery"] is None:
            states.append({"key": "trvBattery", "value": TRV_BATTERY_UNKNOWN,
                           "uiValue": "unknown"})
        else:
            states.append({"key": "trvBattery", "value": int(summary["battery"]),
                           "uiValue": f"{int(summary['battery'])}%"})
        self._write_states(dev, states)

        # Mirror into Indigo's OWN battery level so the device list, find_low_battery and
        # every notifier that reads it see the valve without knowing this plugin exists.
        # The CAPABILITY is claimed here rather than at device start, because declaring it
        # creates a native batteryLevel of 0 and a fleet of thermostats reporting a flat
        # battery is a worse fault than having no reading at all.
        if summary["battery"] is not None:
            try:
                props = dev.pluginProps
                if not props.get("SupportsBatteryLevel"):
                    props["SupportsBatteryLevel"] = True
                    dev.replacePluginPropsOnServer(props)
                    dev = indigo.devices[dev.id]
                dev.updateStateOnServer("batteryLevel", int(summary["battery"]),
                                        clearErrorState=False)
            except Exception as exc:
                self.logger.debug(f"Could not mirror batteryLevel for '{dev.name}': {exc}")

        if not self.trv_report_faults:
            # Routine writes no longer clear the error, so with reporting switched off
            # we must take back one we set earlier, or it would stay for ever.
            if getattr(dev, "errorState", "") == "valve silent":
                try:
                    dev.setErrorStateOnServer("")
                except Exception as exc:
                    self.logger.debug(f"Could not clear error state on '{dev.name}': {exc}")
            return
        if summary["online"] is False:
            try:
                dev.setErrorStateOnServer("valve silent")
            except Exception as exc:
                self.logger.debug(f"Could not set error state on '{dev.name}': {exc}")
            if dev.id not in self._trv_warned:
                self._trv_warned.add(dev.id)
                self.logger.warning(f"[TRV] {dev.name}: {describe(summary, now)}")
        elif summary["online"] is True:
            if dev.id in self._trv_warned:
                self._trv_warned.discard(dev.id)
                self.logger.info(f"[TRV] {dev.name}: answering again.")
            try:
                dev.setErrorStateOnServer("")
            except Exception as exc:
                self.logger.debug(f"Could not clear error state on '{dev.name}': {exc}")

    # --------------------------------------------------------------------------
    # The boiler relay  (main thread only, except where noted)
    # --------------------------------------------------------------------------

    def _start_relay_device(self, dev):
        """deviceStartComm for a boiler relay: native on/off sensor props, honest seeds."""
        with self.relay_lock:
            self.relay_devices[dev.address] = dev.id
        try:
            props = dev.pluginProps
            wanted = {"SupportsOnState": True, "SupportsSensorValue": False,
                      "SupportsStatusRequest": False, "AllowOnStateChange": False}
            if any(props.get(k) != v for k, v in wanted.items()):
                props.update(wanted)
                dev.replacePluginPropsOnServer(props)
            dev.stateListOrDisplayStateIdChanged()
            dev = indigo.devices[dev.id]
        except Exception as exc:
            self.logger.warning(f"deviceStartComm: could not set relay props for '{dev.name}': {exc}")
        try:
            seed = []
            fresh = not dev.states.get("relayStatus")
            if fresh:
                seed.append({"key": "relayStatus", "value": "unknown"})
            if not dev.states.get("relayAnswering"):
                seed.append({"key": "relayAnswering", "value": "unknown"})
            if not dev.states.get("relaySummary"):
                seed.append({"key": "relaySummary",
                             "value": describe_relay(None, None, None, False, time.time())})
            if dev.states.get("relayAddress") != dev.address:
                seed.append({"key": "relayAddress", "value": dev.address})
            # Only on a brand-new device: Indigo creates an Integer as 0, and 0% is also a
            # real demand, so a later start cannot tell the two apart.
            for key in (("heatDemand", "relayDemand") if fresh else ()):
                seed.append({"key": key, "value": RELAY_DEMAND_UNKNOWN, "uiValue": "unknown"})
            if seed:
                self._write_states(dev, seed)
        except Exception as exc:
            self.logger.warning(f"deviceStartComm: could not seed relay states for '{dev.name}': {exc}")

    def _create_relay_device(self, addr, first):
        """Create the device for a relay heard on the air. Main thread only."""
        name = RELAY_DEVICE_NAME if first else f"{RELAY_DEVICE_NAME} {addr}"
        try:
            indigo.devices[name]
            name = f"{RELAY_DEVICE_NAME} {addr}"   # the plain name is already taken
        except KeyError:
            pass
        self.logger.info(f"Auto-creating boiler relay device '{name}' for {addr}")
        try:
            new_dev = indigo.device.create(
                protocol=indigo.kProtocol.Plugin,
                address=addr,
                name=name,
                deviceTypeId=RELAY_TYPE_ID,
                props={"SupportsOnState": True, "SupportsSensorValue": False,
                       "SupportsStatusRequest": False, "AllowOnStateChange": False},
                folder=self._get_or_create_folder(DEVICE_FOLDER_NAME),
            )
        except Exception as exc:
            self.logger.error(f"Failed to create the boiler relay device for {addr}: {exc}")
            return None
        with self.relay_lock:
            self.relay_devices[addr] = new_dev.id
        return new_dev

    @staticmethod
    def _parse_relay_ts(text):
        """A relayLastHeard / relayLastChanged state back into epoch seconds, or None."""
        try:
            return datetime.strptime(str(text), RELAY_TS_FORMAT).timestamp()
        except (TypeError, ValueError):
            return None

    @classmethod
    def _relay_decision(cls, prev, rec, demand, now, listening_since):
        """The states a relay device should hold. Pure: no Indigo call, no clock read.

        prev             the device's current states (dict-like)
        rec              what the relay has said since this plugin started, or None
        demand           {"heat": pct|None, "relay": pct|None}, or None when it cannot be
                         attributed to this relay (more than one relay on the system)
        listening_since  when this plugin started listening

        Returns (states, silent). "When it last switched" is only ever claimed from a switch
        actually SEEN: the first report after a restart, or after installation, sets the
        state without inventing a time for it.
        """
        window = RELAY_SILENT_MINUTES * 60.0
        heard_live = rec.get("heard") if rec else None
        level      = rec.get("level") if rec else None
        closed     = relay_is_closed(level)

        prev_status = prev.get("relayStatus") or "unknown"
        if closed is None:
            status = prev_status if prev_status in ("on", "off") else "unknown"
        else:
            status = "on" if closed else "off"

        changed_text = prev.get("relayLastChanged") or ""
        if closed is not None and prev_status in ("on", "off") and status != prev_status:
            changed_text = datetime.fromtimestamp(rec["level_ts"]).strftime(RELAY_TS_FORMAT)

        listened_long = (now - listening_since) > window
        silent = listened_long and (heard_live is None or now - heard_live > window)
        if silent:
            answering = "silent"
        elif heard_live is not None:
            answering = "answering"
        else:
            answering = prev.get("relayAnswering") or "unknown"

        heard_ts = heard_live if heard_live is not None else cls._parse_relay_ts(prev.get("relayLastHeard"))
        heard_text = (datetime.fromtimestamp(heard_ts).strftime(RELAY_TS_FORMAT)
                      if heard_ts is not None else (prev.get("relayLastHeard") or ""))

        known = {"on": True, "off": False}.get(status)
        states = {
            "relayStatus":      status,
            "relayAnswering":   answering,
            "relayLastHeard":   heard_text,
            "relayLastChanged": changed_text,
            "relaySummary":     describe_relay(known, cls._parse_relay_ts(changed_text),
                                               heard_ts, silent, now),
        }
        if known is not None:
            states["onOffState"] = known
        if demand is not None:
            for key, src in (("heatDemand", "heat"), ("relayDemand", "relay")):
                if demand.get(src) is not None:
                    states[key] = demand[src]
        return states, silent

    def _publish_relay_states(self):
        """Create relay devices as relays are heard, and write their states on change."""
        now = time.time()
        with self.relay_lock:
            heard   = {a: dict(r) for a, r in self.relay_heard.items()}
            demand  = dict(self.boiler_demand)
            devices = dict(self.relay_devices)

        for addr in sorted(heard):
            if addr in self.ignored_relays:
                continue
            if addr not in devices:
                new_dev = self._create_relay_device(addr, first=not devices)
                if new_dev is not None:
                    devices[addr] = new_dev.id

        # Demand is the controller's, for the FC (heat source) domain. With one relay on
        # the system that relay IS the boiler; with more, nothing here says which one is,
        # so the demand is not written rather than put on the wrong device.
        attribute = len(devices) == 1
        if not attribute and devices and not self._relay_demand_note:
            self._relay_demand_note = True
            self.logger.info(f"{len(devices)} relays heard - boiler demand is not shown on "
                             "any of them, because the radio traffic does not say which "
                             "one fires the boiler")

        for addr, dev_id in devices.items():
            try:
                dev = indigo.devices[dev_id]
            except KeyError:
                with self.relay_lock:
                    if self.relay_devices.get(addr) == dev_id:
                        del self.relay_devices[addr]
                continue
            if not dev.enabled:
                continue
            states, silent = self._relay_decision(
                dev.states, heard.get(addr), demand if attribute else None,
                now, self._relay_listening_since)
            self._write_relay_states(dev, states, silent, now)
            self._account_relay_hour(dev, states, now)

    def _save_ignored_relays(self):
        try:
            prefs = self.pluginPrefs
            prefs["ignoredRelays"] = ",".join(sorted(self.ignored_relays))
            self.pluginPrefs = prefs
            self.savePluginPrefs()
        except Exception as exc:
            self.logger.debug(f"Could not save the deleted-relay list: {exc}")

    def menuRestoreDeletedRelays(self, valuesDict=None, typeId=None):
        """Forget which relays were deleted, so each is created again when next heard."""
        with self.relay_lock:
            gone = sorted(self.ignored_relays)
            self.ignored_relays.clear()
        self._save_ignored_relays()
        if gone:
            self.logger.info(f"Deleted boiler relays {', '.join(gone)} will be created again "
                             f"the next time each is heard.")
        else:
            self.logger.info("No boiler relay has been deleted, so there is nothing to bring back.")
        return True

    @staticmethod
    def _relay_hour_sentence(name, hour_start, on_secs, calls):
        """One plain sentence about an hour of the boiler relay, or None for a quiet hour."""
        minutes = int(round(on_secs / 60.0))
        if minutes == 0 and calls == 0:
            return None
        start = timetable.clock(hour_start.hour * 60)
        end = timetable.clock(((hour_start.hour + 1) % 24) * 60)
        if minutes >= 60:
            span = "the whole hour"
        elif minutes == 0:
            span = "under a minute"
        else:
            span = f"{minutes} minute{'s' if minutes != 1 else ''}"
        if calls == 0:
            count = ", carrying on from the hour before"
        elif calls == 1:
            count = ", in one call"
        else:
            count = f", in {calls} separate calls"
        return f"{name}: the boiler was called for heat for {span} between {start} and {end}{count}."

    def _account_relay_hour(self, dev, states, now):
        """Add this pass to the relay's hour, and log the hour just finished once a new one
        starts. Replaces the line per switch (about 12 an hour in winter) with one an hour."""
        is_on = bool(states.get("onOffState"))
        local = datetime.fromtimestamp(now)
        hour = local.replace(minute=0, second=0, microsecond=0)
        rec = self._relay_hours.get(dev.id)
        if rec is None:
            self._relay_hours[dev.id] = {"hour": hour, "on_secs": 0.0,
                                         "calls": 1 if is_on else 0, "last": now, "on": is_on}
            return
        gap = max(0.0, min(now - rec["last"], 60.0))   # a stalled loop must not invent burner time
        if rec["on"]:
            rec["on_secs"] += gap
        if hour != rec["hour"]:
            line = self._relay_hour_sentence(dev.name, rec["hour"], rec["on_secs"], rec["calls"])
            if line:
                self.logger.info(line)
            rec.update(hour=hour, on_secs=0.0, calls=0)
        if is_on and not rec["on"]:
            rec["calls"] += 1
        rec.update(last=now, on=is_on)

    def _write_relay_states(self, dev, states, silent, now):
        """Write what changed, then the error state. The only code that sets or clears
        the relay's error. lastHeard on its own is written at most every ten minutes, so
        a relay reporting every few minutes does not add an SQL Logger row each time."""
        batch = []
        heard_only = True
        for key, value in states.items():
            if dev.states.get(key) == value:
                continue
            if key != "relayLastHeard":
                heard_only = False
            item = {"key": key, "value": value}
            if key in ("heatDemand", "relayDemand"):
                item["uiValue"] = "unknown" if value == RELAY_DEMAND_UNKNOWN else f"{value}%"
            batch.append(item)
        if batch and heard_only and \
                now - self._relay_heard_written.get(dev.id, 0.0) < RELAY_HEARD_WRITE_EVERY:
            batch = []
        if batch:
            self._write_states(dev, batch)
            if any(i["key"] == "relayLastHeard" for i in batch):
                self._relay_heard_written[dev.id] = now
            if "onOffState" in states and any(i["key"] == "onOffState" for i in batch):
                # DEBUG from 1.14.0: the hourly summary carries it to the Event Log.
                self.logger.debug(f"{dev.name}: {states['relaySummary']}")

        if silent:
            if getattr(dev, "errorState", "") != RELAY_ERROR_TEXT:
                try:
                    dev.setErrorStateOnServer(RELAY_ERROR_TEXT)
                except Exception as exc:
                    self.logger.debug(f"Could not set error state on '{dev.name}': {exc}")
            if dev.id not in self._relay_warned:
                self._relay_warned.add(dev.id)
                self.logger.warning(f"{dev.name}: {states['relaySummary']}")
        else:
            if getattr(dev, "errorState", "") == RELAY_ERROR_TEXT:
                try:
                    dev.setErrorStateOnServer("")
                except Exception as exc:
                    self.logger.debug(f"Could not clear error state on '{dev.name}': {exc}")
            if dev.id in self._relay_warned:
                self._relay_warned.discard(dev.id)
                self.logger.info(f"{dev.name}: heard from again.")

    def actionControlSensor(self, action, dev):
        """A relay device is read-only: Evohome switches the relay, not Indigo."""
        if action.sensorAction == indigo.kSensorAction.RequestStatus:
            self.logger.info(f"{dev.name}: {dev.states.get('relaySummary', '')}. "
                             "The relay reports on its own every few minutes.")
        else:
            self.logger.warning(f"{dev.name} cannot be switched from Indigo - the Evohome "
                                "controller decides when the boiler runs.")

    def _read_prefs(self):
        """Load MQTT settings and gateway ID from plugin preferences.

        Resolution order for each credential: IndigoSecrets.py (master) -> PluginConfig.
        If neither source provides the broker host, log an ERROR — the plugin
        cannot connect without one.
        """
        prefs = self.pluginPrefs

        def _as_int(key, default, lo, hi):
            """Coerce a pref to int with guard — prefs become strings after a dialog save."""
            try:
                val = int(str(prefs.get(key, default)).strip())
            except (ValueError, TypeError):
                self.logger.warning(f"Invalid value for '{key}' — using default {default}")
                return default
            return max(lo, min(hi, val))

        self.broker_host     = MQTT_BROKER   or prefs.get("mqtt_broker_host", "").strip()
        # Same order as the host: IndigoSecrets.py first, the dialog as the fallback.
        secret_port = self._secret_broker_port()
        if MQTT_BROKER and secret_port is None and str(MQTT_PORT).strip() not in ("", "0"):
            self.logger.warning(
                f"MQTT_PORT in IndigoSecrets.py is not a port number ({MQTT_PORT!r}) — "
                "using the Broker Port from Configure instead"
            )
        self.broker_port     = secret_port or _as_int("mqtt_broker_port", 1883, 1, 65535)
        self.broker_username = MQTT_USERNAME or prefs.get("mqtt_username",    "").strip()
        self.broker_password = MQTT_PASSWORD or prefs.get("mqtt_password",    "").strip()
        self.debug           = bool(prefs.get("debug_logging",   False))

        # Power-cycle watchdog settings
        self.wd_enabled         = bool(prefs.get("watchdog_enabled", False))
        try:
            self.wd_plug_id = int(str(prefs.get("watchdog_plug_device", "")).strip() or 0)
        except (ValueError, TypeError):
            self.wd_plug_id = 0
        self.wd_offline_minutes = _as_int("watchdog_offline_minutes", 15, 5, 1440)
        self.wd_off_seconds     = _as_int("watchdog_off_seconds",     10, 3, 120)
        self.wd_max_cycles      = _as_int("watchdog_max_cycles",       3, 1, 20)

        # Per-valve tracking
        self.trv_stale_hours = _as_int("trv_stale_hours", TRV_STALE_HOURS_DEFAULT,
                                       TRV_STALE_HOURS_MIN, TRV_STALE_HOURS_MAX)
        self.trv_report_faults = as_bool(prefs.get("trv_report_faults", True), True)
        # Default True: silence about a zone we hold a device for is the fault this
        # whole feature exists to raise. Untick it where a zone legitimately has no
        # radiator valve — underfloor heating, or a zone driven by a relay — otherwise
        # that zone reports a silent valve for ever and trains its owner to ignore the
        # warning, which costs more than the warning is worth.
        self.trv_expect_every_zone = as_bool(prefs.get("trv_expect_every_zone", True), True)
        # Restore the persisted daily cycle counters so a reload mid-outage can't reset the cap.
        self.wd_cycle_day = str(prefs.get("wd_cycle_day", "")).strip()
        try:
            self.wd_cycles_today = int(str(prefs.get("wd_cycles_today", "0")).strip() or 0)
        except (ValueError, TypeError):
            self.wd_cycles_today = 0
        try:
            self.wd_last_cycle_ts = float(str(prefs.get("wd_last_cycle_ts", "0")).strip() or 0)
        except (ValueError, TypeError):
            self.wd_last_cycle_ts = 0.0
        if self.wd_enabled and not self.wd_plug_id:
            self.logger.warning(
                "Power-cycle watchdog is enabled but no plug device is selected — "
                "watchdog is inactive until one is chosen in Configure"
            )

        if not self.broker_host:
            self.logger.error(
                "No MQTT broker host configured. Set MQTT_BROKER in IndigoSecrets.py "
                "or fill in 'Broker Host' under Plugins -> RAMSES ESP -> Configure. "
                "Plugin cannot connect to the gateway until this is set."
            )

        # Extract gateway ID. The shared sanitiser handles corruption where the id was typed
        # multiple times so Indigo stored "18:20305218:20305218:..." with no whitespace.
        ctrl = str(prefs.get("controller_id", "")).strip()
        if re.match(r"^01:\d{6}$", ctrl):
            self.controller_id = ctrl

        self.ignored_relays = {a.strip() for a in str(prefs.get("ignoredRelays", "") or "").split(",")
                               if a.strip()}

        raw_gw_id = prefs.get("discovered_gateway_id", "")
        clean = self._sanitise_gateway_id(raw_gw_id)
        self.gateway_id = clean if clean else raw_gw_id.strip()   # empty or already valid

        # If the stored value was corrupted, rewrite it with the clean version
        if self.gateway_id != raw_gw_id:
            try:
                prefs["discovered_gateway_id"] = self.gateway_id
                self.pluginPrefs = prefs
                self.logger.info(
                    f"Gateway ID sanitised: was {repr(raw_gw_id)}, "
                    f"now {repr(self.gateway_id)}"
                )
            except Exception as exc:
                self.logger.warning(f"Could not save sanitised gateway ID: {exc}")

    @staticmethod
    def _port_from_secret(raw):
        """IndigoSecrets.MQTT_PORT as a usable port, or None when it is unset or unusable.

        The template ships it as the int 1883, but a hand-edited file may hold a string,
        so both are accepted. Blank, 0 and anything outside 1-65535 mean "not supplied"
        and the caller falls back to the dialog.
        """
        if isinstance(raw, bool):
            return None
        try:
            port = int(str(raw).strip())
        except (ValueError, TypeError):
            return None
        return port if 1 <= port <= 65535 else None

    @classmethod
    def _secret_broker_port(cls):
        """The port IndigoSecrets.py supplies, or None to use the dialog's.

        Read only when the file also names the broker. The shared template ships
        MQTT_PORT = 1883 with MQTT_BROKER blank, and a blank broker means "configure me
        in the dialog" — letting the template's port win there would override the port
        a user typed for their own broker.
        """
        if not MQTT_BROKER:
            return None
        return cls._port_from_secret(MQTT_PORT)

    # --------------------------------------------------------------------------
    # Menu callbacks
    # --------------------------------------------------------------------------

    def showPluginInfo(self, valuesDict=None, typeId=None):
        """Re-run the startup banner on demand from the Plugins menu."""
        extras = [("Timestamps in Log:", "ON" if self.timestamp_enabled else "OFF")]
        if log_startup_banner:
            log_startup_banner(self.pluginId, self.pluginDisplayName, self.pluginVersion, extras=extras)
        else:
            indigo.server.log(f"{self.pluginDisplayName} v{self.pluginVersion}")
            for label, value in extras:
                indigo.server.log(f"  {label} {value}")

    def menuShowTrvStatus(self, valuesDict=None, typeId=None):
        """Log what is known about every valve, worst first."""
        now   = time.time()
        stale = self.trv_stale_hours * 3600.0
        with self.trv_lock:
            addrs = self.trv.addresses()
            zones = sorted(self.trv.known_zones())
            summaries = {z: self.trv.zone_summary(z, now, stale, self._trv_listening_since)
                         for z in zones}
            silent = self.trv.silent_since(now, stale)
        indigo.server.log("=== RAMSES valve battery and liveness ===")
        indigo.server.log(f"  Valves heard: {len(addrs)} across {len(zones)} zone(s)")
        indigo.server.log(f"  Silent after: {self.trv_stale_hours} hours"
                          f"{'' if self.trv_report_faults else ' (device errors switched off)'}")
        listening = now - self._trv_listening_since
        indigo.server.log(f"  Listening for: {int(listening // 60)} minutes")
        if not addrs:
            indigo.server.log("  Nothing heard yet — valves transmit only when they have "
                              "something to say, so give it a while.")
            return True
        for zone in zones:
            dev  = self._find_zone_device(zone)
            name = dev.name if dev else f"Zone {zone}"
            indigo.server.log(f"  {name}: {describe(summaries[zone], now)}")
        unplaced = [a for a in addrs
                    if all(a not in (summaries[z]["addresses"] or "") for z in zones)]
        if unplaced:
            indigo.server.log(f"  Heard but not yet placed in a zone: {', '.join(unplaced)}")
        if silent:
            indigo.server.log("  Silent: " + ", ".join(
                f"{a} ({int(age // 3600)}h)" for a, age in silent))
        return True

    def menuForgetSilentTrvs(self, valuesDict=None, typeId=None):
        """Drop valves not heard for a week, so a replaced one stops flagging its zone.

        Deliberately a MENU ITEM and not a timer. A valve that has genuinely died is
        exactly the one that goes quiet, so forgetting it automatically would delete
        the warning rather than raise it; dropping one is a decision for a person.
        """
        now = time.time()
        with self.trv_lock:
            gone = [a for a, _ in self.trv.silent_since(now, 7 * 24 * 3600.0)]
            for addr in gone:
                self.trv.forget(addr)
        if not gone:
            indigo.server.log("[TRV] Nothing to forget — no valve has been silent for a week.")
            return True
        # Recompute from scratch: a forgotten valve changes its zone's summary.
        self._trv_published.clear()
        self._trv_warned.clear()
        self._save_trv_state()
        indigo.server.log(f"[TRV] Forgot {len(gone)} valve(s): {', '.join(gone)}. "
                          f"Each will be picked up again if it starts transmitting.")
        return True

    def menuToggleTimestamps(self):
        self.timestamp_enabled = not self.timestamp_enabled
        # Use the reassignment pattern (not bare item-assignment) so the value is staged in
        # the prefs dict Indigo flushes on shutdown.
        prefs = self.pluginPrefs
        prefs["timestampEnabled"] = self.timestamp_enabled
        self.pluginPrefs = prefs
        if self._ts_filter:
            self._ts_filter.enabled = self.timestamp_enabled
        state = "ON" if self.timestamp_enabled else "OFF"
        indigo.server.log(f"[{self.pluginDisplayName}] Timestamps in Log -> {state}")
