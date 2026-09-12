#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_trv.py
# Description: Contract tests for per-valve liveness and battery — the 1060 decode, the
#              zone attribution, the worst-case aggregation, and the restart grace that
#              stops a reload inventing a fault.
# Author:      CliveS & Claude Opus 5
# Date:        12-09-2026
# Version:     1.0
#
# The load-bearing test in here is the restart grace. Everything else fails loudly; that
# one fails by paging somebody at four in the morning about a valve that was working
# perfectly while the plugin was switched off.

import ast
import os
import sys

import pytest


_HERE = os.path.dirname(os.path.abspath(__file__))
_SP = os.path.abspath(os.path.join(_HERE, "..", "RAMSES_ESP.indigoPlugin",
                                   "Contents", "Server Plugin"))
if _SP not in sys.path:
    sys.path.insert(0, _SP)

import ramses_trv as T   # noqa: E402

HOUR = 3600.0
NOW = 1_000_000.0
MAX_ZONES = 12


def fields(src, dev2="--:------", dev3="01:091567", code="3150"):
    """A RAMSES message split the way the plugin splits it."""
    return ["---", "I", "---", src, dev2, dev3, code, "002", ""]


# ---------------------------------------------------------------------------
class TestParseBattery:
    """1060 decode. Anything it cannot read must come back as nothing at all."""

    def test_a_normal_reading(self):
        # level 0x94 = 148 -> 74%, flag 0x01 = not low
        assert T.parse_battery("00 94 01".replace(" ", "")) == (74, False)

    def test_a_low_battery_warning(self):
        assert T.parse_battery("001001") == (8, False)
        assert T.parse_battery("001000") == (8, True)

    def test_full(self):
        assert T.parse_battery("00C801") == (100, False)

    def test_an_unreported_level_is_none_but_the_flag_still_counts(self):
        pct, low = T.parse_battery("00FF00")
        assert pct is None
        assert low is True

    def test_a_level_above_the_range_is_not_a_reading(self):
        pct, _ = T.parse_battery("00FE01")
        assert pct is None, "254 halves to 127%, which is not a battery percentage"

    def test_a_payload_of_the_wrong_length_is_refused_outright(self):
        # Half-decoding an unfamiliar layout invents a percentage out of another field.
        for bad in ("", "0094", "0094010203", "00940"):
            assert T.parse_battery(bad) is None, bad

    def test_junk_is_refused(self):
        assert T.parse_battery("00ZZ01") is None
        assert T.parse_battery(None) is None
        assert T.parse_battery(1060) is None

    def test_case_and_whitespace_do_not_matter(self):
        assert T.parse_battery(" 009401 ") == T.parse_battery("009401")
        assert T.parse_battery("00c801") == T.parse_battery("00C801")


# ---------------------------------------------------------------------------
class TestZoneAttribution:
    """Byte 0 is the zone ONLY on a packet addressed to the controller."""

    def test_a_packet_to_the_controller_carries_its_zone(self):
        assert T.trv_zone_from_fields(fields("04:254255"), "0100", MAX_ZONES) == 1
        assert T.trv_zone_from_fields(fields("04:164295"), "090000", MAX_ZONES) == 9

    def test_a_self_addressed_packet_carries_no_zone(self):
        # A valve's own 30C9 is 04:x -> 04:x with byte 0 = 00 whatever the zone. Reading
        # it would file every such valve under zone 0.
        f = fields("04:254001", dev2="--:------", dev3="04:254001", code="30C9")
        assert T.trv_zone_from_fields(f, "00072E", MAX_ZONES) is None

    def test_a_packet_from_the_controller_is_not_a_valve_packet(self):
        f = fields("01:091567", dev3="01:091567", code="30C9")
        assert T.trv_zone_from_fields(f, "000866", MAX_ZONES) is None

    def test_a_domain_code_is_not_a_zone(self):
        # 0xF9 CH / 0xFA DHW / 0xFC boiler relay ride in the same byte.
        for dom in ("F900", "FA00", "FC00"):
            assert T.trv_zone_from_fields(fields("04:254255"), dom, MAX_ZONES) is None

    def test_the_last_real_zone_is_accepted_and_the_next_is_not(self):
        assert T.trv_zone_from_fields(fields("04:1"), "0B00", MAX_ZONES) == 11
        assert T.trv_zone_from_fields(fields("04:1"), "0C00", MAX_ZONES) is None

    def test_short_or_junk_payload(self):
        assert T.trv_zone_from_fields(fields("04:1"), "", MAX_ZONES) is None
        assert T.trv_zone_from_fields(fields("04:1"), "Z", MAX_ZONES) is None

    def test_trv_source(self):
        assert T.trv_source(fields("04:254255")) == "04:254255"
        assert T.trv_source(fields("01:091567")) is None
        assert T.trv_source(["---", "I"]) is None


# ---------------------------------------------------------------------------
class TestRecording:
    """A packet must never blank a fact learned from an earlier one."""

    def test_a_zoneless_packet_does_not_erase_a_learned_zone(self):
        r = T.TrvRegistry()
        r.record("04:aaa", NOW, zone=3)
        r.record("04:aaa", NOW + 10)                     # self-addressed, no zone
        assert r.zone_summary(3, NOW + 20, HOUR, 0.0)["count"] == 1

    def test_an_ordinary_packet_does_not_erase_a_battery_reading(self):
        r = T.TrvRegistry()
        r.record("04:aaa", NOW, zone=3, battery_pct=74, battery_low=False)
        r.record("04:aaa", NOW + 10, zone=3)
        assert r.zone_summary(3, NOW + 20, HOUR, 0.0)["battery"] == 74

    def test_last_seen_only_moves_forward(self):
        r = T.TrvRegistry()
        r.record("04:aaa", NOW, zone=1)
        r.record("04:aaa", NOW - 500, zone=1)            # an out-of-order stamp
        assert r.zone_summary(1, NOW, HOUR, 0.0)["last_seen"] == NOW

    def test_a_non_valve_address_is_ignored(self):
        r = T.TrvRegistry()
        r.record("01:091567", NOW, zone=1)
        assert r.addresses() == []


# ---------------------------------------------------------------------------
class TestZoneSummary:
    """A zone is only as healthy as its unhappiest valve."""

    def _two_valve_zone(self):
        r = T.TrvRegistry()
        r.record("04:aaa", NOW, zone=5, battery_pct=90, battery_low=False)
        r.record("04:bbb", NOW, zone=5, battery_pct=41, battery_low=True)
        return r

    def test_an_unknown_zone_returns_nothing_at_all(self):
        # Not a cheerful default: a device showing "online" for a zone with no known
        # valve is the exact failure this feature exists to remove.
        assert T.TrvRegistry().zone_summary(5, NOW, HOUR, 0.0) is None

    def test_battery_is_the_lowest_of_the_valves(self):
        s = self._two_valve_zone().zone_summary(5, NOW, HOUR, 0.0)
        assert s["battery"] == 41
        assert s["count"] == 2

    def test_any_valve_warning_makes_the_zone_warn(self):
        assert self._two_valve_zone().zone_summary(5, NOW, HOUR, 0.0)["battery_low"] is True

    def test_no_battery_reading_is_none_not_zero(self):
        r = T.TrvRegistry()
        r.record("04:aaa", NOW, zone=5)
        s = r.zone_summary(5, NOW, HOUR, 0.0)
        assert s["battery"] is None
        assert s["battery_low"] is None

    def test_one_silent_valve_makes_the_zone_not_online(self):
        r = self._two_valve_zone()
        s = r.zone_summary(5, NOW + 3 * HOUR, HOUR, 0.0)
        assert s["online"] is False
        assert "04:aaa" in s["silent"] and "04:bbb" in s["silent"]

    def test_the_oldest_sighting_is_what_counts(self):
        r = T.TrvRegistry()
        r.record("04:aaa", NOW, zone=5)
        r.record("04:bbb", NOW - 5 * HOUR, zone=5)
        s = r.zone_summary(5, NOW, HOUR, 0.0)
        assert s["online"] is False, "one quiet valve is a quiet zone"
        assert s["silent"] == "04:bbb"
        assert s["last_seen"] == NOW and s["oldest_seen"] == NOW - 5 * HOUR

    def test_all_recent_is_online(self):
        assert self._two_valve_zone().zone_summary(5, NOW + 60, HOUR, 0.0)["online"] is True


# ---------------------------------------------------------------------------
class TestRestartGrace:
    """Silence is only evidence if somebody was listening through it.

    A valve last heard before the plugin came up may have been transmitting happily all
    night into a receiver that was switched off. Judging it silent on the strength of a
    restored timestamp raises a fault about the plugin's own downtime.
    """

    def _stale_record(self):
        r = T.TrvRegistry()
        r.record("04:aaa", NOW - 9 * HOUR, zone=2)   # restored from disk, long ago
        return r

    def test_a_valve_last_heard_before_the_restart_is_unknown_not_silent(self):
        # Plugin started a minute ago, threshold 6 h: we have not listened long enough.
        s = self._stale_record().zone_summary(2, NOW, 6 * HOUR, NOW - 60)
        assert s["online"] is None
        assert s["silent"] == ""

    def test_once_we_have_listened_longer_than_the_threshold_it_is_silent(self):
        s = self._stale_record().zone_summary(2, NOW, 6 * HOUR, NOW - 7 * HOUR)
        assert s["online"] is False
        assert s["silent"] == "04:aaa"

    def test_a_valve_heard_since_the_restart_is_judged_at_once(self):
        # No need to wait: we heard it, then it stopped, and we were listening throughout.
        r = T.TrvRegistry()
        r.record("04:aaa", NOW - 7 * HOUR, zone=2)
        s = r.zone_summary(2, NOW, 6 * HOUR, NOW - 8 * HOUR)
        assert s["online"] is False

    def test_a_recent_valve_is_online_even_early_in_the_run(self):
        r = T.TrvRegistry()
        r.record("04:aaa", NOW - 60, zone=2)
        assert r.zone_summary(2, NOW, 6 * HOUR, NOW - 120)["online"] is True

    def test_one_unjudgeable_valve_holds_the_whole_zone_at_unknown(self):
        r = T.TrvRegistry()
        r.record("04:aaa", NOW - 30, zone=2)          # fine
        r.record("04:bbb", NOW - 9 * HOUR, zone=2)    # cannot say yet
        s = r.zone_summary(2, NOW, 6 * HOUR, NOW - 60)
        assert s["online"] is None, "unknown must not be rounded up to healthy"


# ---------------------------------------------------------------------------
class TestSilentSinceAndForget:
    def test_silent_since_lists_worst_first(self):
        r = T.TrvRegistry()
        r.record("04:aaa", NOW - 2 * HOUR, zone=1)
        r.record("04:bbb", NOW - 9 * HOUR, zone=1)
        r.record("04:ccc", NOW - 60, zone=1)
        out = r.silent_since(NOW, HOUR)
        assert [a for a, _ in out] == ["04:bbb", "04:aaa"]

    def test_forget_reports_whether_there_was_one(self):
        r = T.TrvRegistry()
        r.record("04:aaa", NOW, zone=1)
        assert r.forget("04:aaa") is True
        assert r.forget("04:aaa") is False
        assert r.zone_summary(1, NOW, HOUR, 0.0) is None


# ---------------------------------------------------------------------------
class TestPersistence:
    def test_round_trip(self):
        r = T.TrvRegistry()
        r.record("04:aaa", NOW, zone=4, battery_pct=61, battery_low=False)
        r2 = T.TrvRegistry()
        assert r2.load_dict(r.to_dict()) == 1
        assert r2.zone_summary(4, NOW, HOUR, 0.0)["battery"] == 61

    def test_one_corrupt_entry_does_not_cost_the_others(self):
        good = {"zone": 1, "last_seen": NOW, "battery_pct": 50,
                "battery_low": False, "battery_at": NOW}
        data = {"version": 1, "trv": {
            "04:aaa": good,
            "04:bad": {"zone": "not a number", "last_seen": "x"},
            "not-a-valve": good,
        }}
        r = T.TrvRegistry()
        assert r.load_dict(data) == 1
        assert r.addresses() == ["04:aaa"]

    def test_junk_document_loads_nothing_and_does_not_raise(self):
        for junk in (None, [], "nope", {}, {"trv": None}):
            assert T.TrvRegistry().load_dict(junk) == 0


# ---------------------------------------------------------------------------
class TestDescribe:
    """The sentence a person reads. Plain English, plurals right, plain ASCII."""

    def _sum(self, **kw):
        base = {"count": 1, "addresses": "04:aaa", "battery": 74, "battery_low": False,
                "last_seen": NOW, "oldest_seen": NOW, "online": True, "silent": ""}
        base.update(kw)
        return base

    def test_one_valve_answering(self):
        s = T.describe(self._sum(), NOW)
        assert s == "The valve answering. Battery 74%."

    def test_two_valves_say_both_and_lowest(self):
        s = T.describe(self._sum(count=2, addresses="04:aaa, 04:bbb"), NOW)
        assert "Both valves answering" in s and "Lowest battery 74%" in s

    def test_three_valves_are_counted(self):
        assert "All 3 valves" in T.describe(self._sum(count=3), NOW)

    def test_a_silent_valve_is_named_with_its_age(self):
        s = T.describe(self._sum(online=False, silent="04:bbb",
                                 oldest_seen=NOW - 9 * HOUR), NOW)
        assert "04:bbb has not been heard for 9 hours" in s

    def test_two_silent_valves_take_the_plural_verb(self):
        s = T.describe(self._sum(count=2, online=False, silent="04:aaa, 04:bbb",
                                 oldest_seen=NOW - 2 * HOUR), NOW)
        assert "have not been heard" in s

    def test_one_hour_is_singular(self):
        s = T.describe(self._sum(online=False, silent="04:bbb",
                                 oldest_seen=NOW - HOUR), NOW)
        assert "for an hour." in s and "1 hours" not in s

    def test_unknown_says_it_is_too_soon_rather_than_reassuring(self):
        s = T.describe(self._sum(online=None), NOW)
        assert "too soon since the restart" in s

    def test_no_battery_reading_says_so(self):
        assert "No battery reading yet" in T.describe(self._sum(battery=None), NOW)

    def test_a_low_warning_is_stated(self):
        assert "warning that its battery is low" in T.describe(self._sum(battery_low=True), NOW)

    def test_nothing_known_is_not_reassuring(self):
        assert T.describe(None, NOW) == "No valve heard for this zone yet."

    def test_every_sentence_is_plain_ascii_and_ends_in_a_full_stop(self):
        for kw in ({}, {"count": 2}, {"online": False, "silent": "04:b"},
                   {"online": None}, {"battery": None}, {"battery_low": True}):
            s = T.describe(self._sum(**kw), NOW)
            s.encode("ascii")
            assert s.endswith(".")
            assert "|" not in s and "=" not in s

    def test_hours_words(self):
        # An either-way assertion proves nothing — name the answer.
        assert T._hours_words(90) == "a minute"
        assert T._hours_words(60) == "a minute"
        assert T._hours_words(150) == "2 minutes"
        assert T._hours_words(3600) == "an hour"
        assert T._hours_words(7200) == "2 hours"
        assert T._hours_words(86400 * 3) == "3 days"
        assert T._hours_words(None) == "some time"


# ---------------------------------------------------------------------------
class TestPluginWiring:
    """Read from the parsed tree — these are arrangements no unit test enters."""

    @classmethod
    def setup_class(cls):
        with open(os.path.join(_SP, "plugin.py"), encoding="utf-8") as fh:
            cls.tree = ast.parse(fh.read())
        cls.funcs = {n.name: n for n in ast.walk(cls.tree)
                     if isinstance(n, ast.FunctionDef)}

    def test_every_valve_packet_is_noted_before_the_opcode_dispatch(self):
        """Liveness is about the SENDER, so an opcode we do not decode still counts."""
        body = self.funcs["_parse_ramses_message"]
        calls = [n for n in ast.walk(body)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
        names = [c.func.attr for c in calls]
        assert "_note_trv_packet" in names
        note = names.index("_note_trv_packet")
        first_parse = min(i for i, n in enumerate(names) if n.startswith("_parse_opcode_"))
        assert note < first_parse, "note the sender before decoding what it said"

    def test_the_error_state_is_set_after_the_state_writes(self):
        """updateStatesOnServer CLEARS a device error by default, so order is the fix."""
        src = ast.dump(self.funcs["_write_trv_states"])
        assert "updateStatesOnServer" in src and "setErrorStateOnServer" in src
        lines = ast.unparse(self.funcs["_write_trv_states"]).splitlines()
        last_write = max(i for i, l in enumerate(lines) if "updateStatesOnServer" in l)
        first_err  = min(i for i, l in enumerate(lines) if "setErrorStateOnServer" in l)
        assert last_write < first_err

    def test_the_main_loop_publishes_valve_states(self):
        names = {n.func.attr for n in ast.walk(self.funcs["_main_loop_pass"])
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        assert "_publish_trv_states" in names

    def test_the_listening_clock_starts_at_startup_not_at_import(self):
        """Restored from disk, but the clock that judges silence starts when we do."""
        src = ast.unparse(self.funcs["startup"])
        assert "_trv_listening_since" in src and "_load_trv_state" in src

    def test_the_valve_record_is_saved_on_shutdown(self):
        names = {n.func.attr for n in ast.walk(self.funcs["shutdown"])
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        assert "_save_trv_state" in names

    def test_nothing_calls_indigo_from_the_mqtt_thread_helper(self):
        """_note_trv_packet runs on the paho thread; an Indigo call there is a fault."""
        src = ast.unparse(self.funcs["_note_trv_packet"])
        assert "indigo." not in src


# ---------------------------------------------------------------------------
class TestUnknownIsRepresentable:
    """The fault this class exists for was seen LIVE, on eleven of twelve zones.

    Both flags shipped as Booleans for about ten minutes. Indigo materialises a new
    Boolean as FALSE, so every zone whose valve had simply not spoken yet asserted
    "silent" and "battery fine" — a fault that was not happening, next to reassurance
    nobody had earned. A List makes "unknown" a value the state can actually hold.
    """

    def test_tri_keeps_none_as_a_real_answer(self, rp):
        assert rp._tri(None, "yes", "no") == "unknown"
        assert rp._tri(True, "yes", "no") == "yes"
        assert rp._tri(False, "yes", "no") == "no"

    def test_each_flag_speaks_its_own_vocabulary(self, rp):
        """The words become sub-state ids, so they have to say what the trigger is for."""
        assert rp._liveness(None) == "unknown"
        assert rp._liveness(True) == "answering"
        assert rp._liveness(False) == "silent"
        assert rp._battery_warn(None) == "unknown"
        assert rp._battery_warn(True) == "low"
        assert rp._battery_warn(False) == "ok"

    def test_every_word_the_code_writes_is_an_option_the_xml_declares(self, rp):
        """A value the List does not declare is refused SERVER-side, silently.

        This is the pairing that broke live: the code and the XML have to agree, and
        nothing else in the suite would notice them drifting apart.
        """
        import xml.etree.ElementTree as ET
        root = ET.parse(os.path.join(_SP, "Devices.xml")).getroot()
        declared = {}
        for st in root.iter("State"):
            lst = st.find("./ValueType/List")
            if lst is not None:
                declared[st.get("id")] = {o.get("value") for o in lst.iter("Option")}
        for key, fn in (("trvStatus", rp._liveness), ("trvBatteryWarn", rp._battery_warn)):
            written = {fn(v) for v in (None, True, False)}
            assert written <= declared[key], (key, written - declared[key])

    def test_neither_flag_reuses_a_name_that_ever_shipped_as_a_boolean(self):
        """Indigo will not re-type a state, so a re-used id keeps the old bool for ever.

        Measured live on all twelve zones: declared as Lists, restarted, still bool —
        and the batch carrying "unknown" into one was then dropped whole.
        """
        import xml.etree.ElementTree as ET
        with open(os.path.join(_SP, "plugin.py"), encoding="utf-8") as fh:
            src = fh.read()
        root = ET.parse(os.path.join(_SP, "Devices.xml")).getroot()
        ids = {st.get("id") for st in root.iter("State")}
        for retired in ("trvOnline", "trvBatteryLow"):
            assert retired not in ids, f"{retired} shipped as a Boolean and cannot be reused"
            assert retired not in src, f"{retired} shipped as a Boolean and cannot be reused"

    def test_the_unknown_battery_sentinel_is_not_zero(self, rp):
        # 0% is the most alarming value in the range, and a valve that is transmitting
        # cannot be at 0 — so 0 could only ever be a lie.
        assert rp.TRV_BATTERY_UNKNOWN == -1

    def test_the_two_flags_are_lists_with_an_unknown_option(self):
        import xml.etree.ElementTree as ET
        root = ET.parse(os.path.join(_SP, "Devices.xml")).getroot()
        found = {}
        for st in root.iter("State"):
            if st.get("id") in ("trvStatus", "trvBatteryWarn"):
                lst = st.find("./ValueType/List")
                assert lst is not None, f"{st.get('id')} must be a List, not a Boolean"
                found[st.get("id")] = [o.get("value") for o in lst.iter("Option")]
        assert set(found) == {"trvStatus", "trvBatteryWarn"}
        for name, values in found.items():
            assert "unknown" in values, name

    def test_no_enum_option_value_carries_whitespace(self):
        """An option value is half of a generated sub-state id.

        Indigo builds `<state>.<value>` per option, so a value with a space is not a
        legal id and the whole write is refused SERVER-side with only a log line.
        """
        import xml.etree.ElementTree as ET
        root = ET.parse(os.path.join(_SP, "Devices.xml")).getroot()
        checked = 0
        for opt in root.iter("Option"):
            v = opt.get("value") or ""
            assert v and v == v.strip() and " " not in v, repr(v)
            checked += 1
        assert checked >= 6, "the scan found no options, so it proved nothing"


# ---------------------------------------------------------------------------
class TestBatteryCapabilityIsClaimedLate:
    """Declaring SupportsBatteryLevel creates a native batteryLevel of 0.

    A dozen thermostats reporting a flat battery is a worse fault than having no
    reading at all, so the capability is claimed only once a real reading arrives.
    """

    @classmethod
    def setup_class(cls):
        with open(os.path.join(_SP, "plugin.py"), encoding="utf-8") as fh:
            cls.tree = ast.parse(fh.read())
        cls.funcs = {n.name: n for n in ast.walk(cls.tree)
                     if isinstance(n, ast.FunctionDef)}

    def test_it_is_not_in_the_start_of_day_capability_defaults(self):
        src = ast.unparse(self.funcs["deviceStartComm"])
        assert "SupportsBatteryLevel" not in src

    def test_it_is_claimed_inside_the_have_a_reading_branch(self):
        """Not merely present in the method — inside the branch that has a number."""
        fn = self.funcs["_write_trv_states"]
        guarded = False
        for node in ast.walk(fn):
            if not isinstance(node, ast.If):
                continue
            test = ast.unparse(node.test)
            if "battery" in test and "None" in test:
                if "SupportsBatteryLevel" in ast.unparse(node):
                    guarded = True
        assert guarded, "the capability must be claimed only where a reading exists"

    def test_the_three_valued_states_are_written_unconditionally(self):
        """An unknown must be PUBLISHED, not left showing yesterday's verdict."""
        lines = ast.unparse(self.funcs["_write_trv_states"]).splitlines()
        for key in ("trvStatus", "trvBatteryWarn"):
            hits = [i for i, l in enumerate(lines) if f"'{key}'" in l]
            assert hits, key
            for i in hits:
                indent = len(lines[i]) - len(lines[i].lstrip())
                assert indent <= 8, f"{key} is written inside a branch: {lines[i]!r}"

    def test_device_start_seeds_the_honest_values(self):
        src = ast.unparse(self.funcs["_seed_trv_states"])
        for key in ("trvStatus", "trvBatteryWarn", "trvSummary", "trvBattery"):
            assert key in src, key
        assert "TRV_BATTERY_UNKNOWN" in src
        assert "_seed_trv_states" in ast.unparse(self.funcs["deviceStartComm"]), \
            "deviceStartComm must still call it"


# ---------------------------------------------------------------------------
class FakeDev:
    """Enough of an Indigo device to drive the two methods that write states.

    Written because the structural tests above check the SHAPE of these methods and a
    mutation sweep walked straight through four of them: `ast.unparse` re-indents from
    the function root, so "is this line inside an if" cannot be answered by counting
    spaces, and "does this key appear in the source" is still true of `if False:`.
    """

    def __init__(self, dev_id=1, name="Test Radiator", states=None, props=None):
        self.id = dev_id
        self.name = name
        self.address = "0"
        self.states = dict(states or {})
        self.pluginProps = dict(props or {})
        self.written = []          # every state batch, in order
        self.single = []           # updateStateOnServer calls
        self.errors = []           # setErrorStateOnServer calls
        self.prop_writes = 0

    def updateStatesOnServer(self, states):
        self.written.append({s["key"]: s["value"] for s in states})
        for s in states:
            self.states[s["key"]] = s["value"]

    def updateStateOnServer(self, key, value):
        self.single.append((key, value))
        self.states[key] = value

    def setErrorStateOnServer(self, msg):
        self.errors.append(msg)

    def replacePluginPropsOnServer(self, props):
        self.pluginProps = dict(props)
        self.prop_writes += 1

    def stateListOrDisplayStateIdChanged(self):
        pass

    def last(self, key):
        """The most recent value written for `key`, or a marker if it never was."""
        for batch in reversed(self.written):
            if key in batch:
                return batch[key]
        return "<never written>"


@pytest.fixture
def wired(rp, plug, monkeypatch):
    """A plugin whose indigo.devices resolves our fake, and the fake."""
    dev = FakeDev()
    monkeypatch.setattr(rp.indigo, "devices", {dev.id: dev}, raising=False)
    plug.trv_report_faults = True
    plug.trv_stale_hours = 6
    plug._trv_warned = set()
    return plug, dev


def _summary(**kw):
    base = {"count": 1, "addresses": "04:aaa", "battery": None, "battery_low": None,
            "last_seen": NOW, "oldest_seen": NOW, "online": None, "silent": ""}
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
class TestWriteBehaviour:
    """What actually reaches the device. These are the four the sweep found."""

    def test_unknown_liveness_is_written_as_unknown_not_as_silent(self, wired):
        plug, dev = wired
        plug._write_trv_states(dev, _summary(online=None), NOW)
        assert dev.last("trvStatus") == "unknown"

    def test_a_known_verdict_is_written_plainly(self, wired):
        plug, dev = wired
        plug._write_trv_states(dev, _summary(online=True), NOW)
        assert dev.last("trvStatus") == "answering"
        plug._write_trv_states(dev, _summary(online=False, silent="04:aaa"), NOW)
        assert dev.last("trvStatus") == "silent"

    def test_an_unreported_battery_is_the_sentinel_never_zero(self, rp, wired):
        plug, dev = wired
        plug._write_trv_states(dev, _summary(battery=None), NOW)
        assert dev.last("trvBattery") == rp.TRV_BATTERY_UNKNOWN
        assert dev.last("trvBattery") != 0, "0% reads to every battery sweep as flat"

    def test_a_real_battery_is_written_as_itself(self, wired):
        plug, dev = wired
        plug._write_trv_states(dev, _summary(battery=74, battery_low=False), NOW)
        assert dev.last("trvBattery") == 74
        assert dev.last("trvBatteryWarn") == "ok"

    def test_both_flags_are_written_every_time_even_when_unknown(self, wired):
        """An unknown must be published, not left showing an older verdict."""
        plug, dev = wired
        plug._write_trv_states(dev, _summary(online=True, battery_low=False), NOW)
        plug._write_trv_states(dev, _summary(online=None, battery_low=None), NOW)
        assert dev.written[-1].get("trvStatus") == "unknown"
        assert dev.written[-1].get("trvBatteryWarn") == "unknown"

    def test_the_native_battery_is_only_claimed_once_there_is_a_reading(self, wired):
        plug, dev = wired
        plug._write_trv_states(dev, _summary(battery=None), NOW)
        assert dev.prop_writes == 0
        assert not dev.pluginProps.get("SupportsBatteryLevel")
        assert dev.single == [], "no native battery may be written without a reading"

        plug._write_trv_states(dev, _summary(battery=61), NOW)
        assert dev.pluginProps.get("SupportsBatteryLevel") is True
        assert ("batteryLevel", 61) in dev.single

    def test_the_capability_is_claimed_once_not_on_every_pass(self, wired):
        plug, dev = wired
        for _ in range(3):
            plug._write_trv_states(dev, _summary(battery=61), NOW)
        assert dev.prop_writes == 1

    def test_a_silent_valve_raises_the_error_state_and_says_so_once(self, wired):
        plug, dev = wired
        s = _summary(online=False, silent="04:aaa", oldest_seen=NOW - 9 * HOUR)
        plug._write_trv_states(dev, s, NOW)
        plug._write_trv_states(dev, s, NOW)
        assert dev.errors == ["valve silent", "valve silent"]
        assert plug.logger.warning.call_count == 1, "silence is said once, not every pass"

    def test_recovery_clears_the_error_and_re_arms_the_warning(self, wired):
        plug, dev = wired
        plug._write_trv_states(dev, _summary(online=False, silent="04:aaa"), NOW)
        plug._write_trv_states(dev, _summary(online=True), NOW)
        assert dev.errors[-1] == ""
        assert dev.id not in plug._trv_warned

    def test_unknown_touches_the_error_state_neither_way(self, wired):
        """Not knowing is not a fault, and it is not an all-clear either."""
        plug, dev = wired
        plug._write_trv_states(dev, _summary(online=None), NOW)
        assert dev.errors == []

    def test_the_fault_switch_turns_off_the_error_state_only(self, wired):
        plug, dev = wired
        plug.trv_report_faults = False
        plug._write_trv_states(dev, _summary(online=False, silent="04:aaa"), NOW)
        assert dev.errors == []
        assert dev.last("trvStatus") == "silent", "the state still tells the truth"


# ---------------------------------------------------------------------------
class TestSeeding:
    """A device that has never heard a valve must not assert anything."""

    def test_a_fresh_device_is_seeded_with_the_honest_answers(self, rp, plug, monkeypatch):
        dev = FakeDev(states={})
        monkeypatch.setattr(rp.indigo, "devices", {dev.id: dev}, raising=False)
        plug.deviceStartComm(dev)
        assert dev.last("trvStatus") == "unknown"
        assert dev.last("trvBatteryWarn") == "unknown"
        assert dev.last("trvBattery") == rp.TRV_BATTERY_UNKNOWN
        assert "No valve heard" in dev.last("trvSummary")

    def test_the_seed_is_not_written_beside_the_thermostat_mode(self, rp, plug, monkeypatch):
        """One unacceptable value drops the WHOLE batch, silently.

        hvacOperationMode is what stops HomeKit showing every zone as OFF, and it was
        lost exactly this way — it rode in the same batch as a seed the server refused,
        with nothing in the plugin log or the event log to say so.

        Driven rather than read: the first version of this scanned the source for the two
        names in one call, and a mutation that appended the mode to the seed LIST a line
        earlier walked straight past it. What matters is what reaches the device.
        """
        dev = FakeDev(states={})
        monkeypatch.setattr(rp.indigo, "devices", {dev.id: dev}, raising=False)
        plug.deviceStartComm(dev)

        assert dev.written, "deviceStartComm wrote no states at all"
        assert any(k.startswith("trv") for b in dev.written for k in b), "nothing was seeded"
        assert any("hvacOperationMode" in b for b in dev.written), "the mode was never written"
        for batch in dev.written:
            if "hvacOperationMode" in batch:
                rode_along = sorted(k for k in batch if k.startswith("trv"))
                assert not rode_along, f"the seed rides with the mode: {rode_along}"

    def test_seeding_never_overwrites_a_real_answer(self, rp, plug, monkeypatch):
        dev = FakeDev(states={"trvStatus": "answering", "trvBatteryWarn": "ok",
                              "trvBattery": 74, "trvSummary": "The valve answering."})
        monkeypatch.setattr(rp.indigo, "devices", {dev.id: dev}, raising=False)
        plug.deviceStartComm(dev)
        written = dev.written[-1] if dev.written else {}
        for key in ("trvStatus", "trvBatteryWarn", "trvBattery", "trvSummary"):
            assert key not in written, f"{key} was clobbered on restart"
