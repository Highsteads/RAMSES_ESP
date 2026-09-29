#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_1_13_timetables.py
# Description: 1.13.0 - reading each zone's weekly timetable from the Evohome controller
#              (opcode 0404) once a day, and putting it on the zone device.
# Author:      CliveS & Claude Opus 5.5
# Date:        29-09-2026
# Version:     1.0

import os
import sys
from datetime import datetime

import pytest

_SP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                   "RAMSES_ESP.indigoPlugin", "Contents", "Server Plugin")
if _SP not in sys.path:
    sys.path.insert(0, _SP)

import ramses_timetable as tt   # noqa: E402

# A real exchange published in ramses_rf's test data (tests_rf/data_driven/schedules/sched_001),
# with the schedule ramses_rf records for it (schedule.json): weekdays 6:30am 21, 8am 18, 3:30pm 21,
# 10:30pm 16; Saturday and Sunday 8am 21, 10am 21, 6pm 21, 11pm 16.
SAMPLE = [
    "0120000829010368816DCCC91183301005D1D93428200E1C7D720C04402C0442640E82000C851701ADD3AFAED1131151",
    "0120000829020339DEBC8DBE1EFBDB5EDBA8DDB92DBEDFADDAB6671179E4FF4EC153F0143C05CFC033F00C3C03CFC173",
    "01200008270303F01C3C072FC00BF002BC00AF7CFEB6DEDE46BBB721EE6DBA78095E8297E0E5CF5BF50DA0291B9C",
]
SAMPLE_DAY = [(390, 21.0), (480, 18.0), (930, 21.0), (1350, 16.0)]
SAMPLE_WEEKEND = [(480, 21.0), (600, 21.0), (1080, 21.0), (1380, 16.0)]
SAMPLE_WEEK = {**{d: SAMPLE_DAY for d in range(5)}, 5: SAMPLE_WEEKEND, 6: SAMPLE_WEEKEND}


def _sample_week():
    return tt.decode([tt.parse_reply(p)[3] for p in SAMPLE])


# ==========================================================================
# The pure module
# ==========================================================================

def test_the_request_matches_ramses_rf():
    assert tt.build_request(1, 1, 0) == "01200008000100"
    assert tt.build_request(1, 2, 3) == "01200008000203"


def test_a_reply_is_split_into_its_parts():
    zone, frag, total, data = tt.parse_reply(SAMPLE[0])
    assert (zone, frag, total) == (1, 1, 3)
    assert data.startswith("68816D")


def test_a_payload_that_is_not_a_timetable_is_refused():
    assert tt.parse_reply("0120") is None
    assert tt.parse_reply("01230008290103AA") is None      # a hot-water header
    assert tt.parse_reply("0120000829040300") is None      # fragment 4 of 3


def test_the_published_sample_decodes_as_ramses_rf_says():
    assert _sample_week() == SAMPLE_WEEK


def test_a_stream_that_does_not_decompress_is_a_value_error():
    with pytest.raises(ValueError):
        tt.decode(["00FF00FF"])


def test_json_round_trips():
    week = _sample_week()
    assert tt.from_json(tt.to_json(week)) == week


def test_the_description_reads_as_a_person_says_it():
    week = {d: [(0, 16.0), (1430, 16.0)] for d in range(7)}
    assert tt.describe(week) == "Every day: midnight 16, 11:50pm 16."
    week = {d: list(SAMPLE_DAY) for d in range(7)}
    assert tt.describe(week) == "Every day: 6:30am 21, 8am 18, 3:30pm 21, 10:30pm 16."
    week[6] = [(720, 20.5)]
    assert tt.describe(week).startswith("Monday, Tuesday, Wednesday, Thursday, Friday and Saturday: ")
    assert tt.describe(week).endswith("Sunday: noon 20.5.")


def test_the_setpoint_in_force_wraps_past_midnight():
    week = {d: [(300, 17.0), (1320, 16.0)] for d in range(7)}
    slots = tt.effective(week)
    assert len(slots) == 7 * tt.SLOTS_PER_DAY
    assert slots[0] == 16.0                      # Monday midnight: Sunday's 10pm value
    assert slots[30] == 17.0                     # Monday 5am
    assert slots[132] == 16.0                    # Monday 10pm


# ==========================================================================
# The plugin: when to read, reading, and publishing
# ==========================================================================

def test_it_reads_once_a_day_after_quarter_past_three(rp):
    due = rp.Plugin._timetable_due
    today = "2026-10-05"
    assert due(datetime(2026, 10, 5, 3, 14), "2026-10-04", False, 999) is False
    assert due(datetime(2026, 10, 5, 3, 15), "2026-10-04", False, 999) is True
    assert due(datetime(2026, 10, 5, 9, 0), today, False, 999) is False
    assert due(datetime(2026, 10, 5, 9, 0), today, True, 999) is True, "on request"


def test_a_first_install_reads_soon_after_starting(rp):
    due = rp.Plugin._timetable_due
    assert due(datetime(2026, 10, 5, 14, 0), "", False, 30) is False
    assert due(datetime(2026, 10, 5, 14, 0), "", False, 200) is True


class FakeZone:
    def __init__(self, dev_id, name, states=None):
        self.id, self.name, self.address = dev_id, name, "1"
        self.states = dict(states or {})

    def updateStatesOnServer(self, states, clearErrorState=True):
        for s in states:
            self.states[s["key"]] = s["value"]


@pytest.fixture
def reading(plug, monkeypatch):
    """A plug whose 'radio' answers each RQ 0404 from the published sample."""
    plug.gateway_id = "18:000001"
    plug.controller_id = "01:145038"
    plug.mqtt_connected = True
    sent = []

    def publish(msg):
        sent.append(msg)
        payload = msg.split()[-1]
        zone, frag = int(payload[0:2], 16), int(payload[10:12], 16)
        if zone == 1:
            fields = ["042", "RP", "---", "01:145038", "18:000001", "--:------", "0404", "048",
                      SAMPLE[frag - 1]]
            plug._note_timetable_reply(fields, SAMPLE[frag - 1])
        return True

    monkeypatch.setattr(plug, "_publish_raw", publish)
    monkeypatch.setattr(sys.modules["plugin"], "TIMETABLE_ASK_TIMEOUT", 0.05, raising=False)
    monkeypatch.setattr(sys.modules["plugin"], "TIMETABLE_ASK_GAP", 0.0, raising=False)
    return plug, sent


def test_the_reader_collects_every_fragment(reading):
    plug, sent = reading
    assert plug._timetable_lock.acquire(blocking=False)
    plug._read_timetables_worker([1])
    results, failed = plug._timetable_results
    assert failed == [] and results[1][0] == SAMPLE_DAY
    assert [m.split()[-1][10:14] for m in sent] == ["0100", "0203", "0303"]
    assert not plug._timetable_lock.locked(), "released for the next read"


def test_a_zone_that_never_answers_is_reported_not_hung(reading):
    plug, sent = reading
    plug._timetable_lock.acquire()
    plug._read_timetables_worker([1, 5])
    results, failed = plug._timetable_results
    assert list(results) == [1] and failed == [5]


def test_replies_are_ignored_when_no_read_is_running(reading):
    plug, _sent = reading
    fields = ["042", "RP", "---", "01:145038", "18:000001", "--:------", "0404", "048", SAMPLE[0]]
    plug._note_timetable_reply(fields, SAMPLE[0])
    assert plug._timetable_replies.empty()


def test_a_neighbours_timetable_is_ignored(reading):
    plug, _sent = reading
    plug._timetable_lock.acquire()
    try:
        fields = ["042", "RP", "---", "01:999999", "18:000001", "--:------", "0404", "048", SAMPLE[0]]
        plug._note_timetable_reply(fields, SAMPLE[0])
        assert plug._timetable_replies.empty()
    finally:
        plug._timetable_lock.release()


def test_results_are_published_on_the_zone_device(plug, monkeypatch):
    dev = FakeZone(11, "Dining Room Radiator", {"timetableData": ""})
    monkeypatch.setattr(plug, "_find_zone_device", lambda z: dev)
    plug._timetable_results = ({1: _sample_week()}, [])
    plug._apply_timetable_results(datetime(2026, 10, 5, 3, 16))
    assert dev.states["timetable"] == (
        "Monday, Tuesday, Wednesday, Thursday and Friday: 6:30am 21, 8am 18, 3:30pm 21, "
        "10:30pm 16. Saturday and Sunday: 8am 21, 10am 21, 6pm 21, 11pm 16.")
    assert tt.from_json(dev.states["timetableData"]) == _sample_week()
    assert dev.states["timetableRead"] == "2026-10-05 03:16"
    assert plug._timetable_last_date == "2026-10-05"
    plug.logger.info.assert_not_called()          # the first read is not a change


def test_a_changed_timetable_is_said_once(plug, monkeypatch):
    old = tt.to_json({d: [(0, 16.0)] for d in range(7)})
    dev = FakeZone(11, "Dining Room Radiator", {"timetableData": old})
    monkeypatch.setattr(plug, "_find_zone_device", lambda z: dev)
    plug._timetable_results = ({1: _sample_week()}, [])
    plug._apply_timetable_results(datetime(2026, 10, 5, 3, 16))
    assert "has changed" in plug.logger.info.call_args.args[0]


def test_a_failed_zone_warns_and_the_read_is_retried(plug, monkeypatch):
    dev = FakeZone(11, "Dining Room Radiator")
    monkeypatch.setattr(plug, "_find_zone_device", lambda z: dev)
    plug._timetable_results = ({}, [9])
    plug._apply_timetable_results(datetime(2026, 10, 5, 3, 16))
    assert "Dining Room Radiator" in plug.logger.warning.call_args.args[0]
    assert plug._timetable_last_date == "", "not marked done, so it reads again"


def test_the_action_and_menu_are_declared():
    import xml.etree.ElementTree as ET
    actions = ET.parse(os.path.join(_SP, "Actions.xml")).getroot()
    menus = ET.parse(os.path.join(_SP, "MenuItems.xml")).getroot()
    assert any(a.get("id") == "readTimetables" for a in actions)
    assert any(m.get("id") == "menuReadTimetables" for m in menus)
    states = {s.get("id") for s in ET.parse(os.path.join(_SP, "Devices.xml")).getroot().iter("State")}
    assert {"timetable", "timetableData", "timetableRead"} <= states
