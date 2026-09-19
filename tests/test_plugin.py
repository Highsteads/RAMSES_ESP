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


# --------------------------------------------------------------------------
# Dispatch verification (v1.8.0) — a plug command counts only once the plug moves
#
# indigo.device.turnOff()/turnOn() raise nothing when the command never reaches the
# plug. On 19-Sep-2026 that let the watchdog "cycle" an unreachable plug three times,
# announce each one, spend the daily cap and ask for a human it did not need. Every
# test below fails on the pre-1.8.0 code.
# --------------------------------------------------------------------------

class FakePlug:
    """Stands in for an Indigo relay device, with only what the watchdog reads."""

    def __init__(self, on=True, enabled=True, error_state="", online=None, reports_state=True):
        self.enabled    = enabled
        self.errorState = error_state
        # A relay always carries the native onState, which is why the picker is filtered to
        # indigo.relay. reports_state=False models the defensive case only: a device that does
        # not model on/off at all, so there is nothing to verify against.
        self.onState    = on if reports_state else None
        self.states     = {}
        if reports_state:
            self.states["onOffState"] = on
        if online is not None:
            self.states["deviceOnline"] = online

    def set(self, on):
        self.onState = on
        if "onOffState" in self.states:
            self.states["onOffState"] = on


@pytest.fixture
def wd(plug, rp, monkeypatch):
    """A plugin armed for watchdog work, with a fake plug wired into indigo.devices."""
    monkeypatch.setattr(rp, "WD_VERIFY_SECONDS", 0.05)
    monkeypatch.setattr(rp, "WD_VERIFY_POLL", 0.01)
    plug.wd_enabled         = True
    plug.wd_plug_id         = 123
    plug.wd_offline_minutes = 15
    plug.wd_off_seconds     = 10
    plug.wd_max_cycles      = 3
    plug.wd_last_cycle_ts   = 0.0
    plug.wd_cycle_day       = ""
    plug.wd_cycles_today    = 0
    plug.wd_gave_up_alerted  = False
    plug.wd_no_cycle_streak  = 0
    plug.wd_no_cycle_alerted = False
    plug.slept = []
    def _sleep(seconds):
        plug.slept.append(seconds)
        time.sleep(min(seconds, 0.01))
    plug.sleep = _sleep
    plug._send_watchdog_pushover = _Recorder()
    plug._persist_watchdog_state = lambda: None
    rp.indigo.device.reset_mock()
    return plug


class _Recorder:
    """Captures Pushover calls so a test can assert what was (and was not) announced."""

    def __init__(self):
        self.calls = []

    def __call__(self, title, message, priority="0"):
        self.calls.append((title, message, priority))

    def titles(self):
        return [t for t, _m, _p in self.calls]


def _wire(rp, dev):
    rp.indigo.devices.__getitem__ = lambda _self, _key: dev


def _wire_live(rp, dev):
    """Wire a plug whose relay commands actually move it, as a working plug would."""
    _wire(rp, dev)
    rp.indigo.device.turnOff.side_effect = lambda _id: dev.set(False)
    rp.indigo.device.turnOn.side_effect  = lambda _id: dev.set(True)


def _wire_deaf(rp, dev):
    """Wire a plug that accepts commands without raising and never actually moves —
    exactly what an unreachable Shelly looks like from inside Indigo."""
    _wire(rp, dev)
    rp.indigo.device.turnOff.side_effect = None
    rp.indigo.device.turnOn.side_effect  = None


# --- _scalar_bool: only a real scalar is an answer -------------------------

def test_scalar_bool_reads_real_values(plug):
    assert plug._scalar_bool(True) is True
    assert plug._scalar_bool(False) is False
    assert plug._scalar_bool(1) is True
    assert plug._scalar_bool(0) is False

def test_scalar_bool_handles_the_v2_api_string_bools(plug):
    """The v2 API hands custom states back as the STRINGS "True"/"False", and bool("False")
    is True — the trap this helper exists to close."""
    assert plug._scalar_bool("False") is False
    assert plug._scalar_bool("True") is True

def test_scalar_bool_says_cannot_tell_for_a_non_scalar(plug):
    """An absent or proxy value must NOT read as OFF. Confident-wrong is the whole bug."""
    assert plug._scalar_bool(None) is None
    assert plug._scalar_bool(object()) is None


# --- reachability pre-flight ----------------------------------------------

def test_unreachable_when_plugin_reports_offline(wd, rp):
    assert "deviceOnline=False" in wd._plug_unreachable_reason(FakePlug(online=False))

def test_unreachable_when_offline_arrives_as_a_string(wd):
    assert wd._plug_unreachable_reason(FakePlug(online="False")) != ""

def test_unreachable_when_disabled(wd):
    assert "disabled" in wd._plug_unreachable_reason(FakePlug(enabled=False))

def test_unreachable_when_indigo_has_an_error_state(wd):
    assert "no ack" in wd._plug_unreachable_reason(FakePlug(error_state="no ack"))

def test_reachable_when_online(wd):
    assert wd._plug_unreachable_reason(FakePlug(online=True)) == ""

def test_silence_is_not_a_reason_to_refuse(wd):
    """A plug that publishes no reachability state is not evidence of an offline plug —
    the watchdog must still try."""
    assert wd._plug_unreachable_reason(FakePlug()) == ""


# --- _power_cycle_plug returns what the plug did, not what was called ------

def test_power_cycle_reports_false_when_the_plug_never_moves(wd, rp):
    dev = FakePlug(on=True)
    _wire_deaf(rp, dev)
    assert wd._power_cycle_plug() is False
    rp.indigo.device.turnOff.assert_called_once_with(123)
    assert dev.onState is True                    # still powered — nothing was cut

def test_a_lost_off_raises_no_false_alarm(wd, rp):
    """NEEDS HELP means the gateway is stranded without power. A command that never landed
    leaves it powered, so that alert must not fire."""
    _wire_deaf(rp, FakePlug(on=True))
    wd._power_cycle_plug()
    assert wd._send_watchdog_pushover.titles() == []

def test_a_lost_off_does_not_wait_out_the_off_window(wd, rp):
    """If the OFF never landed the plug still has power, so there is no off-window to sit
    through — waiting one out just blocks the main loop for nothing."""
    _wire_deaf(rp, FakePlug(on=True))
    wd.wd_off_seconds = 10
    wd._power_cycle_plug()
    assert 10 not in wd.slept

def test_power_cycle_reports_true_when_the_plug_moves(wd, rp):
    dev = FakePlug(on=True)
    _wire_live(rp, dev)
    assert wd._power_cycle_plug() is True
    assert dev.onState is True                    # cut, then restored
    rp.indigo.device.turnOff.assert_called_once_with(123)
    rp.indigo.device.turnOn.assert_called_once_with(123)

def test_power_cycle_still_unverified_when_the_plug_reports_nothing(wd, rp):
    """A device with no on/off state cannot be checked. That is 'cannot tell', not 'failed' —
    the watchdog must keep working, unverified, rather than refusing to cycle for ever."""
    _wire(rp, FakePlug(reports_state=False))
    rp.indigo.device.turnOff.side_effect = None
    rp.indigo.device.turnOn.side_effect  = None
    assert wd._power_cycle_plug() is None

def test_needs_help_still_fires_when_power_was_really_cut(wd, rp):
    """The real emergency: the OFF landed, the ON did not."""
    dev = FakePlug(on=True)
    _wire(rp, dev)
    rp.indigo.device.turnOff.side_effect = lambda _id: dev.set(False)
    rp.indigo.device.turnOn.side_effect  = None      # refuses to come back
    assert wd._power_cycle_plug() is True
    assert "RAMSES watchdog NEEDS HELP" in wd._send_watchdog_pushover.titles()


# --- _watchdog_tick: the 19-Sep-2026 outage, replayed ---------------------

def test_tick_does_not_cycle_or_announce_an_unreachable_plug(wd, rp):
    """The live failure. The plug was reported offline before the first cycle, so all three
    attempts should have been skipped and nothing announced."""
    _wire_deaf(rp, FakePlug(online=False))
    now = time.time()
    wd._watchdog_tick(now - 20 * 60)
    assert wd.wd_cycles_today == 0                      # cap not spent
    assert wd._send_watchdog_pushover.titles() == []    # nothing claimed
    rp.indigo.device.turnOff.assert_not_called()        # no blind command sent

def test_tick_does_not_count_a_cycle_whose_command_was_lost(wd, rp):
    """A reachable-looking plug that silently swallows the command still must not count."""
    _wire_deaf(rp, FakePlug(on=True, online=True))
    wd._watchdog_tick(time.time() - 20 * 60)
    assert wd.wd_cycles_today == 0
    assert "RAMSES watchdog power-cycled gateway" not in wd._send_watchdog_pushover.titles()

def test_tick_counts_and_announces_a_real_cycle(wd, rp):
    _wire_live(rp, FakePlug(on=True, online=True))
    wd._watchdog_tick(time.time() - 20 * 60)
    assert wd.wd_cycles_today == 1
    assert "RAMSES watchdog power-cycled gateway" in wd._send_watchdog_pushover.titles()
    assert wd.wd_no_cycle_streak == 0

def test_repeated_skips_escalate_once_and_name_the_real_problem(wd, rp):
    """After the cap's worth of attempts the user does hear about it — but told that the plug
    is unreachable, not that the gateway was cycled and needs a human."""
    _wire_deaf(rp, FakePlug(online=False))
    for _ in range(5):
        wd.wd_last_cycle_ts = 0.0                       # let the spacing allow another attempt
        wd._watchdog_tick(time.time() - 60 * 60)
    titles = wd._send_watchdog_pushover.titles()
    assert titles.count("RAMSES watchdog cannot cycle the plug") == 1
    assert "RAMSES watchdog power-cycled gateway" not in titles
    assert wd.wd_cycles_today == 0

def test_a_skipped_attempt_keeps_the_normal_spacing(wd, rp):
    """A skip must not turn into a retry on every main-loop pass."""
    _wire_deaf(rp, FakePlug(online=False))
    before = wd.wd_last_cycle_ts
    wd._watchdog_tick(time.time() - 20 * 60)
    assert wd.wd_last_cycle_ts > before

def test_gateway_back_online_rearms_the_no_cycle_latches(wd):
    wd.wd_no_cycle_alerted = True
    wd.wd_no_cycle_streak  = 7
    assert wd._watchdog_decision(time.time(), None) == "idle"
    assert wd.wd_no_cycle_alerted is False
    assert wd.wd_no_cycle_streak == 0

def test_giveup_reports_the_cycles_that_really_happened(wd, rp):
    """The give-up text must count real cycles, not the cap it was compared against."""
    now = time.time()
    wd.wd_cycle_day     = time.strftime("%Y-%m-%d", time.localtime(now))
    # The two numbers must DIFFER, or the assertion cannot tell which one was printed.
    wd.wd_max_cycles    = 2
    wd.wd_cycles_today  = 5
    wd.wd_last_cycle_ts = now - 20 * 60
    wd._watchdog_tick(now - 60 * 60)
    body = [m for t, m, _p in wd._send_watchdog_pushover.calls if t == "RAMSES watchdog giving up"]
    assert body, "no give-up alert was sent"
    assert "after 5 power cycle(s)" in body[0]
