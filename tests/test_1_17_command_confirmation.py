#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_1_17_command_confirmation.py
# Description: 1.17.0 - a command is confirmed only when the controller reports the
#              SAME command back (temperature, mode and end time), a change is ours only
#              when it matches what we sent in full, and temperatureSeenEpoch carries the
#              temperature time as seconds since the epoch, which a clock change cannot
#              make ambiguous.
# Author:      CliveS & Claude Opus 5.5
# Date:        05-10-2026
# Version:     1.0

import os
import time
import types
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

OURS    = "01:091567"
GATEWAY = "18:203052"
_SP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                   "RAMSES_ESP.indigoPlugin", "Contents", "Server Plugin")


class FakeZone:
    def __init__(self, states=None):
        self.id, self.name, self.address, self.enabled = 1006487156, "Bedroom 3 Radiator", "7", True
        self.states = {"zoneControllerId": OURS, "setpointHeat": 20.5,
                       "zoneMode": "temporary override", "zoneOverrideUntil": "2026-10-05 10:00"}
        self.states.update(states or {})

    def updateStatesOnServer(self, states, clearErrorState=True):
        for s in states:
            self.states[s["key"]] = s["value"]


@pytest.fixture
def zone(plug, monkeypatch):
    dev = FakeZone()
    plug.controller_id  = OURS
    plug.gateway_id     = GATEWAY
    plug.gateway_online = True
    plug.mqtt_connected = True
    plug.mqtt_client    = MagicMock()
    plug.mqtt_client.publish.return_value = types.SimpleNamespace(rc=0)
    monkeypatch.setattr(plug, "_find_zone_device", lambda z: dev)
    return plug, dev


def _renew(plug, dev, setpoint=20.5, minutes=120):
    """What EvoHomeControl does every hour: the same temperature, a later end."""
    until = datetime.now().replace(second=0, microsecond=0) + timedelta(minutes=minutes)
    plug._validate_and_publish_setpoint(dev, setpoint, "set", until=until)
    return until.strftime("%Y-%m-%d %H:%M")


def _setpoint_report(plug, setpoint, rx=None):
    data = {"setpoint": setpoint, "ts": "", "controller_id": OURS}
    if rx is not None:
        data["rx"] = rx
    plug._apply_setpoint_update(7, data)


def _mode_report(plug, setpoint, mode, until="", rx=None):
    data = {"mode": mode, "until": until, "ts": "", "controller_id": OURS}
    if setpoint is not None:
        data["setpoint"] = setpoint
    if rx is not None:
        data["rx"] = rx
    plug._apply_mode_update(7, data)


# ==========================================================================
# HI-04: a renewal is confirmed only by a matching zone-mode report
# ==========================================================================

def test_a_setpoint_broadcast_does_not_confirm_a_renewal(zone):
    """The 2309 broadcast carries the temperature only, and a renewal keeps the same
    temperature, so it cannot say whether the new end time landed."""
    plug, dev = zone
    _renew(plug, dev)
    _setpoint_report(plug, 20.5)
    assert 7 in plug.pending_setpoints


def test_a_mode_report_with_the_old_end_time_does_not_confirm_it(zone):
    plug, dev = zone
    _renew(plug, dev)
    _mode_report(plug, 20.5, "temporary override", "2026-10-05 10:00")
    assert 7 in plug.pending_setpoints


def test_a_mode_report_of_the_same_command_confirms_it(zone):
    plug, dev = zone
    end = _renew(plug, dev)
    _mode_report(plug, 20.5, "temporary override", end)
    assert plug.pending_setpoints == {}


def test_an_unconfirmed_renewal_is_resent(zone):
    plug, dev = zone
    _renew(plug, dev)
    t0 = plug.pending_setpoints[7]["first"]
    _setpoint_report(plug, 20.5)
    plug._retry_setpoints(t0 + 61)
    assert plug.mqtt_client.publish.call_count == 2


def test_a_permanent_command_needs_a_permanent_mode_report(zone):
    plug, dev = zone
    plug._validate_and_publish_setpoint(dev, 19.0, "set")
    _setpoint_report(plug, 19.0)
    assert 7 in plug.pending_setpoints
    _mode_report(plug, 19.0, "temporary override", "2026-10-05 10:00")
    assert 7 in plug.pending_setpoints
    _mode_report(plug, 19.0, "permanent override")
    assert plug.pending_setpoints == {}


def test_a_mode_report_heard_before_the_command_left_does_not_confirm_it(zone):
    plug, dev = zone
    end = _renew(plug, dev)
    first = plug.pending_setpoints[7]["first"]
    _mode_report(plug, 20.5, "temporary override", end, rx=first - 5)
    assert 7 in plug.pending_setpoints


def test_a_mode_report_with_no_setpoint_confirms_once_the_temperature_has(zone):
    plug, dev = zone
    end = _renew(plug, dev)
    _mode_report(plug, None, "temporary override", end)
    assert 7 in plug.pending_setpoints, "nothing yet says the temperature landed"
    _setpoint_report(plug, 20.5)
    _mode_report(plug, None, "temporary override", end)
    assert plug.pending_setpoints == {}


def test_a_different_temperature_in_the_mode_report_does_not_confirm_it(zone):
    plug, dev = zone
    end = _renew(plug, dev)
    _mode_report(plug, 20.0, "temporary override", end)
    assert 7 in plug.pending_setpoints


def test_the_mode_frame_is_stamped_with_when_it_arrived(plug):
    plug.controller_id = OURS
    before = time.time()
    fields = ["045", "I", "---", OURS, "--:------", OURS, "2349", "013",
              "07080204FFFFFF00141C0907EA"]
    plug._parse_opcode_2349(fields, fields[8], "")
    assert plug.pending_updates[7]["rx"] >= before


# ==========================================================================
# HI-05: a change is ours only when it matches what we sent in full
# ==========================================================================

def test_a_permanent_change_at_our_temperature_is_by_hand(zone):
    """Somebody holds the room at the temperature Indigo just set, for good."""
    plug, dev = zone
    _renew(plug, dev, setpoint=21.0)
    _mode_report(plug, 21.0, "permanent override")
    assert dev.states["setpointSource"] == "manual"


def test_a_different_end_time_at_our_temperature_is_by_hand(zone):
    plug, dev = zone
    _renew(plug, dev, setpoint=21.0)
    _mode_report(plug, 21.0, "temporary override", "2026-12-25 08:00")
    assert dev.states["setpointSource"] == "manual"


def test_our_renewal_reported_back_is_ours(zone):
    plug, dev = zone
    end = _renew(plug, dev, setpoint=21.0)
    _mode_report(plug, 21.0, "temporary override", end)
    assert dev.states["setpointSource"] == "indigo"
    plug.logger.info.assert_not_called()


def test_our_permanent_command_reported_back_is_ours(zone):
    plug, dev = zone
    plug._validate_and_publish_setpoint(dev, 21.0, "set")
    _mode_report(plug, 21.0, "permanent override")
    assert dev.states["setpointSource"] == "indigo"


def test_the_sent_log_keeps_the_end_time(zone):
    plug, dev = zone
    _renew(plug, dev)
    sp, _ts, until = plug._sent_log[7]
    assert sp == pytest.approx(20.5)
    assert isinstance(until, datetime)


# ==========================================================================
# HI-09: the temperature time as epoch seconds
# ==========================================================================

@pytest.mark.parametrize("ts,expected", [
    # 25-10-2026: 01:30 BST and 01:30 GMT print the same in local text,
    # but they are an hour apart.
    ("2026-10-25T00:30:00+00:00", datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc)),
    ("2026-10-25T01:30:00+00:00", datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc)),
    ("2026-10-25T01:30:00+01:00", datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc)),
])
def test_the_epoch_follows_the_gateway_timestamp(plug, ts, expected):
    assert plug._ts_epoch(ts) == int(expected.timestamp())


@pytest.mark.parametrize("ts", ["1970-01-01T05:42:17+00:00", "", "rubbish"])
def test_an_unusable_timestamp_falls_back_to_now(plug, ts):
    before = int(time.time())
    assert before <= plug._ts_epoch(ts) <= int(time.time()) + 1


def test_a_temperature_report_writes_the_epoch(zone):
    plug, dev = zone
    plug._apply_temp_update(7, {"temp": 19.5, "ts": "2026-10-25T01:30:00+00:00",
                                "controller_id": OURS})
    assert dev.states["temperatureSeenEpoch"] == int(
        datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc).timestamp())
    assert isinstance(dev.states["temperatureSeenEpoch"], int)


def test_setpoint_and_mode_reports_leave_the_epoch_alone(zone):
    plug, dev = zone
    dev.states["temperatureSeenEpoch"] = 123
    _setpoint_report(plug, 20.5)
    _mode_report(plug, 20.5, "temporary override", "2026-10-05 10:00")
    assert dev.states["temperatureSeenEpoch"] == 123


def test_the_epoch_state_is_declared_as_an_integer():
    root = ET.parse(os.path.join(_SP, "Devices.xml")).getroot()
    zone = root.find("Device[@id='ramsesZoneThermostat']")
    state = next((s for s in zone.find("States") if s.get("id") == "temperatureSeenEpoch"), None)
    assert state is not None
    assert state.findtext("ValueType") == "Integer"
