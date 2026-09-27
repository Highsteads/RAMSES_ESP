#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    ramses_relay.py
# Description: The boiler relay (BDR91) and the controller's boiler demand, decoded from
#              the RAMSES-II packets they broadcast. No Indigo import - this is the test seam.
# Author:      CliveS & Claude Opus 5.5
# Date:        27-09-2026
# Version:     1.0
#
# WHY THIS EXISTS. Evohome fires the boiler through a BDR91 wireless relay, and until now
# Indigo could not see when that happened. Everything needed is already on the air.
# Measured on a live gateway on 27-09-2026 (radio addresses replaced with examples):
#
#   I --- 13:123456 --:------ 13:123456 3B00 002 00C8     the relay's cycle sync
#   I --- 13:123456 --:------ 13:123456 3EF0 003 0000FF   the relay's own state (off)
#   I --- 01:123456 --:------ 01:123456 3B00 002 FCC8     the controller's cycle sync
#   I --- 01:123456 --:------ 01:123456 3150 002 FC00     the controller's heat demand
#   I --- 01:123456 --:------ 01:123456 0008 002 FC00     the controller's relay demand
#
# The 3EF0 layout and the FC "boiler" domain follow the community ramses_rf decoding,
# whose own notes carry the two BDR91 forms: 0000FF (open) and 00C8FF (closed).

import datetime as _dt

OPCODE_ACTUATOR_STATE = "3EF0"   # a relay reporting its contact
OPCODE_ACTUATOR_SYNC  = "3B00"   # start-of-cycle sync; carries no state, proves life
OPCODE_RELAY_DEMAND   = "0008"   # what the controller asks the relay for
OPCODE_HEAT_DEMAND    = "3150"   # how much heat the controller wants overall

RELAY_ADDRESS_PREFIX      = "13:"   # BDR91 and other Honeywell relays
CONTROLLER_ADDRESS_PREFIX = "01:"   # the Evohome controller
DOMAIN_BOILER             = "FC"    # the domain that means "the heat source"

# Demand and relay levels are 0-200, halving to a percentage. 0xFF means "not known".
# Some devices send a little over 200 at full demand (ramses_rf issue #71 saw 0xCA);
# that is read as 100%, not refused.
LEVEL_MAX     = 200
LEVEL_UNKNOWN = 0xFF


def is_relay_address(addr):
    """True for a RAMSES address belonging to a relay such as the BDR91."""
    return isinstance(addr, str) and addr.startswith(RELAY_ADDRESS_PREFIX)


def relay_source(fields):
    """The relay that SENT this packet, or None if it did not come from one."""
    if len(fields) < 4:
        return None
    src = fields[3].strip()
    return src if is_relay_address(src) else None


def controller_source(fields):
    """The controller that SENT this packet, or None if it did not come from one."""
    if len(fields) < 4:
        return None
    src = fields[3].strip()
    return src if src.startswith(CONTROLLER_ADDRESS_PREFIX) else None


def _level_to_percent(raw):
    """0-200 to a whole percentage, None for 'not known'."""
    if raw == LEVEL_UNKNOWN:
        return None
    return int(round(min(raw, LEVEL_MAX) * 100 / LEVEL_MAX))


def parse_relay_state(payload_hex):
    """Decode a 3EF0 payload into the relay's level as a percentage, or None.

    Byte 1 is the level. A BDR91 only ever says 0 (open) or 200 (closed); other relays
    can report a part level, which is kept as it came. Three bytes is the BDR91 form;
    longer payloads come from OpenTherm bridges and are read the same way.
    """
    try:
        payload = (payload_hex or "").strip().upper()
        if len(payload) < 6 or len(payload) % 2:
            return None
        return _level_to_percent(int(payload[2:4], 16))
    except ValueError:
        return None


def parse_boiler_demand(payload_hex):
    """Decode a controller's 0008 or 3150 payload for the FC (boiler) domain.

    Returns a whole percentage, or None when the payload is not a two-byte FC entry or
    the level is 'not known'. A zone-level payload (00-0B in byte 0) is not boiler
    demand, and a payload of any other length is refused outright rather than guessed.
    """
    try:
        payload = (payload_hex or "").strip().upper()
        if len(payload) != 4 or payload[0:2] != DOMAIN_BOILER:
            return None
        return _level_to_percent(int(payload[2:4], 16))
    except ValueError:
        return None


def relay_is_closed(level):
    """True when the relay is closed (calling the boiler), None when not known."""
    if level is None:
        return None
    return level > 0


def _clock(ts):
    """A time as a person says it: '7:05am', '12:30pm'."""
    t = _dt.datetime.fromtimestamp(ts)
    hour = t.hour % 12 or 12
    suffix = "am" if t.hour < 12 else "pm"
    return f"{hour}:{t.minute:02d}{suffix}"


def _when(ts, now):
    """'7:05am', or 'yesterday at 7:05am', or '3 Sep at 7:05am'."""
    then = _dt.datetime.fromtimestamp(ts)
    today = _dt.datetime.fromtimestamp(now).date()
    if then.date() == today:
        return _clock(ts)
    if then.date() == today - _dt.timedelta(days=1):
        return f"yesterday at {_clock(ts)}"
    return f"{then.day} {then.strftime('%b')} at {_clock(ts)}"


def describe(closed, changed_ts, heard_ts, silent, now):
    """One plain-English line for the device list.

    closed      True / False / None (not known)
    changed_ts  when the relay was last SEEN to switch, or None
    heard_ts    when the relay last spoke at all, or None
    silent      True when it has been quiet for longer than it ever should be
    """
    if heard_ts is None:
        return "Not heard from the boiler relay yet"
    if silent:
        return f"The boiler relay has not been heard since {_when(heard_ts, now)}"
    if closed is None:
        return "Heard from the boiler relay, state not reported yet"
    word = "Calling the boiler for heat" if closed else "Not calling for heat"
    if changed_ts is None:
        return word
    return f"{word} since {_when(changed_ts, now)}"
