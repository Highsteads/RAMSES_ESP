#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_1_16_temperature_seen.py
# Description: 1.16.0 - temperatureSeen moves only on a temperature report, so a
#              consumer can tell a current reading from a frozen one. lastSeen also
#              moves on setpoint and mode reports, which kept a stale reading fresh.
# Author:      CliveS & Claude Opus 5.5
# Date:        02-10-2026
# Version:     1.0

import os
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock

import pytest

OURS = "01:091567"
BUNDLE = os.path.join(os.path.dirname(__file__), "..", "RAMSES_ESP.indigoPlugin",
                      "Contents", "Server Plugin")


class FakeZone:
    def __init__(self):
        self.id, self.name, self.address, self.enabled = 1, "Hall Radiator", "4", True
        self.states = {"zoneControllerId": OURS, "setpointHeat": 18.0,
                       "temperatureInput1": 25.0, "zoneMode": "schedule",
                       "lastSeen": "2026-10-02 06:00:00",
                       "temperatureSeen": "2026-10-02 06:00:00"}

    def updateStatesOnServer(self, states, clearErrorState=True):
        for s in states:
            self.states[s["key"]] = s["value"]


@pytest.fixture
def zone(plug, monkeypatch):
    dev = FakeZone()
    plug.controller_id = OURS
    plug.mqtt_client = MagicMock()
    monkeypatch.setattr(plug, "_find_zone_device", lambda z: dev)
    monkeypatch.setattr(plug, "_format_ts", lambda ts: "2026-10-02 09:00:00")
    return plug, dev


def test_a_setpoint_report_leaves_the_temperature_time_alone(zone):
    plug, dev = zone
    plug._apply_setpoint_update(4, {"setpoint": 18.0, "ts": "", "controller_id": OURS})
    assert dev.states["lastSeen"] == "2026-10-02 09:00:00"
    assert dev.states["temperatureSeen"] == "2026-10-02 06:00:00"


def test_a_mode_report_leaves_the_temperature_time_alone(zone):
    plug, dev = zone
    plug._apply_mode_update(4, {"setpoint": 18.0, "mode": "schedule", "until": "",
                                "ts": "", "controller_id": OURS})
    assert dev.states["lastSeen"] == "2026-10-02 09:00:00"
    assert dev.states["temperatureSeen"] == "2026-10-02 06:00:00"


def test_a_temperature_report_moves_both(zone):
    plug, dev = zone
    plug._apply_temp_update(4, {"temp": 19.5, "ts": "", "controller_id": OURS})
    assert dev.states["temperatureInput1"] == 19.5
    assert dev.states["temperatureSeen"] == "2026-10-02 09:00:00"
    assert dev.states["lastSeen"] == "2026-10-02 09:00:00"


def test_the_state_is_declared_on_the_zone_device():
    root = ET.parse(os.path.join(BUNDLE, "Devices.xml")).getroot()
    zone = root.find("Device[@id='ramsesZoneThermostat']")
    ids = [s.get("id") for s in zone.find("States")]
    assert "temperatureSeen" in ids
