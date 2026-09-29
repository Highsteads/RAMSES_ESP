#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_1_15_dual_control.py
# Description: 1.15.0 - telling a change made by hand (controller, valve wheel, app) from
#              one Indigo made, and a timed setting with an explicit end date.
# Author:      CliveS & Claude Opus 5.5
# Date:        29-09-2026
# Version:     1.0

import json
import time
import types
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

OURS    = "01:091567"
GATEWAY = "18:203052"


class FakeZone:
    def __init__(self, states=None):
        self.id, self.name, self.address, self.enabled = 1006487156, "Bedroom 3 Radiator", "7", True
        self.states = {"zoneControllerId": OURS, "setpointHeat": 8.0,
                       "zoneMode": "temporary override", "zoneOverrideUntil": "2026-10-14 00:00"}
        self.states.update(states or {})

    def updateStatesOnServer(self, states, clearErrorState=True):
        for s in states:
            self.states[s["key"]] = s["value"]


@pytest.fixture
def zone(plug, monkeypatch):
    dev = FakeZone()
    plug.controller_id = OURS
    plug.gateway_id = GATEWAY
    plug.gateway_online = True
    plug.mqtt_connected = True
    plug.mqtt_client = MagicMock()
    plug.mqtt_client.publish.return_value = types.SimpleNamespace(rc=0)
    monkeypatch.setattr(plug, "_find_zone_device", lambda z: dev)
    return plug, dev


def _report(plug, setpoint, mode, until=""):
    plug._apply_mode_update(7, {"setpoint": setpoint, "mode": mode, "until": until,
                                "ts": "", "controller_id": OURS})


# ==========================================================================
# Who changed it
# ==========================================================================

def test_a_change_nobody_here_sent_is_by_hand(zone):
    plug, dev = zone
    _report(plug, 21.0, "temporary override", "2026-10-05 22:00")
    assert dev.states["setpointSource"] == "manual"
    assert dev.states["setpointChangedAt"]
    line = plug.logger.info.call_args.args[0]
    assert "21 degrees until 10pm from outside Indigo" in line


def test_our_own_command_is_ours(zone):
    plug, dev = zone
    plug._validate_and_publish_setpoint(dev, 20.5, "set",
                                        until=datetime.now() + timedelta(hours=2))
    _report(plug, 20.5, "temporary override", "2026-10-05 22:00")
    assert dev.states["setpointSource"] == "indigo"
    plug.logger.info.assert_not_called()


def test_an_old_command_does_not_excuse_a_new_change(zone, monkeypatch):
    plug, dev = zone
    plug._sent_log[7] = (21.0, time.time() - 3600)
    _report(plug, 21.0, "temporary override", "2026-10-05 22:00")
    assert dev.states["setpointSource"] == "manual"


def test_going_back_to_the_timetable_is_the_timetable(zone):
    plug, dev = zone
    _report(plug, 16.0, "schedule")
    assert dev.states["setpointSource"] == "timetable"
    plug.logger.info.assert_not_called()


def test_a_permanent_change_by_hand_says_so(zone):
    plug, dev = zone
    _report(plug, 19.0, "permanent override")
    assert dev.states["setpointSource"] == "manual"
    assert "until it is changed back" in plug.logger.info.call_args.args[0]


def test_a_repeat_of_what_the_device_shows_changes_nothing(zone):
    plug, dev = zone
    _report(plug, 8.0, "temporary override", "2026-10-14 00:00")
    assert "setpointSource" not in dev.states


# ==========================================================================
# A timed setting with an end date
# ==========================================================================

def _sent(plug):
    return [json.loads(c.args[1])["msg"] for c in plug.mqtt_client.publish.call_args_list]


def test_an_end_date_wins_over_a_length(zone):
    plug, dev = zone
    end = (datetime.now() + timedelta(days=15)).replace(hour=0, minute=0, second=0, microsecond=0)
    action = types.SimpleNamespace(deviceId=dev.id, props={
        "setpoint": "8", "minutes": "120", "until": end.strftime("%Y-%m-%d %H:%M")})
    plug.action_set_temporary_setpoint(action, dev)
    (msg,) = _sent(plug)
    assert msg.endswith(f"{end.minute:02X}{end.hour:02X}{end.day:02X}{end.month:02X}{end.year:04X}")
    assert plug.pending_setpoints[7]["until"] == end


@pytest.mark.parametrize("text", ["not a date", "2020-01-01 00:00", "2099-01-01 00:00"])
def test_a_bad_or_out_of_range_end_sends_nothing(zone, text):
    plug, dev = zone
    action = types.SimpleNamespace(deviceId=dev.id, props={"setpoint": "8", "until": text})
    plug.action_set_temporary_setpoint(action, dev)
    plug.mqtt_client.publish.assert_not_called()
    assert plug.logger.error.called


def test_the_new_states_and_field_are_declared():
    import os
    import xml.etree.ElementTree as ET
    sp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                      "RAMSES_ESP.indigoPlugin", "Contents", "Server Plugin")
    states = {s.get("id") for s in ET.parse(os.path.join(sp, "Devices.xml")).getroot().iter("State")}
    assert {"setpointSource", "setpointChangedAt"} <= states
    action = next(a for a in ET.parse(os.path.join(sp, "Actions.xml")).getroot()
                  if a.get("id") == "setTemporarySetpoint")
    assert any(f.get("id") == "until" for f in action.iter("Field"))
