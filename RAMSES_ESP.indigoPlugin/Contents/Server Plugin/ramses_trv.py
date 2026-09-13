#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    ramses_trv.py
# Description: Per-valve liveness and battery, decoded from the RAMSES-II packets the
#              TRVs broadcast about themselves. No Indigo import — this is the test seam.
# Author:      CliveS & Claude Opus 5
# Date:        13-09-2026
# Version:     1.1
#
# WHY THIS EXISTS. A zone device's `online` and `lastSeen` describe the GATEWAY's MQTT
# link and the CONTROLLER's periodic broadcast — the controller keeps announcing a zone
# whether or not the valve in it is still answering, so a dead HR92 stayed invisible
# until the room went cold. Nothing anywhere held a battery reading for a TRV either.
#
# Both facts are already on the air. Measured on this gateway on 12-09-2026: over nine
# minutes the valves sent 13 packets of their own from 5 distinct addresses, and a packet
# a valve addresses to the controller carries its ZONE INDEX as payload byte 0.

OPCODE_BATTERY = "1060"

# 1060 payload, per the community ramses_rf decoding: three bytes — index, level, flag.
# A level of 0xFF means the valve is not reporting one; otherwise it is 0-200 and halves
# to a percentage. The flag is 0x00 for "I am warning about my battery" and 0x01 for not.
BATTERY_LEVEL_UNKNOWN = 0xFF
BATTERY_LEVEL_MAX     = 200
BATTERY_SCALE         = 2.0
BATTERY_LOW_FALSE     = 0x01

# The address class a heating valve uses. 01: is the controller, 18: the gateway.
TRV_ADDRESS_PREFIX = "04:"


def is_trv_address(addr):
    """True for a RAMSES address belonging to a heating valve."""
    return isinstance(addr, str) and addr.startswith(TRV_ADDRESS_PREFIX)


def trv_source(fields):
    """The valve that SENT this packet, or None if it did not come from one."""
    if len(fields) < 4:
        return None
    src = fields[3].strip()
    return src if is_trv_address(src) else None


def trv_zone_from_fields(fields, payload_hex, max_zones):
    """The zone a valve's packet is about, or None when the packet cannot say.

    A packet a valve ADDRESSES TO THE CONTROLLER carries the zone index as payload
    byte 0 — measured 12-09-2026 across 3150 heat-demand and 12B0 window-detection
    packets, and it agrees with the zone the same valve's 2309 setpoint reports.

    A valve's SELF-addressed packet (04:x -> 04:x, which is how it reports its own
    temperature) does NOT. Byte 0 there is 00 whatever the zone, so reading it would
    file every such valve under zone 0 and quietly attach one room's battery reading
    to another room's device. Hence the explicit check that the destination is the
    controller before byte 0 is believed at all.
    """
    if trv_source(fields) is None:
        return None
    if len(fields) < 6:
        return None
    # DEV2 is usually '--:------' and DEV3 the controller, but accept either slot.
    if not any(f.strip().startswith("01:") for f in fields[4:6]):
        return None
    if not payload_hex or len(payload_hex) < 2:
        return None
    try:
        zone = int(payload_hex[0:2], 16)
    except ValueError:
        return None
    return zone if 0 <= zone < max_zones else None


def parse_battery(payload_hex):
    """Decode a 1060 payload into (percent, low_flag), or None when it cannot be read.

    Returns a 2-tuple. Either element may be None on its own: a valve can report a
    low-battery flag without a level, and a level of 0xFF means it is declining to
    give one. A payload that is not three bytes returns None OUTRIGHT — a length we
    do not recognise is a layout we cannot read, and half-decoding it would invent a
    battery percentage out of somebody else's field.

    UNPROVEN AGAINST THIS HARDWARE. No 1060 was captured from these HR92s while this
    was written, so the layout rests on the community convention rather than on a
    specimen off this roof. That is precisely why every unrecognised shape returns
    None rather than a plausible number: an invented battery reading is worse than
    no reading, because it silences the very warning the feature exists to give.
    """
    if not isinstance(payload_hex, str):
        return None
    hexstr = payload_hex.strip().upper()
    if len(hexstr) != 6:
        return None
    try:
        raw_level = int(hexstr[2:4], 16)
        raw_flag  = int(hexstr[4:6], 16)
    except ValueError:
        return None

    if raw_level == BATTERY_LEVEL_UNKNOWN or raw_level > BATTERY_LEVEL_MAX:
        percent = None
    else:
        percent = int(round(raw_level / BATTERY_SCALE))

    low = (raw_flag != BATTERY_LOW_FALSE)
    return percent, low


class TrvRegistry:
    """What each valve has said, and when.

    Keyed by the valve's own address, because that is what identifies it — a zone can
    hold more than one valve, and a valve can be moved between zones. Everything is
    aggregated to the WORST case: the lowest battery and the OLDEST sighting, since a
    zone is only as healthy as its unhappiest valve.
    """

    def __init__(self):
        self._trv = {}   # addr -> dict

    # -- recording ---------------------------------------------------------

    def record(self, addr, ts, zone=None, battery_pct=None, battery_low=None):
        """Note that `addr` was heard at `ts`, with whatever else the packet carried.

        `zone`, `battery_pct` and `battery_low` are only written when SUPPLIED. A
        self-addressed packet arrives with no zone, and most packets carry no battery
        at all; letting either overwrite with None would throw away a fact already
        learned every time the valve mentioned something else.
        """
        if not is_trv_address(addr):
            return
        rec = self._trv.setdefault(addr, {
            "zone": None, "last_seen": 0.0,
            "battery_pct": None, "battery_low": None, "battery_at": None,
        })
        if ts and ts > rec["last_seen"]:
            rec["last_seen"] = float(ts)
        if zone is not None:
            rec["zone"] = int(zone)
        if battery_pct is not None or battery_low is not None:
            if battery_pct is not None:
                rec["battery_pct"] = int(battery_pct)
            if battery_low is not None:
                rec["battery_low"] = bool(battery_low)
            rec["battery_at"] = float(ts) if ts else None

    def forget(self, addr):
        """Drop a valve entirely. Returns True when there was one to drop."""
        return self._trv.pop(addr, None) is not None

    def silent_since(self, now, stale_secs):
        """[(addr, seconds_silent)] for every valve past the threshold, worst first.

        Deliberately NOT an auto-prune: a valve that has genuinely died is exactly the
        one that goes quiet, so forgetting it on a timer would delete the warning
        instead of raising it. Dropping one is a decision for a person to take.
        """
        out = [(a, now - r["last_seen"]) for a, r in self._trv.items()
               if r["last_seen"] and now - r["last_seen"] > stale_secs]
        return sorted(out, key=lambda p: -p[1])

    # -- reading -----------------------------------------------------------

    def known_zones(self):
        return {r["zone"] for r in self._trv.values() if r["zone"] is not None}

    def addresses(self):
        return sorted(self._trv)

    def zone_summary(self, zone, now, stale_secs, listening_since=0.0):
        """What to publish for one zone, or None when nothing is known about it.

        None means exactly that — no valve for this zone has ever been heard — and the
        caller must write nothing rather than a reassuring default. A device showing a
        confident "online" for a zone we have no valve for is the failure this whole
        feature exists to remove.

        `listening_since` is when this plugin last started listening, and it is what
        stops a restart inventing a fault. Silence is only evidence if somebody was
        listening through it: a valve last heard before the plugin came up may have
        been transmitting happily all night into a receiver that was switched off. So a
        valve is judged silent only once it has been heard SINCE we started listening,
        or once we have been listening longer than the threshold itself. Until then its
        liveness is unknown, which is the truth.
        """
        valves = {a: r for a, r in self._trv.items() if r["zone"] == zone}
        if not valves:
            return None

        seen  = [r["last_seen"] for r in valves.values() if r["last_seen"]]
        pcts  = [r["battery_pct"] for r in valves.values() if r["battery_pct"] is not None]
        lows  = [r["battery_low"] for r in valves.values() if r["battery_low"] is not None]

        listened_long_enough = (now - listening_since) > stale_secs
        silent, unjudgeable = [], []
        for addr, rec in sorted(valves.items()):
            last = rec["last_seen"]
            if last and now - last <= stale_secs:
                continue                      # heard recently: fine
            if last and last >= listening_since:
                silent.append(addr)           # heard since we started, then stopped
            elif listened_long_enough:
                silent.append(addr)           # we have listened long enough to be sure
            else:
                unjudgeable.append(addr)      # too soon after a restart to say

        if not seen:
            online = None
        elif silent:
            online = False
        elif unjudgeable:
            online = None
        else:
            online = True

        return {
            "count":      len(valves),
            "addresses":  ", ".join(sorted(valves)),
            "battery":    min(pcts) if pcts else None,
            "battery_low": (any(lows) if lows else None),
            "last_seen":  max(seen) if seen else None,
            "oldest_seen": min(seen) if seen else None,
            "online":     online,
            "silent":     ", ".join(silent),
        }

    # -- persistence -------------------------------------------------------

    def to_dict(self):
        return {"version": 1, "trv": self._trv}

    def load_dict(self, data):
        """Restore from disk, skipping anything malformed rather than refusing the lot.

        One corrupt entry must not cost every other valve its history — the whole point
        of persisting is that a restart does not blank the readings until each valve
        happens to speak again.
        """
        if not isinstance(data, dict):
            return 0
        loaded = 0
        for addr, rec in (data.get("trv") or {}).items():
            if not is_trv_address(addr) or not isinstance(rec, dict):
                continue
            try:
                self._trv[addr] = {
                    "zone":        None if rec.get("zone") is None else int(rec["zone"]),
                    "last_seen":   float(rec.get("last_seen") or 0.0),
                    "battery_pct": None if rec.get("battery_pct") is None else int(rec["battery_pct"]),
                    "battery_low": None if rec.get("battery_low") is None else bool(rec["battery_low"]),
                    "battery_at":  None if rec.get("battery_at") is None else float(rec["battery_at"]),
                }
                loaded += 1
            except (TypeError, ValueError):
                continue
        return loaded


def _hours_words(seconds):
    """A rough age in the words a person uses, singular handled."""
    if seconds is None:
        return "some time"
    mins = int(seconds // 60)
    if mins < 60:
        return "a minute" if mins == 1 else f"{mins} minutes"
    hours = int(round(seconds / 3600.0))
    if hours < 48:
        return "an hour" if hours == 1 else f"{hours} hours"
    days = int(round(seconds / 86400.0))
    return "a day" if days == 1 else f"{days} days"


def unheard_summary(listened_long_enough):
    """What to publish for a zone that HAS a device but whose valve has never been heard.

    `zone_summary` returns None for a zone the registry knows nothing about, and the
    caller used to skip exactly those — which made the one valve most likely to be
    missing from the registry, a valve already dead when the plugin started listening,
    the single case that could never raise a fault. It sat on its seeded "unknown" for
    as long as it stayed dead. Live: the Utility Room valve went quiet on 02-06-2026 and
    still read "unknown" on 13-09-2026, 103 days later, with a working detector either
    side of it and nothing in between.

    Absence of a record is not absence of a fault. Once we have been listening for
    longer than the threshold, having heard nothing whatever from a zone we hold a
    device for is a verdict rather than a shrug, so `online` is False and it takes the
    same path to the error state as a valve that fell quiet while we watched. Before
    that it is None, which is the same grace a known valve gets after a restart.
    """
    return {
        "count":       0,
        "addresses":   "",
        "battery":     None,
        "battery_low": None,
        "last_seen":   None,
        "oldest_seen": None,
        "online":      False if listened_long_enough else None,
        "silent":      "",
    }


def describe(summary, now):
    """One plain-English sentence about a zone's valves.

    Written for a person reading a control page or a log line, so it says what the
    numbers mean rather than listing them: "Both valves answering" beats "count 2,
    online true". An unknown stays unknown in words too — a sentence that reads as
    reassurance when nothing has been heard would undo the point of the None above.
    """
    if not summary:
        return "No valve heard for this zone yet."

    # A zone we hold a device for and have never heard a valve in. Kept ahead of the
    # count arithmetic below, which would otherwise read "All 0 valves answering".
    if summary["count"] == 0:
        if summary["online"] is False:
            return ("Nothing has ever been heard from this zone's valve. It has either "
                    "lost power, gone out of range, or is set to a different zone.")
        return ("Nothing heard from this zone's valve yet, and it is too soon since the "
                "restart to say whether that is a fault.")

    n = summary["count"]
    what = "The valve" if n == 1 else ("Both valves" if n == 2 else f"All {n} valves")

    if summary["online"] is False:
        names = summary["silent"] or "a valve"
        age = _hours_words(now - summary["oldest_seen"]) if summary["oldest_seen"] else "some time"
        head = f"{names} has not been heard for {age}."
        if "," in names:
            head = f"{names} have not been heard for {age}."
    elif summary["online"] is None:
        head = f"{what} answering, though it is too soon since the restart to be sure."
        if n > 1:
            head = f"{what} answering, though it is too soon since the restart to be sure."
    else:
        head = f"{what} answering."

    batt = summary["battery"]
    if batt is None:
        tail = " No battery reading yet."
    elif n == 1:
        tail = f" Battery {batt}%."
    else:
        tail = f" Lowest battery {batt}%."
    if summary["battery_low"]:
        tail += " One of them is warning that its battery is low."
    return head + tail
