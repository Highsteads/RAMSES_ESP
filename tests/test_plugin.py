#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_plugin.py
# Description: Contract tests for the RAMSES_ESP plugin's pure logic — RAMSES-II decoders,
#              the W 2349 setpoint encoder, the gateway-id sanitiser, the timestamp helper,
#              and the power-cycle watchdog state machine (incl. the crash-safe restore).
#              No live Indigo server or gateway is required.
# Author:      CliveS & Claude Opus 4.8
# Date:        26-06-2026
# Version:     1.0

import time

import pytest


# --------------------------------------------------------------------------
# _parse_temp_bytes — 16-bit big-endian signed, value/100 degC, 0x7FFF = unknown
# --------------------------------------------------------------------------

def test_temp_positive(plug):
    assert plug._parse_temp_bytes("0866", 0) == pytest.approx(21.5)   # 0x0866 = 2150

def test_temp_negative(plug):
    # 0xFE0C = 65036 -> 65036 - 65536 = -500 -> -5.00 degC
    assert plug._parse_temp_bytes("FE0C", 0) == pytest.approx(-5.0)

def test_temp_unknown_sentinel_is_none(plug):
    assert plug._parse_temp_bytes("7FFF", 0) is None

def test_temp_short_payload_is_none(plug):
    assert plug._parse_temp_bytes("08", 0) is None

def test_temp_byte_offset(plug):
    # A real 30C9 3-byte block is ZZTTTT: byte 0 = zone, bytes 1-2 = temp.
    # Offset 1 reads hex chars 2..5 — the "0866" after the "00" zone byte.
    assert plug._parse_temp_bytes("000866", 1) == pytest.approx(21.5)


# --------------------------------------------------------------------------
# _encode_2349_setpoint — ZZ XXXX MM FFFFFF
# --------------------------------------------------------------------------

def test_encode_zone1_215(rp):
    assert rp.Plugin._encode_2349_setpoint(1, 21.5) == "01086602FFFFFF"

def test_encode_zone0_frost_floor(rp):
    # 8.0 degC -> 800 -> 0x0320
    assert rp.Plugin._encode_2349_setpoint(0, 8.0) == "00032002FFFFFF"

def test_encode_clamps_high(rp):
    # Absurd setpoint clamps to TEMP_UNKNOWN_RAW - 1 = 0x7FFE
    assert rp.Plugin._encode_2349_setpoint(0, 400.0) == "007FFE02FFFFFF"

def test_encode_clamps_negative_to_zero(rp):
    assert rp.Plugin._encode_2349_setpoint(0, -5.0) == "00000002FFFFFF"


# --------------------------------------------------------------------------
# _sanitise_gateway_id
# --------------------------------------------------------------------------

def test_gw_valid(rp):
    assert rp.Plugin._sanitise_gateway_id("18:203052") == "18:203052"

def test_gw_corrupted_double(rp):
    assert rp.Plugin._sanitise_gateway_id("18:20305218:203052") == "18:203052"

def test_gw_whitespace(rp):
    assert rp.Plugin._sanitise_gateway_id("  18:203052  ") == "18:203052"

def test_gw_garbage(rp):
    assert rp.Plugin._sanitise_gateway_id("not-an-id") == ""

def test_gw_empty(rp):
    assert rp.Plugin._sanitise_gateway_id("") == ""


# --------------------------------------------------------------------------
# _format_ts — ISO parse, pre-NTP sentinel, fallback
# --------------------------------------------------------------------------

def test_format_ts_valid_iso(plug):
    out = plug._format_ts("2026-06-26T14:30:00+00:00")
    assert out.startswith("2026-06-26")

def test_format_ts_pre_ntp_uses_now(plug):
    out = plug._format_ts("1970-01-01T05:42:17+00:00")
    assert not out.startswith("1970")
    assert getattr(plug, "_ntp_warn_logged", False) is True

def test_format_ts_garbage_falls_back(plug):
    out = plug._format_ts("definitely not a date")
    assert len(out) >= 10   # a YYYY-MM-DD ... string, no exception


# --------------------------------------------------------------------------
# RAMSES domain codes must not become zones; unknown 2349 setpoint must not clobber
# --------------------------------------------------------------------------

_CTRL_FIELDS = ["045", "I", "---", "01:123456", "--:------", "--:------", "30C9", "003"]

def test_30c9_domain_code_skipped(plug):
    # zone 0xFC (boiler relay domain) must NOT create a pending zone entry
    fields = _CTRL_FIELDS + ["FC0866"]
    plug._parse_opcode_30c9(fields, "FC0866", "ts")
    assert plug.pending_updates == {}

def test_30c9_valid_zone_accepted(plug):
    fields = _CTRL_FIELDS + ["000866"]
    plug._parse_opcode_30c9(fields, "000866", "ts")
    assert plug.pending_updates[0]["temp"] == pytest.approx(21.5)

def test_2349_unknown_setpoint_not_carried(plug):
    # zone 0, setpoint 0x7FFF (unknown), mode 0x02 -> mode carried, setpoint NOT carried
    fields = ["045", "I", "---", "01:123456", "--:------", "--:------", "2349", "007", "007FFF02FFFFFF"]
    plug._parse_opcode_2349(fields, "007FFF02FFFFFF", "ts")
    assert "setpoint" not in plug.pending_updates[0]
    assert plug.pending_updates[0]["mode"] == "permanent override"

def test_2349_known_setpoint_carried(plug):
    fields = ["045", "I", "---", "01:123456", "--:------", "--:------", "2349", "007", "00086602FFFFFF"]
    plug._parse_opcode_2349(fields, "00086602FFFFFF", "ts")
    assert plug.pending_updates[0]["setpoint"] == pytest.approx(21.5)
    assert plug.pending_updates[0]["mode"] == "permanent override"

def test_2349_domain_code_skipped(plug):
    fields = ["045", "I", "---", "01:123456", "--:------", "--:------", "2349", "007", "FC086602FFFFFF"]
    plug._parse_opcode_2349(fields, "FC086602FFFFFF", "ts")
    assert plug.pending_updates == {}


# --------------------------------------------------------------------------
# 0004 zone-name decode — odd-length payload must not lose the whole name
# --------------------------------------------------------------------------

def test_0004_decodes_name(plug):
    # zone 00, pad 00, "office" = 6f6666696365
    plug._parse_opcode_0004(_CTRL_FIELDS + ["x"], "00006F6666696365", "ts")
    assert plug.pending_zone_names[0] == "office"

def test_0004_odd_length_does_not_raise(plug):
    # trailing half-byte trimmed; valid leading bytes still decode, no exception
    plug._parse_opcode_0004(_CTRL_FIELDS + ["x"], "00006F666669636", "ts")
    assert 0 in plug.pending_zone_names


# --------------------------------------------------------------------------
# Watchdog decision FSM — pure, no Indigo IO
# --------------------------------------------------------------------------

def _arm(plug, **over):
    plug.wd_enabled         = over.get("enabled", True)
    plug.wd_plug_id         = over.get("plug_id", 123)
    plug.wd_offline_minutes = over.get("offline_minutes", 15)
    plug.wd_max_cycles      = over.get("max_cycles", 3)
    plug.wd_last_cycle_ts   = over.get("last_cycle_ts", 0.0)
    plug.wd_cycle_day       = over.get("cycle_day", "")
    plug.wd_cycles_today    = over.get("cycles_today", 0)
    plug.wd_gave_up_alerted = over.get("gave_up", False)

def test_wd_disabled_idle(plug):
    _arm(plug, enabled=False)
    assert plug._watchdog_decision(1_000_000_000.0, 1_000_000_000.0 - 9999) == "idle"

def test_wd_no_plug_idle(plug):
    _arm(plug, plug_id=0)
    assert plug._watchdog_decision(1_000_000_000.0, 1_000_000_000.0 - 9999) == "idle"

def test_wd_online_idle_and_rearms(plug):
    _arm(plug, gave_up=True)
    assert plug._watchdog_decision(1_000_000_000.0, None) == "idle"
    assert plug.wd_gave_up_alerted is False   # re-armed for the next outage

def test_wd_offline_below_threshold_idle(plug):
    now = 1_000_000_000.0
    _arm(plug)
    assert plug._watchdog_decision(now, now - 5 * 60) == "idle"   # 5 < 15 min

def test_wd_offline_first_cycle(plug):
    now = 1_000_000_000.0
    _arm(plug)
    assert plug._watchdog_decision(now, now - 20 * 60) == "cycle"

def test_wd_spacing_blocks_immediate_recycle(plug):
    now = 1_000_000_000.0
    _arm(plug, last_cycle_ts=now - 60, cycle_day=time.strftime("%Y-%m-%d", time.localtime(now)))
    assert plug._watchdog_decision(now, now - 20 * 60) == "idle"   # last cycle only 1 min ago

def test_wd_cap_reached_giveup(plug):
    now = 1_000_000_000.0
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    _arm(plug, cycle_day=today, cycles_today=3, last_cycle_ts=now - 20 * 60)
    assert plug._watchdog_decision(now, now - 60 * 60) == "giveup"

def test_wd_new_day_resets_counter(plug):
    now = 1_000_000_000.0
    _arm(plug, cycle_day="2000-01-01", cycles_today=3, last_cycle_ts=now - 20 * 60)
    assert plug._watchdog_decision(now, now - 60 * 60) == "cycle"
    assert plug.wd_cycles_today == 0   # counter rolled over to the new day


# --------------------------------------------------------------------------
# Power-cycle: the plug must ALWAYS be switched back on — even on StopThread
# --------------------------------------------------------------------------

def test_power_cycle_normal_restores(plug, rp):
    plug.wd_plug_id    = 123
    plug.wd_off_seconds = 10
    plug.sleep = lambda _s: None
    rp.indigo.device.reset_mock()
    plug._power_cycle_plug()
    rp.indigo.device.turnOff.assert_called_once_with(123)
    rp.indigo.device.turnOn.assert_called_once_with(123)

def test_power_cycle_restores_even_on_stopthread(plug, rp):
    """The crash-safety guarantee: if the off-window sleep is interrupted by StopThread
    (plugin shutting down mid-cycle), the finally block must STILL switch the plug back on."""
    plug.wd_plug_id    = 123
    plug.wd_off_seconds = 10
    rp.indigo.device.reset_mock()

    def _boom(_s):
        raise plug.StopThread()
    plug.sleep = _boom

    with pytest.raises(plug.StopThread):
        plug._power_cycle_plug()

    rp.indigo.device.turnOff.assert_called_once_with(123)
    rp.indigo.device.turnOn.assert_called_once_with(123)   # restored despite StopThread
