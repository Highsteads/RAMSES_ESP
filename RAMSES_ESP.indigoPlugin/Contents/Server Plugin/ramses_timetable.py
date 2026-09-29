#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    ramses_timetable.py
# Description: Read an Evohome zone's weekly timetable over RAMSES-II (opcode 0404):
#              request and reply framing, fragment decoding, and plain-English text.
#              No indigo import, so it is tested on its own.
# Author:      CliveS & Claude Opus 5.5
# Date:        29-09-2026
# Version:     1.0
#
# PROVEN LIVE 29-09-2026 on controller 01:091567, all 12 zones, and cross-checked against
# ramses_rf's ScheduleFragmentPayload / ScheduleSwitchpointPayload:
#   RQ --- 18:gw 01:ctl --:------ 0404 007 ZZ200008 00 NN TT   (TT = 00 on the first ask)
#   RP --- 01:ctl 18:gw --:------ 0404 LLL ZZ200008 len NN TT <fragment>
# The fragments, joined, are a zlib stream of 20-byte little-endian records:
# zone, day (0 = Monday), minutes after midnight, setpoint x 100, and a trailer that on
# this controller is a paired cooling setpoint (ignored here). Each switchpoint holds until
# the next one, wrapping past midnight into the following day.

import json
import struct
import zlib

OPCODE_TIMETABLE = "0404"
_RECORD          = "<xxxxBxxxBxxxHxxHH"
_RECORD_SIZE     = 20
SLOT_MINUTES     = 10                 # Evohome switchpoints fall on 10-minute steps
SLOTS_PER_DAY    = 24 * 60 // SLOT_MINUTES
DAY_NAMES        = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                    "Saturday", "Sunday")


def build_request(zone, frag, total):
    """The payload of an RQ 0404 asking for fragment `frag` of `total` (0 = unknown)."""
    return f"{zone:02X}200008{0:02X}{frag:02X}{total:02X}"


def parse_reply(payload_hex):
    """(zone, fragment, total, fragment_hex) from an RP 0404 payload, or None."""
    p = (payload_hex or "").strip().upper()
    if len(p) < 14 or p[2:8] != "200008":
        return None
    try:
        zone, frag, total = int(p[0:2], 16), int(p[10:12], 16), int(p[12:14], 16)
    except ValueError:
        return None
    data = p[14:]
    if not data or frag < 1 or total < frag:
        return None
    return zone, frag, total, data


def decode(fragments):
    """{day: [(minutes, setpoint_c), ...]} from the fragments in order. Raises ValueError
    on a stream that does not decompress or does not divide into whole records."""
    try:
        raw = zlib.decompress(bytes.fromhex("".join(fragments)))
    except (zlib.error, ValueError) as exc:
        raise ValueError(f"timetable does not decompress: {exc}") from exc
    if not raw or len(raw) % _RECORD_SIZE:
        raise ValueError(f"timetable is {len(raw)} bytes, not whole records")
    week = {}
    for offset in range(0, len(raw), _RECORD_SIZE):
        _zone, day, minutes, setpoint, _trailer = struct.unpack(
            _RECORD, raw[offset:offset + _RECORD_SIZE])
        if day > 6 or minutes >= 24 * 60:
            raise ValueError(f"record out of range: day {day}, minute {minutes}")
        week.setdefault(day, []).append((minutes, setpoint / 100.0))
    for day in week:
        week[day].sort()
    return week


def to_json(week):
    """Compact text for a device state: {"0": [[300, 17.0], ...], ...}."""
    return json.dumps({str(d): [[m, sp] for m, sp in week[d]] for d in sorted(week)},
                      separators=(",", ":"))


def from_json(text):
    """The reverse of to_json. Raises ValueError on anything malformed."""
    data = json.loads(text)
    return {int(d): [(int(m), float(sp)) for m, sp in points] for d, points in data.items()}


def effective(week):
    """The setpoint in force in every 10-minute slot of the week, Monday midnight first.
    Before a day's first switchpoint the last one of the previous day still holds."""
    last_of = {}
    for day in range(7):
        points = week.get(day) or []
        last_of[day] = points[-1][1] if points else None
    slots = []
    for day in range(7):
        current = None
        back = day
        for _ in range(7):
            back = (back - 1) % 7
            if last_of[back] is not None:
                current = last_of[back]
                break
        points = list(week.get(day) or [])
        for slot in range(SLOTS_PER_DAY):
            minute = slot * SLOT_MINUTES
            while points and points[0][0] <= minute:
                current = points.pop(0)[1]
            slots.append(current)
    return slots


def clock(minutes):
    """5am, 6:30am, noon, midnight, 11:50pm - as a person says it."""
    h, m = divmod(int(minutes), 60)
    if (h, m) == (0, 0):
        return "midnight"
    if (h, m) == (12, 0):
        return "noon"
    suffix = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    return f"{h12}{suffix}" if m == 0 else f"{h12}:{m:02d}{suffix}"


def degrees(value):
    return f"{value:g}"


def _join_days(days):
    names = [DAY_NAMES[d] for d in days]
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def describe(week):
    """One plain-English line: 'Every day: 5am 17, 9am 18, noon 20.' Days with the same
    switchpoints are grouped."""
    if not week:
        return "No timetable read."
    groups = {}
    for day in range(7):
        key = tuple(week.get(day) or [])
        groups.setdefault(key, []).append(day)
    parts = []
    for points, days in groups.items():
        text = ", ".join(f"{clock(m)} {degrees(sp)}" for m, sp in points) or "nothing set"
        label = "Every day" if len(days) == 7 else _join_days(days)
        parts.append(f"{label}: {text}.")
    return " ".join(parts)
