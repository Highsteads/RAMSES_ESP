#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_1_14_fixes.py
# Description: 1.14.0 - a deleted boiler relay stays deleted, the MQTT lock is never held
#              while paho's thread is stopped, and the boiler relay logs one line an hour
#              instead of one per switch.
# Author:      CliveS & Claude Opus 5.5
# Date:        29-09-2026
# Version:     1.0

from datetime import datetime
from unittest.mock import MagicMock


# ruff: noqa: F811 - the shared 'fake' fixture is imported by name, and each test takes it
# as a parameter of the same name, which is how pytest finds it.
from test_relay import FakeRelay, RELAY_OFF, RELAY_ON, _feed, fake  # noqa: F401


# ==========================================================================
# A deleted relay stays deleted
# ==========================================================================

def test_a_deleted_relay_is_not_created_again(fake):
    plug, devices, created = fake
    _feed(plug, RELAY_OFF)
    plug._publish_relay_states()
    dev = created[0]
    plug.deviceDeleted(dev)
    del devices.by_id[dev.id]
    _feed(plug, RELAY_ON)
    plug._publish_relay_states()
    assert len(created) == 1, "not recreated from the next message"
    assert "13:123456" in plug.ignored_relays


def test_the_deleted_list_survives_a_restart(fake):
    plug, _devices, created = fake
    _feed(plug, RELAY_OFF)
    plug._publish_relay_states()
    plug.deviceDeleted(created[0])
    assert plug.pluginPrefs["ignoredRelays"] == "13:123456"
    plug.ignored_relays = set()
    plug.pluginPrefs["mqtt_broker_host"] = "192.168.1.10"
    plug._read_prefs()
    assert plug.ignored_relays == {"13:123456"}


def test_bringing_deleted_relays_back(fake):
    plug, devices, created = fake
    _feed(plug, RELAY_OFF)
    plug._publish_relay_states()
    plug.deviceDeleted(created[0])
    del devices.by_id[created[0].id]
    plug.menuRestoreDeletedRelays()
    _feed(plug, RELAY_ON)
    plug._publish_relay_states()
    assert len(created) == 2
    assert plug.pluginPrefs["ignoredRelays"] == ""


# ==========================================================================
# Never hold mqtt_lock while stopping paho's thread
# ==========================================================================

class _ClientNeedingTheLock:
    """Stands in for paho: stopping its thread waits for that thread, which on first
    gateway discovery is itself waiting for mqtt_lock."""

    def __init__(self, plug):
        self.plug = plug
        self.got_lock = None

    def loop_stop(self):
        self.got_lock = self.plug.mqtt_lock.acquire(timeout=1)
        if self.got_lock:
            self.plug.mqtt_lock.release()

    def disconnect(self):
        pass


def test_reconnecting_does_not_hold_the_lock_while_stopping(plug, rp, monkeypatch):
    client = _ClientNeedingTheLock(plug)
    plug.mqtt_client = client
    monkeypatch.setattr(rp.mqtt, "Client", MagicMock())
    plug._mqtt_connect()
    assert client.got_lock is True


def test_disconnecting_does_not_hold_the_lock_while_stopping(plug):
    client = _ClientNeedingTheLock(plug)
    plug.mqtt_client = client
    plug._mqtt_disconnect()
    assert client.got_lock is True
    assert plug.mqtt_client is None


# ==========================================================================
# One boiler line an hour
# ==========================================================================

def _ts(h, m, s=0):
    return datetime(2026, 10, 20, h, m, s).timestamp()


def _run(plug, dev, pattern):
    """pattern: [(timestamp, on)] fed to the hour accounting in order."""
    for ts, on in pattern:
        plug._account_relay_hour(dev, {"onOffState": on}, ts)


def test_an_hour_of_bursts_is_one_line(plug):
    dev = FakeRelay(7, "Boiler Relay", "13:123456")
    pattern = []
    for burst in range(5):                           # five 4-minute calls between 7 and 8
        start = 7 * 60 + burst * 10
        for minute in range(start, start + 10):
            for sec in range(0, 60, 5):
                pattern.append((_ts(minute // 60, minute % 60, sec), minute < start + 4))
    pattern.append((_ts(8, 0, 5), False))
    _run(plug, dev, pattern)
    lines = [c.args[0] for c in plug.logger.info.call_args_list]
    assert lines == ["Boiler Relay: the boiler was called for heat for 20 minutes "
                     "between 7am and 8am, in 5 separate calls."]


def test_a_quiet_hour_says_nothing(plug):
    dev = FakeRelay(7, "Boiler Relay", "13:123456")
    _run(plug, dev, [(_ts(3, 0), False), (_ts(3, 30), False), (_ts(4, 0, 5), False)])
    plug.logger.info.assert_not_called()


def test_a_call_running_on_from_the_hour_before(plug):
    line = plug._relay_hour_sentence("Boiler Relay", datetime(2026, 10, 20, 11, 0), 720, 0)
    assert line == ("Boiler Relay: the boiler was called for heat for 12 minutes between "
                    "11am and noon, carrying on from the hour before.")


def test_a_whole_hour_and_one_call(plug):
    line = plug._relay_hour_sentence("Boiler Relay", datetime(2026, 10, 20, 23, 0), 3600, 1)
    assert line == ("Boiler Relay: the boiler was called for heat for the whole hour between "
                    "11pm and midnight, in one call.")


def test_a_stalled_loop_does_not_invent_burner_time(plug):
    dev = FakeRelay(7, "Boiler Relay", "13:123456")
    _run(plug, dev, [(_ts(9, 0), True), (_ts(9, 40), True), (_ts(10, 0, 5), False)])
    line = plug.logger.info.call_args.args[0]
    assert "for 2 minutes" in line, line


def test_the_switch_line_is_now_debug(fake):
    plug, _devices, created = fake
    _feed(plug, RELAY_OFF)
    plug._publish_relay_states()
    _feed(plug, RELAY_ON)
    plug._publish_relay_states()
    assert not any("Calling the boiler" in c.args[0] for c in plug.logger.info.call_args_list)
    assert any("Calling the boiler" in c.args[0] for c in plug.logger.debug.call_args_list)
