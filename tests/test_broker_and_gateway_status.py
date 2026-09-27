#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_broker_and_gateway_status.py
# Description: 1.9.0 regressions — the Configure dialog saves with Broker Host blank when
#              IndigoSecrets.py names the broker, MQTT_PORT is read with the same order as
#              the host, and the new gatewayStatus state follows the GATEWAY rather than
#              this plugin's own broker link.
# Author:      CliveS & Claude Opus 5.5
# Date:        27-09-2026
# Version:     1.0

import time

import pytest


def _secrets(monkeypatch, rp, broker="", port=""):
    """Pin the module-level IndigoSecrets values. On the Indigo Mac the real file is on
    sys.path, so every test sets these explicitly rather than inheriting real values."""
    monkeypatch.setattr(rp, "MQTT_BROKER", broker)
    monkeypatch.setattr(rp, "MQTT_PORT", port)


def _dialog(**kw):
    values = {"mqtt_broker_host": "", "mqtt_broker_port": "1883",
              "discovered_gateway_id": "", "watchdog_enabled": False}
    values.update(kw)
    return values


# --------------------------------------------------------------------------
# The Configure dialog and a blank Broker Host
# --------------------------------------------------------------------------

def test_blank_host_saves_when_the_secrets_file_names_the_broker(plug, rp, monkeypatch):
    _secrets(monkeypatch, rp, broker="192.168.1.10")
    result = plug.validatePrefsConfigUi(_dialog())
    assert result[0] is True


def test_blank_host_is_still_refused_with_no_broker_anywhere(plug, rp, monkeypatch):
    _secrets(monkeypatch, rp)
    ok, _values, errors = plug.validatePrefsConfigUi(_dialog())
    assert ok is False
    assert "mqtt_broker_host" in errors


def test_blank_port_saves_when_the_secrets_file_supplies_it(plug, rp, monkeypatch):
    _secrets(monkeypatch, rp, broker="192.168.1.10", port=1883)
    assert plug.validatePrefsConfigUi(_dialog(mqtt_broker_port=""))[0] is True


def test_a_bad_port_is_refused_even_when_the_file_supplies_one(plug, rp, monkeypatch):
    _secrets(monkeypatch, rp, broker="192.168.1.10", port=1883)
    ok, _values, errors = plug.validatePrefsConfigUi(_dialog(mqtt_broker_port="abc"))
    assert ok is False
    assert "mqtt_broker_port" in errors


def test_blank_port_is_refused_when_the_file_does_not_name_the_broker(plug, rp, monkeypatch):
    # The template ships MQTT_PORT = 1883 with MQTT_BROKER blank. That port belongs to
    # nobody's broker, so it must not excuse an empty dialog field.
    _secrets(monkeypatch, rp, port=1883)
    ok, _values, errors = plug.validatePrefsConfigUi(
        _dialog(mqtt_broker_host="192.168.1.10", mqtt_broker_port=""))
    assert ok is False
    assert "mqtt_broker_port" in errors


# --------------------------------------------------------------------------
# MQTT_PORT resolution
# --------------------------------------------------------------------------

def test_port_comes_from_the_secrets_file_first(plug, rp, monkeypatch):
    _secrets(monkeypatch, rp, broker="192.168.1.10", port=8883)
    plug.pluginPrefs = {"mqtt_broker_port": "1883"}
    plug._read_prefs()
    assert plug.broker_port == 8883


def test_port_from_the_file_may_be_a_string(plug, rp, monkeypatch):
    _secrets(monkeypatch, rp, broker="192.168.1.10", port=" 8883 ")
    plug.pluginPrefs = {"mqtt_broker_port": "1883"}
    plug._read_prefs()
    assert plug.broker_port == 8883


def test_dialog_port_is_used_when_the_file_does_not_name_the_broker(plug, rp, monkeypatch):
    _secrets(monkeypatch, rp, port=1883)
    plug.pluginPrefs = {"mqtt_broker_host": "192.168.1.10", "mqtt_broker_port": "8883"}
    plug._read_prefs()
    assert plug.broker_port == 8883


def test_a_bad_port_in_the_file_falls_back_to_the_dialog_and_warns(plug, rp, monkeypatch):
    _secrets(monkeypatch, rp, broker="192.168.1.10", port="not-a-port")
    plug.pluginPrefs = {"mqtt_broker_port": "8883"}
    plug._read_prefs()
    assert plug.broker_port == 8883
    assert plug.logger.warning.called


@pytest.mark.parametrize("raw", ["", 0, "0", None, 70000, -1, True])
def test_port_from_secret_rejects_what_is_not_a_port(rp, raw):
    assert rp.Plugin._port_from_secret(raw) is None


# --------------------------------------------------------------------------
# gatewayStatus
# --------------------------------------------------------------------------

class FakeZone:
    def __init__(self, dev_id):
        self.id = dev_id
        self.name = f"Zone {dev_id}"
        self.states = {}
        self.calls = []

    def updateStateOnServer(self, key, value, clearErrorState=True):
        self.calls.append((key, value, clearErrorState))
        self.states[key] = value


@pytest.fixture
def zones(plug, rp, monkeypatch):
    devs = {101: FakeZone(101), 102: FakeZone(102)}
    monkeypatch.setattr(rp.indigo, "devices", devs, raising=False)
    plug.zone_devices = {0: 101, 1: 102}
    plug.mqtt_connected = True
    return plug, devs


def test_status_is_unknown_until_the_gateway_has_spoken(rp):
    assert rp.Plugin._gateway_status(True, None) == "unknown"


def test_status_is_unknown_while_our_own_broker_link_is_down(rp):
    # With our link down nothing from the gateway can reach us, so an old verdict
    # either way would be a guess.
    assert rp.Plugin._gateway_status(False, True) == "unknown"
    assert rp.Plugin._gateway_status(False, False) == "unknown"


def test_status_follows_the_gateway_not_the_broker(rp):
    assert rp.Plugin._gateway_status(True, True) == "online"
    assert rp.Plugin._gateway_status(True, False) == "offline"


def test_a_dead_gateway_reads_offline_with_the_broker_still_up(zones):
    """The reported fault: the broker link stays up, the gateway's last will arrives."""
    plug, devs = zones
    plug.gateway_id = "18:000001"
    plug._handle_info_message("RAMSES/GATEWAY/18:000001", "offline",
                              ["RAMSES", "GATEWAY", "18:000001"])
    plug._publish_gateway_status()
    assert devs[101].states["gatewayStatus"] == "offline"
    assert devs[102].states["gatewayStatus"] == "offline"


def test_gateway_status_write_never_clears_a_valve_error(zones):
    plug, devs = zones
    plug.gateway_online = True
    plug._publish_gateway_status()
    assert all(call[2] is False for dev in devs.values() for call in dev.calls)


def test_an_unchanged_status_writes_nothing(zones):
    plug, devs = zones
    plug.gateway_online = True
    plug._publish_gateway_status()
    plug._publish_gateway_status()
    assert len(devs[101].calls) == 1
    plug.gateway_online = False
    plug._publish_gateway_status()
    assert [c[1] for c in devs[101].calls] == ["online", "offline"]


def test_the_main_loop_publishes_gateway_status(zones, rp, monkeypatch):
    plug, devs = zones
    plug.gateway_online = True
    monkeypatch.setattr(plug, "_watchdog_tick", lambda *_: None)
    monkeypatch.setattr(plug, "_publish_trv_states", lambda: None)
    plug._zone_names_requested = True
    plug._main_loop_pass()
    assert devs[101].states.get("gatewayStatus") == "online"


def test_gateway_status_is_declared_for_the_zone_device(rp):
    import os
    import xml.etree.ElementTree as ET
    from conftest import SERVER_PLUGIN
    root = ET.parse(os.path.join(SERVER_PLUGIN, "Devices.xml")).getroot()
    dev = root.find(f"./Device[@id='{rp.DEVICE_TYPE_ID}']")
    state = dev.find("./States/State[@id='gatewayStatus']")
    assert state is not None
    options = {o.get("value") for o in state.iter("Option")}
    assert options == {"unknown", "online", "offline"}


# --------------------------------------------------------------------------
# Routine zone writes keep the "valve silent" error (1.9.0)
# --------------------------------------------------------------------------

class ErrorZone:
    """A zone device that behaves like Indigo: every state write clears the error
    unless clearErrorState=False. `batch_kwarg` says whether the batch call takes it."""

    def __init__(self, dev_id=201, batch_kwarg=True):
        self.id = dev_id
        self.name = "Test Zone"
        self.address = "0"
        self.states = {"setpointHeat": 20.0}
        self.pluginProps = {}
        self.errorState = "valve silent"
        self.batch_kwarg = batch_kwarg
        self.batch_calls = 0
        self.single_calls = 0

    def updateStatesOnServer(self, states, **kw):
        if kw and not self.batch_kwarg:
            raise TypeError("updateStatesOnServer() got an unexpected keyword argument")
        self.batch_calls += 1
        for s in states:
            self.states[s["key"]] = s["value"]
        if kw.get("clearErrorState", True):
            self.errorState = ""

    def updateStateOnServer(self, key, value, clearErrorState=True, **_kw):
        self.single_calls += 1
        self.states[key] = value
        if clearErrorState:
            self.errorState = ""

    def setErrorStateOnServer(self, msg):
        self.errorState = msg


@pytest.fixture(params=[True, False], ids=["batch-takes-flag", "batch-refuses-flag"])
def silent_zone(request, plug, rp, monkeypatch):
    dev = ErrorZone(batch_kwarg=request.param)
    monkeypatch.setattr(rp.indigo, "devices", {dev.id: dev}, raising=False)
    plug.zone_devices = {0: dev.id}
    return plug, dev


def test_a_temperature_broadcast_keeps_the_valve_error(silent_zone):
    plug, dev = silent_zone
    plug._apply_temp_update(0, {"temp": 19.5, "controller_id": "01:000001", "ts": ""})
    assert dev.states["temperatureInput1"] == 19.5
    assert dev.errorState == "valve silent"


@pytest.mark.parametrize("apply, data", [
    ("_apply_setpoint_update", {"setpoint": 21.0}),
    ("_apply_mode_update", {"mode": "schedule", "setpoint": 21.0}),
])
def test_setpoint_and_mode_broadcasts_keep_the_valve_error(silent_zone, apply, data):
    plug, dev = silent_zone
    getattr(plug, apply)(0, dict(data, ts=""))
    assert dev.errorState == "valve silent"


def test_a_broker_drop_keeps_the_valve_error(silent_zone):
    plug, dev = silent_zone
    plug._apply_offline_update(0)
    assert dev.states["online"] == "false"
    assert dev.errorState == "valve silent"


def test_a_refused_batch_flag_is_remembered(plug, rp, monkeypatch):
    dev = ErrorZone(batch_kwarg=False)
    plug._write_states(dev, [{"key": "a", "value": 1}])
    plug._write_states(dev, [{"key": "b", "value": 2}])
    assert plug._batch_keeps_error is False
    assert dev.batch_calls == 0 and dev.single_calls == 2
    assert dev.errorState == "valve silent"


def test_only_the_valve_code_can_clear_the_error(silent_zone):
    plug, dev = silent_zone
    plug.trv_report_faults = True
    summary = {"count": 1, "addresses": "04:000001", "battery": None, "battery_low": None,
               "last_seen": time.time(), "oldest_seen": time.time(), "online": True,
               "silent": ""}
    plug._write_trv_states(dev, summary, time.time())
    assert dev.errorState == ""


def test_switching_reporting_off_takes_back_our_own_error(silent_zone):
    plug, dev = silent_zone
    plug.trv_report_faults = False
    summary = {"count": 1, "addresses": "04:000001", "battery": None, "battery_low": None,
               "last_seen": time.time(), "oldest_seen": time.time(), "online": False,
               "silent": "04:000001"}
    plug._write_trv_states(dev, summary, time.time())
    assert dev.errorState == ""


def test_no_state_write_in_the_plugin_bypasses_the_error_keeping_helper():
    """Every batch write goes through _write_states, and every single write passes
    clearErrorState=False, so a new write cannot quietly start wiping the error again."""
    import ast
    import os
    from conftest import SERVER_PLUGIN
    tree = ast.parse(open(os.path.join(SERVER_PLUGIN, "plugin.py"), encoding="utf-8").read())
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        for call in ast.walk(fn):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)):
                continue
            if call.func.attr not in ("updateStatesOnServer", "updateStateOnServer"):
                continue
            kws = {k.arg: k.value for k in call.keywords}
            flag = kws.get("clearErrorState")
            assert isinstance(flag, ast.Constant) and flag.value is False, \
                f"{fn.name} writes states without clearErrorState=False"
