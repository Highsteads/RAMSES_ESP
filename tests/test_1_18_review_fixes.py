#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_1_18_review_fixes.py
# Description: 1.18.0 - the RAMSES ESP findings of the 17-Oct-2026 joint review with
#              EvoHomeControl: (1) a change by hand supersedes a waiting command of ours,
#              but a late echo of an earlier command of ours does not; (2) attribution is
#              judged against the last mode report, not against a setpoint a 2309 moved;
#              (3) Set Temporary Setpoint tells its caller whether the command left;
#              (4) times survive the clocks going back; (8) a failed timetable read backs off.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-10-2026
# Version:     1.0

import time
import types
from datetime import datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

OURS    = "01:091567"
GATEWAY = "18:203052"


class FakeZone:
    def __init__(self, states=None):
        self.id, self.name, self.address, self.enabled = 1006487156, "Bedroom 3 Radiator", "7", True
        self.states = {"zoneControllerId": OURS, "setpointHeat": 20.5,
                       "zoneMode": "schedule", "zoneOverrideUntil": ""}
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


def _until(minutes=120):
    return datetime.now().replace(second=0, microsecond=0) + timedelta(minutes=minutes)


def _mode(plug, setpoint, mode, until=""):
    plug._apply_mode_update(7, {"mode": mode, "until": until, "setpoint": setpoint,
                                "ts": "", "controller_id": OURS})


# ==========================================================================
# Finding 1: a change by hand supersedes a waiting command of ours
# ==========================================================================

def test_a_manual_change_drops_the_older_pending_command(zone):
    """The review's reproduction: pending 20 temporary, manual 22 permanent."""
    plug, dev = zone
    plug._validate_and_publish_setpoint(dev, 20.0, "set", until=_until())
    assert 7 in plug.pending_setpoints
    _mode(plug, 22.0, "permanent override")
    assert 7 not in plug.pending_setpoints, "superseded command still pending"


def test_the_retry_does_not_resend_a_superseded_command(zone):
    plug, dev = zone
    plug._validate_and_publish_setpoint(dev, 20.0, "set", until=_until())
    _mode(plug, 22.0, "permanent override")
    before = len(plug.mqtt_client.publish.call_args_list)
    plug._retry_setpoints(time.time() + 61)
    resent = plug.mqtt_client.publish.call_args_list[before:]
    assert resent == [], f"retry resent a superseded command: {resent}"


def test_a_dial_turned_while_ours_waits_supersedes_it(zone):
    """Turning a dial makes a temporary setting until the next timetable change - the
    same mode and end time as our command - at another temperature. It is the person's."""
    plug, dev = zone
    until = _until()
    end = until.strftime("%Y-%m-%d %H:%M")
    plug._validate_and_publish_setpoint(dev, 20.0, "set", until=until)
    _mode(plug, 22.5, "temporary override", end)
    assert 7 not in plug.pending_setpoints
    assert dev.states["setpointSource"] == "manual"


def test_a_late_echo_of_our_earlier_command_does_not_cancel_the_newer_one(zone):
    """We sent 20, then 21 for the same end; the controller now reports the 20 landing.
    That is ours, not a change by hand, so 21 must stay pending to be confirmed."""
    plug, dev = zone
    until = _until()
    end = until.strftime("%Y-%m-%d %H:%M")
    plug._validate_and_publish_setpoint(dev, 20.0, "set", until=until)
    plug._validate_and_publish_setpoint(dev, 21.0, "set", until=until)
    _mode(plug, 20.0, "temporary override", end)
    assert plug.pending_setpoints[7]["sp"] == 21.0
    assert dev.states["setpointSource"] == "indigo"


def test_our_own_command_reported_back_is_still_confirmed(zone):
    plug, dev = zone
    until = _until()
    plug._validate_and_publish_setpoint(dev, 20.0, "set", until=until)
    _mode(plug, 20.0, "temporary override", until.strftime("%Y-%m-%d %H:%M"))
    assert plug.pending_setpoints == {}
    assert dev.states["setpointSource"] == "indigo"


# ==========================================================================
# Finding 2: a 2309 between two 2349s no longer hides a change
# ==========================================================================

def test_a_change_first_seen_in_a_2309_is_still_attributed(zone):
    """The zone was permanent 20. The 2309 broadcast shows 22 first, and moves
    setpointHeat; the 2349 that follows (still permanent) must update the source."""
    plug, dev = zone
    dev.states.update({"zoneMode": "permanent override", "setpointHeat": 20.0})
    _mode(plug, 20.0, "permanent override")              # the last mode report seen
    dev.states["setpointSource"] = "timetable"
    plug._apply_setpoint_update(7, {"setpoint": 22.0, "ts": "", "controller_id": OURS})
    assert dev.states["setpointHeat"] == 22.0
    _mode(plug, 22.0, "permanent override")
    assert dev.states["setpointSource"] == "manual"


def test_the_same_holds_straight_after_a_restart(zone):
    """No 2349 seen yet: the 2309 itself keeps the pre-change baseline."""
    plug, dev = zone
    dev.states.update({"zoneMode": "permanent override", "setpointHeat": 20.0,
                       "setpointSource": "timetable"})
    plug._apply_setpoint_update(7, {"setpoint": 22.0, "ts": "", "controller_id": OURS})
    _mode(plug, 22.0, "permanent override")
    assert dev.states["setpointSource"] == "manual"


def test_a_repeat_of_the_last_mode_report_changes_nothing(zone):
    plug, dev = zone
    _mode(plug, 21.0, "permanent override")
    stamp = dev.states.get("setpointChangedAt")
    dev.states["setpointSource"] = "sentinel"
    _mode(plug, 21.0, "permanent override")
    assert dev.states["setpointSource"] == "sentinel"
    assert dev.states.get("setpointChangedAt") == stamp


# ==========================================================================
# Finding 3: the action says whether the command left
# ==========================================================================

def _action(dev, **props):
    return types.SimpleNamespace(deviceId=dev.id, props=props)


def test_the_action_reports_a_sent_command_as_accepted(zone):
    plug, dev = zone
    result = plug.action_set_temporary_setpoint(_action(dev, setpoint="20", minutes="120"), dev)
    assert result == {"accepted": True, "reason": ""}


def test_the_action_reports_an_offline_gateway_as_refused(zone):
    plug, dev = zone
    plug.gateway_online = False
    result = plug.action_set_temporary_setpoint(_action(dev, setpoint="20", minutes="120"), dev)
    assert result["accepted"] is False
    assert "offline" in result["reason"]
    assert 7 not in plug.pending_setpoints


def test_the_action_reports_a_bad_setpoint_as_refused(zone):
    plug, dev = zone
    result = plug.action_set_temporary_setpoint(_action(dev, setpoint="warm"), dev)
    assert result["accepted"] is False


# ==========================================================================
# Finding 4: times that survive the clocks going back
# ==========================================================================

def test_a_length_in_minutes_is_counted_in_real_minutes():
    """Two hours from 00:30 BST on 25-Oct-2026 (the night the clocks go back) ends at
    01:31 GMT - 121 real minutes. Adding to the wall clock gave 02:31, 181 minutes."""
    from plugin import Plugin
    start = datetime(2026, 10, 25, 0, 30, tzinfo=ZoneInfo("Europe/London")).timestamp()
    end = Plugin._end_after_minutes(start, 120)
    assert (end.hour, end.minute) == (1, 31)


def test_a_change_carries_its_moment_in_seconds(zone):
    plug, dev = zone
    before = int(time.time())
    _mode(plug, 22.0, "permanent override")
    epoch = dev.states["setpointChangedAtEpoch"]
    assert isinstance(epoch, int) and before <= epoch <= int(time.time())


# ==========================================================================
# Finding 8: a failed timetable read backs off
# ==========================================================================

def test_a_read_is_not_due_before_its_retry_time(plug):
    now = datetime(2026, 10, 24, 9, 0)
    assert plug._timetable_due(now, "2026-10-23", False, 999, retry_at=2000.0, now_epoch=1000.0) is False
    assert plug._timetable_due(now, "2026-10-23", False, 999, retry_at=2000.0, now_epoch=2001.0) is True


def test_a_request_still_reads_at_once(plug):
    now = datetime(2026, 10, 24, 9, 0)
    assert plug._timetable_due(now, "2026-10-23", True, 999, retry_at=9e12, now_epoch=0.0) is True


def test_a_failed_read_says_when_it_tries_again(zone):
    plug, dev = zone
    now = datetime(2026, 10, 24, 3, 20)
    texts = []
    for _ in range(3):
        plug._timetable_results = ({}, [7])
        plug._apply_timetable_results(now)
        texts.append(plug.logger.warning.call_args[0][0])
    assert "in 1 hour" in texts[0] and "in 1 hour" in texts[1]
    assert "tomorrow" in texts[2]
    assert plug._timetable_last_date == "2026-10-24"
    assert plug._timetable_retry_at == 0.0
