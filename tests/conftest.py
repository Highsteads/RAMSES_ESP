#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    conftest.py
# Description: pytest fixtures + a minimal `indigo` / `paho` stub so plugin.py can be
#              imported and its pure logic exercised with no live Indigo server or gateway.
# Author:      CliveS & Claude Opus 4.8
# Date:        26-06-2026
# Version:     1.0

import os
import sys
import types
from unittest.mock import MagicMock

import pytest

# --- Locate the bundle's Server Plugin dir (repo-relative, works in CI too) ---
_HERE          = os.path.dirname(os.path.abspath(__file__))
SERVER_PLUGIN  = os.path.abspath(
    os.path.join(_HERE, "..", "RAMSES_ESP.indigoPlugin", "Contents", "Server Plugin")
)


def _make_indigo_stub():
    """Build a stand-in `indigo` module with just enough surface for import + unit tests."""
    ind = types.ModuleType("indigo")

    class _PluginBase:
        class StopThread(Exception):
            pass

        def __init__(self, plugin_id, display_name, version, prefs):
            self.pluginId          = plugin_id
            self.pluginDisplayName = display_name
            self.pluginVersion     = version
            self.pluginPrefs       = prefs
            self.logger            = MagicMock()

        def sleep(self, _seconds):
            # Tests override this where the timing matters (e.g. StopThread injection).
            return None

        def deviceStartComm(self, dev):
            return None

        def deviceStopComm(self, dev):
            return None

    ind.PluginBase = _PluginBase
    ind.Dict       = dict
    ind.List       = list

    ind.kHvacMode = types.SimpleNamespace(
        Off=0, Heat=1, Cool=2, HeatCool=3, ProgramHeat=4, ProgramCool=5, ProgramHeatCool=6)
    ind.kThermostatAction = types.SimpleNamespace(
        SetHeatSetpoint=1, IncreaseHeatSetpoint=2, DecreaseHeatSetpoint=3,
        SetHvacMode=4, RequestStatusAll=5, RequestSetpoints=6,
        RequestTemperatures=7, RequestMode=8, RequestEquipmentState=9)
    ind.kProtocol      = types.SimpleNamespace(Plugin="plugin")
    ind.kStateImageSel = MagicMock()

    ind.server       = MagicMock()
    ind.devices      = MagicMock()
    ind.variables    = MagicMock()
    ind.device       = MagicMock()
    ind.activePlugin = MagicMock()
    return ind


# Stub indigo + paho BEFORE importing plugin (plugin.py does `class Plugin(indigo.PluginBase)`).
sys.modules["indigo"] = _make_indigo_stub()

_paho        = types.ModuleType("paho")
_paho_mqtt   = types.ModuleType("paho.mqtt")
_paho_client = types.ModuleType("paho.mqtt.client")
_paho_client.Client = MagicMock
sys.modules["paho"]            = _paho
sys.modules["paho.mqtt"]       = _paho_mqtt
sys.modules["paho.mqtt.client"] = _paho_client

sys.path.insert(0, SERVER_PLUGIN)

import plugin as ramses_plugin   # noqa: E402  (import after stubs are in place)


@pytest.fixture
def rp():
    """The imported plugin module (exposes Plugin + module-level constants)."""
    return ramses_plugin


@pytest.fixture
def plug():
    """A Plugin instance backed by the stubbed indigo and an empty prefs dict."""
    p = ramses_plugin.Plugin("uk.co.clives.ramses.esp", "RAMSES ESP", "1.4.0", {})
    p.logger = MagicMock()
    return p
