#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_1_11_fixes.py
# Description: 1.11.0 regressions - frames taken only from our own controller, a
#              gateway that is connected but deaf, setpoints shown only once the
#              controller reports them, garbled frames, and the startup lines.
# Author:      CliveS & Claude Opus 5.5
# Date:        28-09-2026
# Version:     1.0

import ast
import os
import time
import types
from unittest.mock import MagicMock

import pytest

OURS    = "01:091567"
THEIRS  = "01:999999"
VALVE   = "04:254001"
GATEWAY = "18:203052"

_SP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                   "RAMSES_ESP.indigoPlugin", "Contents", "Server Plugin")


def _frame(sender, dest, opcode, payload, verb="I"):
    """A RAMSES line split into fields, the way _parse_ramses_message does it."""
    length = f"{len(payload) // 2:03d}"
    return ["045", verb, "---", sender, "--:------", dest, opcode, length, payload]


class FakeZone:
    def __init__(self, name="Hall Kitchen Radiator", address="3", states=None):
        self.id      = 1138438804
        self.name    = name
        self.address = address
        self.enabled = True
        self.states  = dict(states or {"zoneControllerId": OURS})
        self.writes  = []

    def updateStatesOnServer(self, states, clearErrorState=True):
        self.writes.append(list(states))
        for s in states:
            self.states[s["key"]] = s["value"]

    def updateStateOnServer(self, key, value, clearErrorState=True, **kw):
        self.writes.append([{"key": key, "value": value}])
        self.states[key] = value


# ==========================================================================
# Frames from our own controller only
# ==========================================================================

def test_a_valve_reporting_its_own_setpoint_is_not_taken_as_the_zones(plug):
    """Captured 28-09-2026: a valve sends 2309 TO the controller with what it holds,
    which just after a change is the old value."""
    plug.controller_id = OURS
    plug._parse_opcode_2309(_frame(VALVE, OURS, "2309", "040320"), "040320", "ts")
    assert plug.pending_updates == {}


def test_a_valve_temperature_addressed_to_the_controller_is_not_taken(plug):
    plug.controller_id = OURS
    plug._parse_opcode_30c9(_frame(VALVE, OURS, "30C9", "0407D0"), "0407D0", "ts")
    assert plug.pending_updates == {}


def test_the_controllers_own_broadcast_is_taken(plug):
    plug.controller_id = OURS
    plug._parse_opcode_2309(_frame(OURS, OURS, "2309", "040320"), "040320", "ts")
    assert plug.pending_updates[4]["setpoint"] == pytest.approx(8.0)


def test_a_neighbours_controller_is_ignored_and_mentioned_once(plug):
    plug.controller_id = OURS
    for _ in range(3):
        plug._parse_opcode_2309(_frame(THEIRS, THEIRS, "2309", "040834"), "040834", "ts")
        plug._parse_opcode_2349(_frame(THEIRS, THEIRS, "2349", "04083402FFFFFF"),
                                "04083402FFFFFF", "ts")
    assert plug.pending_updates == {}
    mentions = [c for c in plug.logger.info.call_args_list if THEIRS in c.args[0]]
    assert len(mentions) == 1


def test_the_first_controller_heard_is_learned_and_queued_for_saving(plug):
    assert plug.controller_id == ""
    plug._parse_opcode_2309(_frame(OURS, OURS, "2309", "040320"), "040320", "ts")
    assert plug.controller_id == OURS
    assert plug.pending_controller_id == OURS


def test_an_existing_install_takes_its_controller_from_the_zone_devices(plug, rp, monkeypatch):
    devs = {1: FakeZone(states={"zoneControllerId": OURS}),
            2: FakeZone(states={"zoneControllerId": OURS})}
    monkeypatch.setattr(rp.indigo, "devices", devs, raising=False)
    plug.zone_devices = {0: 1, 1: 2}
    assert plug._controller_from_zone_devices() == OURS


def test_zone_devices_that_disagree_decide_nothing(plug, rp, monkeypatch):
    devs = {1: FakeZone(states={"zoneControllerId": OURS}),
            2: FakeZone(states={"zoneControllerId": THEIRS})}
    monkeypatch.setattr(rp.indigo, "devices", devs, raising=False)
    plug.zone_devices = {0: 1, 1: 2}
    assert plug._controller_from_zone_devices() == ""


def test_a_neighbours_valve_is_not_filed_into_our_zones(plug):
    plug.controller_id = OURS
    plug.trv = MagicMock()
    fields = _frame(VALVE, THEIRS, "3150", "0400")
    plug._note_trv_packet(fields, "0400", "3150")
    plug.trv.record.assert_not_called()
    plug._note_trv_packet(_frame(VALVE, OURS, "3150", "0400"), "0400", "3150")
    plug.trv.record.assert_called_once()


def test_a_neighbours_boiler_demand_is_ignored(plug):
    plug.controller_id = OURS
    plug._note_relay_packet(_frame(THEIRS, THEIRS, "3150", "FCC8"), "FCC8", "3150")
    assert plug.boiler_demand["heat"] is None
    plug._note_relay_packet(_frame(OURS, OURS, "3150", "FCC8"), "FCC8", "3150")
    assert plug.boiler_demand["heat"] == 100


# ==========================================================================
# A gateway that is connected but deaf
# ==========================================================================

def test_deaf_needs_a_gateway_that_claims_to_be_online(rp):
    deaf = rp.Plugin._gateway_is_deaf
    now = 10_000.0
    assert deaf(now, True, True, True, now - 1000, now - 2000) is True
    assert deaf(now, True, True, True, now - 60, now - 2000) is False
    assert deaf(now, True, False, True, now - 1000, now - 2000) is False   # last will covers it
    assert deaf(now, True, None, True, now - 1000, now - 2000) is False
    assert deaf(now, False, True, True, now - 1000, now - 2000) is False   # our link is down
    assert deaf(now, True, True, False, now - 1000, now - 2000) is False   # not listening yet
    # A fresh subscription gets the whole window before it can be called deaf.
    assert deaf(now, True, True, True, 0.0, now - 60) is False


def _deaf_ready(plug):
    now = time.time()
    plug.mqtt_connected     = True
    plug.gateway_online     = True
    plug.gateway_subscribed = True
    plug.gateway_id         = GATEWAY
    plug.mqtt_client        = MagicMock()
    plug._last_rx_time      = now - 1000
    plug._rx_listen_since   = now - 2000
    return now


def test_a_deaf_gateway_arms_the_alert_and_the_watchdog(plug):
    now = _deaf_ready(plug)
    plug._check_gateway_deaf(now)
    assert plug.gateway_deaf is True
    assert plug.gateway_offline_since == now
    plug._check_gateway_deaf(now + 5)
    assert plug.logger.warning.call_count == 1, "said once, not every pass"


def test_a_deaf_gateway_shows_as_offline(rp):
    assert rp.Plugin._gateway_status(True, True, True) == "offline"
    assert rp.Plugin._gateway_status(True, True, False) == "online"


def test_a_message_arriving_ends_the_deaf_spell(plug):
    now = _deaf_ready(plug)
    plug._check_gateway_deaf(now)
    plug.gateway_alert_sent = True
    plug._note_rx(now + 10)
    assert plug.gateway_deaf is False
    assert plug.gateway_offline_since is None
    assert plug.pending_gateway_alert == "restored"


def test_the_gateway_rejoining_gives_it_a_fresh_window(plug):
    now = _deaf_ready(plug)
    plug._check_gateway_deaf(now)
    plug._handle_info_message(f"RAMSES/GATEWAY/{GATEWAY}", "online",
                              ["RAMSES", "GATEWAY", GATEWAY])
    assert plug.gateway_deaf is False
    assert plug._rx_listen_since >= now


def test_the_watchdog_is_rearmed_if_something_clears_the_timer(plug):
    now = _deaf_ready(plug)
    plug._check_gateway_deaf(now)
    plug.gateway_offline_since = None
    plug._check_gateway_deaf(now + 5)
    assert plug.gateway_offline_since == now + 5


# ==========================================================================
# Setpoints
# ==========================================================================

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


def test_a_sent_setpoint_is_not_shown_until_the_controller_reports_it(sending):
    plug, zone = sending
    plug._validate_and_publish_setpoint(zone, 20.5, "set")
    assert plug.mqtt_client.publish.call_count == 1
    assert "setpointHeat" not in zone.states
    assert plug.pending_setpoints[3]["sp"] == pytest.approx(20.5)


def test_the_controllers_report_confirms_it(sending):
    plug, zone = sending
    plug._validate_and_publish_setpoint(zone, 20.5, "set")
    plug._apply_setpoint_update(3, {"setpoint": 20.5, "ts": "", "controller_id": OURS})
    assert plug.pending_setpoints == {}
    assert zone.states["setpointHeat"] == pytest.approx(20.5)


def test_the_old_value_one_step_away_does_not_confirm_it(sending):
    plug, zone = sending
    plug._validate_and_publish_setpoint(zone, 20.5, "set")
    plug._confirm_setpoint(3, 20.0)
    assert 3 in plug.pending_setpoints


def test_an_unconfirmed_setpoint_is_resent_then_given_up(sending):
    plug, zone = sending
    plug._validate_and_publish_setpoint(zone, 20.5, "set")
    t0 = plug.pending_setpoints[3]["first"]
    plug._retry_setpoints(t0 + 30)
    assert plug.mqtt_client.publish.call_count == 1, "not yet"
    plug._retry_setpoints(t0 + 61)
    plug._retry_setpoints(t0 + 122)
    assert plug.mqtt_client.publish.call_count == 3
    plug._retry_setpoints(t0 + 200)
    assert plug.mqtt_client.publish.call_count == 3, "three sends in all"
    assert plug.logger.warning.call_count == 0
    plug._retry_setpoints(t0 + 301)
    assert 3 not in plug.pending_setpoints
    assert "not confirmed" in plug.logger.warning.call_args.args[0]


def test_a_refused_publish_is_not_recorded(sending):
    plug, zone = sending
    plug.mqtt_client.publish.return_value = types.SimpleNamespace(rc=4)
    plug._validate_and_publish_setpoint(zone, 20.5, "set")
    assert plug.pending_setpoints == {}
    assert plug.logger.error.called


@pytest.mark.parametrize("offline,deaf", [(True, False), (False, True)])
def test_nothing_is_sent_through_a_gateway_that_cannot_pass_it_on(sending, offline, deaf):
    plug, zone = sending
    plug.gateway_online = False if offline else True
    plug.gateway_deaf   = deaf
    plug._validate_and_publish_setpoint(zone, 20.5, "set")
    plug._validate_and_publish_setpoint(zone, 21.0, "set")
    plug.mqtt_client.publish.assert_not_called()
    assert plug.logger.error.call_count == 1, "said once per outage"


def test_no_resends_while_the_gateway_is_down(sending):
    plug, zone = sending
    plug._validate_and_publish_setpoint(zone, 20.5, "set")
    t0 = plug.pending_setpoints[3]["first"]
    plug.gateway_deaf = True
    plug._retry_setpoints(t0 + 61)
    assert plug.mqtt_client.publish.call_count == 1
    plug._retry_setpoints(t0 + 1801)
    assert plug.pending_setpoints == {}, "a command left from a long outage is forgotten"


# ==========================================================================
# Garbled frames, and the startup lines
# ==========================================================================

def test_a_garbled_frame_is_not_logged_as_an_error(plug):
    plug.controller_id = OURS
    plug._parse_ramses_message(f"045 I --- {OURS} --:------ {OURS} 30C9 003 04ZZZZ", "ts")
    plug.logger.error.assert_not_called()


def test_startup_says_one_line_at_info():
    with open(os.path.join(_SP, "plugin.py"), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    startup = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "startup")
    infos = [n for n in ast.walk(startup)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "info"]
    assert len(infos) == 1
