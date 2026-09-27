#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_relay.py
# Description: Contract tests for the boiler relay (BDR91) device added in 1.10.0 — the
#              3EF0 / 0008 / 3150 decode, the routing of live packets, the state decision
#              (never inventing a switch time), silence, demand attribution and the
#              device lifecycle.
# Author:      CliveS & Claude Opus 5.5
# Date:        27-09-2026
# Version:     1.0
#
# The packets used here were captured from a live gateway on 27-09-2026, with the radio
# addresses swapped for example ones.

import os
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SP = os.path.abspath(os.path.join(_HERE, "..", "RAMSES_ESP.indigoPlugin",
                                   "Contents", "Server Plugin"))
if _SP not in sys.path:
    sys.path.insert(0, _SP)

import ramses_relay as R   # noqa: E402

RELAY_OFF  = "060  I --- 13:123456 --:------ 13:123456 3EF0 003 0000FF"
RELAY_ON   = "060  I --- 13:123456 --:------ 13:123456 3EF0 003 00C8FF"
RELAY_SYNC = "060  I --- 13:123456 --:------ 13:123456 3B00 002 00C8"
CTRL_SYNC  = "043  I --- 01:123456 --:------ 01:123456 3B00 002 FCC8"
CTRL_HEAT  = "043  I --- 01:123456 --:------ 01:123456 3150 002 FC{lvl}"
CTRL_RELAY = "043  I --- 01:123456 --:------ 01:123456 0008 002 FC{lvl}"
TRV_DEMAND = "050  I --- 04:124335 --:------ 01:123456 3150 002 03{lvl}"

NOW = datetime(2026, 9, 27, 12, 0, 0).timestamp()
HOUR = 3600.0


# --------------------------------------------------------------------------
# The pure decode
# --------------------------------------------------------------------------

class TestRelayState:
    @pytest.mark.parametrize("payload,pct", [
        ("0000FF", 0), ("00C8FF", 100), ("00c8ff", 100), (" 00C8FF ", 100),
        ("0064100C00FF", 50),     # an OpenTherm bridge's longer form, read the same way
        ("00CAFF", 100),          # a little over 200 is full, not junk
    ])
    def test_levels(self, payload, pct):
        assert R.parse_relay_state(payload) == pct

    @pytest.mark.parametrize("payload", ["", None, "00C8", "00C8F", "00FFFF", "zzzzzz"])
    def test_refused(self, payload):
        assert R.parse_relay_state(payload) is None


class TestBoilerDemand:
    @pytest.mark.parametrize("payload,pct", [("FC00", 0), ("FCC8", 100), ("FC64", 50),
                                             ("FCCA", 100), ("fc64", 50)])
    def test_levels(self, payload, pct):
        assert R.parse_boiler_demand(payload) == pct

    @pytest.mark.parametrize("payload", [
        "03C8",      # a zone's demand, not the boiler's
        "FCFF",      # not known
        "FC0000",    # wrong length
        "FC", "", None, "FCZZ",
    ])
    def test_refused(self, payload):
        assert R.parse_boiler_demand(payload) is None


def test_sources():
    relay = RELAY_OFF.split()
    ctrl = CTRL_SYNC.split()
    trv = TRV_DEMAND.format(lvl="00").split()
    assert R.relay_source(relay) == "13:123456"
    assert R.relay_source(ctrl) is None and R.relay_source(trv) is None
    assert R.controller_source(ctrl) == "01:123456"
    assert R.controller_source(relay) is None and R.controller_source(trv) is None
    assert R.relay_source(["x"]) is None


def test_relay_is_closed():
    assert R.relay_is_closed(None) is None
    assert R.relay_is_closed(0) is False
    assert R.relay_is_closed(100) is True


class TestDescribe:
    def test_never_heard(self):
        assert R.describe(None, None, None, False, NOW) == "Not heard from the boiler relay yet"

    def test_silent_names_when_it_was_last_heard(self):
        heard = datetime(2026, 9, 27, 7, 5).timestamp()
        assert R.describe(True, None, heard, True, NOW) == \
            "The boiler relay has not been heard since 7:05am"

    def test_calling_since(self):
        changed = datetime(2026, 9, 27, 11, 40).timestamp()
        assert R.describe(True, changed, NOW, False, NOW) == \
            "Calling the boiler for heat since 11:40am"

    def test_yesterday_and_older(self):
        yday = datetime(2026, 9, 26, 22, 15).timestamp()
        older = datetime(2026, 9, 3, 12, 0).timestamp()
        assert R.describe(False, yday, NOW, False, NOW) == \
            "Not calling for heat since yesterday at 10:15pm"
        assert R.describe(False, older, NOW, False, NOW) == \
            "Not calling for heat since 3 Sep at 12:00pm"

    def test_no_switch_seen_claims_no_time(self):
        assert R.describe(False, None, NOW, False, NOW) == "Not calling for heat"

    def test_heard_but_state_not_yet_reported(self):
        assert R.describe(None, None, NOW, False, NOW) == \
            "Heard from the boiler relay, state not reported yet"


# --------------------------------------------------------------------------
# Live packets through the plugin's parser
# --------------------------------------------------------------------------

def _feed(plug, *lines):
    for line in lines:
        plug._parse_ramses_message(line, "ts")


def test_a_relay_report_records_level_and_life(plug):
    _feed(plug, RELAY_OFF)
    rec = plug.relay_heard["13:123456"]
    assert rec["level"] == 0 and rec["heard"] is not None


def test_a_sync_proves_life_but_not_state(plug):
    _feed(plug, RELAY_ON, RELAY_SYNC)
    rec = plug.relay_heard["13:123456"]
    assert rec["level"] == 100            # the sync did not wipe the level


def test_controller_demand_is_recorded(plug):
    _feed(plug, CTRL_HEAT.format(lvl="64"), CTRL_RELAY.format(lvl="C8"))
    assert plug.boiler_demand == {"heat": 50, "relay": 100}


def test_a_zone_demand_is_not_boiler_demand(plug):
    _feed(plug, TRV_DEMAND.format(lvl="C8"))
    assert plug.boiler_demand == {"heat": None, "relay": None}


def test_a_request_is_ignored(plug):
    _feed(plug, "045 RQ --- 01:123456 13:123456 --:------ 3EF0 001 00")
    assert plug.relay_heard == {}


def test_a_bad_relay_packet_costs_nothing_else(plug):
    _feed(plug, "060  I --- 13:123456 --:------ 13:123456 3EF0 003 ZZ",
          CTRL_HEAT.format(lvl="00"))
    assert plug.boiler_demand["heat"] == 0


# --------------------------------------------------------------------------
# The state decision
# --------------------------------------------------------------------------

def _decide(rp, prev=None, rec=None, demand=None, now=NOW, since=NOW - 3 * HOUR):
    return rp.Plugin._relay_decision(prev or {}, rec, demand, now, since)


def test_the_first_report_sets_the_state_without_inventing_a_switch(rp):
    states, silent = _decide(rp, rec={"heard": NOW, "level": 0, "level_ts": NOW})
    assert states["relayStatus"] == "off"
    assert states["onOffState"] is False
    assert states["relayLastChanged"] == ""
    assert states["relaySummary"] == "Not calling for heat"
    assert silent is False


def test_a_seen_switch_records_when(rp):
    ts = NOW - 60
    states, _ = _decide(rp, prev={"relayStatus": "off"},
                        rec={"heard": ts, "level": 100, "level_ts": ts})
    assert states["relayStatus"] == "on" and states["onOffState"] is True
    assert states["relayLastChanged"] == datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    assert states["relaySummary"].startswith("Calling the boiler for heat since ")


def test_an_unchanged_state_keeps_its_switch_time(rp):
    prev = {"relayStatus": "on", "relayLastChanged": "2026-09-27 07:05:00"}
    states, _ = _decide(rp, prev=prev, rec={"heard": NOW, "level": 100, "level_ts": NOW})
    assert states["relayLastChanged"] == "2026-09-27 07:05:00"
    assert states["relaySummary"] == "Calling the boiler for heat since 7:05am"


def test_before_any_report_the_last_known_state_stands(rp):
    prev = {"relayStatus": "on", "relayAnswering": "answering",
            "relayLastHeard": "2026-09-27 11:58:00"}
    states, silent = _decide(rp, prev=prev, rec=None, since=NOW - 60)
    assert states["relayStatus"] == "on"
    assert states["relayAnswering"] == "answering"
    assert silent is False


def test_silence_is_only_called_after_listening_long_enough(rp):
    prev = {"relayStatus": "off", "relayLastHeard": "2026-09-27 07:05:00"}
    window = rp.RELAY_SILENT_MINUTES * 60
    _, early = _decide(rp, prev=prev, rec=None, since=NOW - window + 5)
    states, late = _decide(rp, prev=prev, rec=None, since=NOW - window - 5)
    assert early is False
    assert late is True
    assert states["relayAnswering"] == "silent"
    assert states["relaySummary"] == "The boiler relay has not been heard since 7:05am"


def test_a_relay_that_went_quiet_is_silent(rp):
    window = rp.RELAY_SILENT_MINUTES * 60
    heard = NOW - window - 1
    _, silent = _decide(rp, rec={"heard": heard, "level": 0, "level_ts": heard})
    assert silent is True
    _, silent = _decide(rp, rec={"heard": NOW - window + 1, "level": 0, "level_ts": NOW})
    assert silent is False


def test_demand_is_written_only_when_attributed_and_known(rp):
    rec = {"heard": NOW, "level": 0, "level_ts": NOW}
    states, _ = _decide(rp, rec=rec, demand=None)
    assert "heatDemand" not in states and "relayDemand" not in states
    states, _ = _decide(rp, rec=rec, demand={"heat": 40, "relay": None})
    assert states["heatDemand"] == 40 and "relayDemand" not in states


# --------------------------------------------------------------------------
# Device lifecycle and writes, against a fake Indigo
# --------------------------------------------------------------------------

class FakeRelay:
    def __init__(self, dev_id, name, address, states=None, props=None):
        self.id = dev_id
        self.name = name
        self.address = address
        self.deviceTypeId = "ramsesBoilerRelay"
        self.enabled = True
        self.errorState = ""
        self.states = dict(states or {})
        self.pluginProps = dict(props or {})
        self.writes = []
        self.errors = []

    def updateStatesOnServer(self, states, clearErrorState=True):
        assert clearErrorState is False
        self.writes.append([dict(s) for s in states])
        for s in states:
            self.states[s["key"]] = s["value"]

    def updateStateOnServer(self, key, value, clearErrorState=True, **_kw):
        assert clearErrorState is False
        self.writes.append([{"key": key, "value": value}])
        self.states[key] = value

    def setErrorStateOnServer(self, msg):
        self.errors.append(msg)
        self.errorState = msg

    def replacePluginPropsOnServer(self, props):
        self.pluginProps = dict(props)

    def stateListOrDisplayStateIdChanged(self):
        pass


class FakeDevices:
    def __init__(self):
        self.by_id = {}

    def __getitem__(self, key):
        if isinstance(key, int):
            return self.by_id[key]
        for dev in self.by_id.values():
            if dev.name == key:
                return dev
        raise KeyError(key)

    def iter(self, _filter=None):
        return iter(list(self.by_id.values()))


@pytest.fixture
def fake(plug, rp, monkeypatch):
    devices = FakeDevices()
    created = []

    def create(protocol, address, name, deviceTypeId, props, folder):
        dev = FakeRelay(100 + len(devices.by_id), name, address, props=props)
        devices.by_id[dev.id] = dev
        created.append(dev)
        return dev

    monkeypatch.setattr(rp.indigo, "devices", devices)
    monkeypatch.setattr(rp.indigo.device, "create", create)
    monkeypatch.setattr(plug, "_get_or_create_folder", lambda _name: 1)
    plug._batch_keeps_error = True
    return plug, devices, created


def test_the_first_relay_heard_becomes_the_boiler_relay(fake):
    plug, _devices, created = fake
    _feed(plug, RELAY_OFF)
    plug._publish_relay_states()
    assert [d.name for d in created] == ["Boiler Relay"]
    assert created[0].address == "13:123456"
    assert created[0].pluginProps["SupportsOnState"] is True
    assert created[0].pluginProps["SupportsSensorValue"] is False


def test_a_second_relay_is_named_by_address_and_demand_goes_nowhere(fake):
    plug, _devices, created = fake
    _feed(plug, RELAY_OFF, CTRL_HEAT.format(lvl="64"))
    plug._publish_relay_states()
    _feed(plug, "060  I --- 13:999999 --:------ 13:999999 3EF0 003 0000FF")
    plug._publish_relay_states()
    assert [d.name for d in created] == ["Boiler Relay", "Boiler Relay 13:999999"]
    # Demand was written while there was one relay; once there are two it is not
    # moved onto either of them.
    _feed(plug, CTRL_HEAT.format(lvl="C8"))
    plug._publish_relay_states()
    assert created[0].states.get("heatDemand") == 50
    assert "heatDemand" not in created[1].states


def test_one_relay_carries_the_demand(fake):
    plug, _devices, created = fake
    _feed(plug, RELAY_ON, CTRL_HEAT.format(lvl="C8"), CTRL_RELAY.format(lvl="64"))
    plug._publish_relay_states()
    dev = created[0]
    assert dev.states["heatDemand"] == 100 and dev.states["relayDemand"] == 50
    assert dev.states["onOffState"] is True
    ui = {i["key"]: i.get("uiValue") for batch in dev.writes for i in batch}
    assert ui["heatDemand"] == "100%"


def test_nothing_is_written_when_nothing_moved(fake):
    plug, _devices, created = fake
    _feed(plug, RELAY_OFF)
    plug._publish_relay_states()
    before = len(created[0].writes)
    plug._publish_relay_states()
    assert len(created[0].writes) == before


def test_last_heard_alone_is_rate_limited(fake, rp):
    plug, _devices, created = fake
    _feed(plug, RELAY_OFF)
    plug._publish_relay_states()
    dev = created[0]
    before = len(dev.writes)
    later = time.time() + 120
    plug.relay_heard["13:123456"]["heard"] = later
    plug._write_relay_states(dev, rp.Plugin._relay_decision(
        dev.states, plug.relay_heard["13:123456"], None, later, plug._relay_listening_since)[0],
        False, later)
    assert len(dev.writes) == before      # only lastHeard moved, too soon to write
    much_later = later + rp.RELAY_HEARD_WRITE_EVERY + 1
    plug.relay_heard["13:123456"]["heard"] = much_later
    plug._write_relay_states(dev, rp.Plugin._relay_decision(
        dev.states, plug.relay_heard["13:123456"], None, much_later,
        plug._relay_listening_since)[0], False, much_later)
    assert len(dev.writes) == before + 1


def test_silence_sets_the_error_once_and_recovery_clears_it(fake, rp):
    plug, _devices, created = fake
    _feed(plug, RELAY_OFF)
    plug._publish_relay_states()
    dev = created[0]
    window = rp.RELAY_SILENT_MINUTES * 60
    plug._relay_listening_since -= 2 * window
    plug.relay_heard["13:123456"]["heard"] -= 2 * window
    plug._publish_relay_states()
    plug._publish_relay_states()
    assert dev.errors == ["relay silent"]
    assert dev.states["relayAnswering"] == "silent"
    assert plug.logger.warning.call_count == 1
    _feed(plug, RELAY_SYNC)
    plug._publish_relay_states()
    assert dev.errors == ["relay silent", ""]
    assert dev.states["relayAnswering"] == "answering"


def test_a_disabled_relay_device_is_left_alone(fake):
    plug, _devices, created = fake
    _feed(plug, RELAY_OFF)
    plug._publish_relay_states()
    dev = created[0]
    dev.enabled = False
    _feed(plug, RELAY_ON)
    plug._publish_relay_states()
    assert dev.states["relayStatus"] == "off"
    assert len(created) == 1                  # and it is not re-created either


def test_start_comm_gives_a_relay_sensor_props_not_thermostat_props(fake, rp):
    plug, devices, _created = fake
    dev = FakeRelay(7, "Boiler Relay", "13:123456")
    devices.by_id[7] = dev
    plug.deviceStartComm(dev)
    assert dev.pluginProps["SupportsOnState"] is True
    assert "SupportsHeatSetpoint" not in dev.pluginProps
    assert plug.relay_devices == {"13:123456": 7}
    assert dev.states["relayStatus"] == "unknown"
    assert dev.states["heatDemand"] == -1


def test_a_restart_does_not_reseed_a_real_zero_demand(fake):
    plug, devices, _created = fake
    dev = FakeRelay(7, "Boiler Relay", "13:123456",
                    states={"relayStatus": "off", "heatDemand": 0, "relayDemand": 0})
    devices.by_id[7] = dev
    plug.deviceStartComm(dev)
    assert dev.states["heatDemand"] == 0 and dev.states["relayDemand"] == 0


def test_deleting_the_relay_drops_it_from_the_index(fake):
    plug, devices, _created = fake
    dev = FakeRelay(7, "Boiler Relay", "13:123456")
    devices.by_id[7] = dev
    plug.deviceStartComm(dev)
    plug.deviceDeleted(dev)
    assert plug.relay_devices == {}


def test_request_status_answers_and_switching_is_refused(plug, rp):
    dev = FakeRelay(7, "Boiler Relay", "13:123456",
                    states={"relaySummary": "Not calling for heat"})
    action = type("A", (), {"sensorAction": rp.indigo.kSensorAction.RequestStatus})()
    plug.actionControlSensor(action, dev)
    assert plug.logger.info.called
    action.sensorAction = rp.indigo.kSensorAction.TurnOn
    plug.actionControlSensor(action, dev)
    assert plug.logger.warning.called


def test_the_main_loop_publishes_the_relay(plug, monkeypatch):
    called = []
    monkeypatch.setattr(plug, "_publish_relay_states", lambda: called.append(1))
    monkeypatch.setattr(plug, "_watchdog_tick", lambda _x: None)
    monkeypatch.setattr(plug, "_publish_gateway_status", lambda: None)
    monkeypatch.setattr(plug, "_publish_trv_states", lambda: None)
    plug.mqtt_connected = True
    plug._zone_names_requested = True
    plug._main_loop_pass()
    assert called == [1]


def test_a_failing_relay_pass_warns_once_and_the_loop_carries_on(plug, monkeypatch):
    def boom():
        raise RuntimeError("no such state")
    monkeypatch.setattr(plug, "_publish_relay_states", boom)
    monkeypatch.setattr(plug, "_watchdog_tick", lambda _x: None)
    monkeypatch.setattr(plug, "_publish_gateway_status", lambda: None)
    monkeypatch.setattr(plug, "_publish_trv_states", lambda: None)
    plug.mqtt_connected = True
    plug._zone_names_requested = True
    plug._main_loop_pass()
    plug._main_loop_pass()
    assert plug.logger.warning.call_count == 1


# --------------------------------------------------------------------------
# Devices.xml
# --------------------------------------------------------------------------

def test_the_relay_device_is_a_sensor_that_does_not_redeclare_native_states():
    tree = ET.parse(os.path.join(_SP, "Devices.xml"))
    dev = tree.find(".//Device[@id='ramsesBoilerRelay']")
    assert dev is not None and dev.get("type") == "sensor"
    ids = {s.get("id") for s in dev.findall("./States/State")}
    assert "onOffState" not in ids and "sensorValue" not in ids
    for wanted in ("relayStatus", "relayAnswering", "relaySummary", "relayLastChanged",
                   "relayLastHeard", "relayAddress", "heatDemand", "relayDemand"):
        assert wanted in ids
    assert all("_" not in i for i in ids)
