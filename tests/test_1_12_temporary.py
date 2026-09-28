#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_1_12_temporary.py
# Description: 1.12.0 - temporary overrides that hand a zone back to the Evohome
#              timetable when they run out. The frames here are the ones sent to and
#              echoed by the live controller on 28-09-2026.
# Author:      CliveS & Claude Opus 5.5
# Date:        28-09-2026
# Version:     1.0

import json
import types
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

OURS    = "01:091567"
GATEWAY = "18:203052"

# Sent at 19:19:45 and honoured; the controller's schedule broadcast when it ran out.
LIVE_SENT     = "07035204FFFFFF16131C0907EA"
LIVE_LAPSED   = "07064000FFFFFF"


def _frame(opcode, payload, sender=OURS):
    return ["042", "I", "---", sender, "--:------", sender, opcode,
            f"{len(payload) // 2:03d}", payload]


def test_the_encoder_builds_the_frame_the_controller_accepted(rp):
    until = datetime(2026, 9, 28, 19, 22)
    assert rp.Plugin._encode_2349_setpoint(7, 8.5, until) == LIVE_SENT


def test_without_an_end_time_it_is_still_a_permanent_override(rp):
    assert rp.Plugin._encode_2349_setpoint(1, 21.5) == "01086602FFFFFF"


def test_the_end_time_is_read_back(rp):
    assert rp.Plugin._decode_2349_until(LIVE_SENT) == "2026-09-28 19:22"
    assert rp.Plugin._decode_2349_until(LIVE_LAPSED) == ""
    assert rp.Plugin._decode_2349_until("07035204FFFFFFFFFFFFFFFFFF") == ""


def test_the_controllers_echo_reads_as_a_temporary_override(plug):
    plug.controller_id = OURS
    plug._parse_opcode_2349(_frame("2349", LIVE_SENT), LIVE_SENT, "ts")
    rec = plug.pending_updates[7]
    assert rec["mode"] == "temporary override"
    assert rec["until"] == "2026-09-28 19:22"
    assert rec["setpoint"] == pytest.approx(8.5)


def test_when_it_runs_out_the_zone_reads_as_on_its_schedule(plug):
    plug.controller_id = OURS
    plug._parse_opcode_2349(_frame("2349", LIVE_LAPSED), LIVE_LAPSED, "ts")
    rec = plug.pending_updates[7]
    assert rec["mode"] == "schedule"
    assert rec["until"] == ""
    assert rec["setpoint"] == pytest.approx(16.0)


class FakeZone:
    def __init__(self):
        self.id, self.name, self.address, self.enabled = 1006487156, "Bedroom 3 Radiator", "7", True
        self.states = {"zoneControllerId": OURS}

    def updateStatesOnServer(self, states, clearErrorState=True):
        for s in states:
            self.states[s["key"]] = s["value"]


@pytest.fixture
def sending(plug, monkeypatch):
    zone = FakeZone()
    plug.mqtt_connected = True
    plug.gateway_online = True
    plug.gateway_id     = GATEWAY
    plug.controller_id  = OURS
    plug.mqtt_client    = MagicMock()
    plug.mqtt_client.publish.return_value = types.SimpleNamespace(rc=0)
    monkeypatch.setattr(plug, "_find_zone_device", lambda z: zone)
    return plug, zone


def _sent(plug):
    return [json.loads(c.args[1])["msg"] for c in plug.mqtt_client.publish.call_args_list]


def _action(zone, **props):
    return types.SimpleNamespace(deviceId=zone.id, props=props)


def test_the_action_sends_a_temporary_override(sending):
    plug, zone = sending
    before = datetime.now()
    plug.action_set_temporary_setpoint(_action(zone, setpoint="20.5", minutes="120"), zone)
    (msg,) = _sent(plug)
    assert f"W --- {GATEWAY} {OURS} --:------ 2349 013 07080204FFFFFF" in msg
    until = plug.pending_setpoints[7]["until"]
    assert timedelta(minutes=120) <= until - before.replace(second=0, microsecond=0) <= timedelta(minutes=122)


def test_a_resend_is_the_same_command(sending):
    plug, zone = sending
    plug.action_set_temporary_setpoint(_action(zone, setpoint="20.5", minutes="120"), zone)
    t0 = plug.pending_setpoints[7]["first"]
    plug._retry_setpoints(t0 + 61)
    first, second = _sent(plug)
    assert first == second


def test_the_length_is_kept_within_bounds(sending):
    plug, zone = sending
    plug.action_set_temporary_setpoint(_action(zone, setpoint="20", minutes="1"), zone)
    until = plug.pending_setpoints[7]["until"]
    assert until - datetime.now() >= timedelta(minutes=9)


def test_a_setpoint_that_is_not_a_number_sends_nothing(sending):
    plug, zone = sending
    plug.action_set_temporary_setpoint(_action(zone, setpoint="warm", minutes="120"), zone)
    plug.mqtt_client.publish.assert_not_called()
    assert plug.logger.error.called


def test_the_action_is_declared_for_zone_devices_only():
    import os
    import xml.etree.ElementTree as ET
    here = os.path.dirname(os.path.abspath(__file__))
    tree = ET.parse(os.path.join(here, "..", "RAMSES_ESP.indigoPlugin", "Contents",
                                 "Server Plugin", "Actions.xml"))
    action = next(a for a in tree.getroot() if a.get("id") == "setTemporarySetpoint")
    assert action.get("deviceFilter") == "self.ramsesZoneThermostat"
    assert action.findtext("CallbackMethod") == "action_set_temporary_setpoint"
