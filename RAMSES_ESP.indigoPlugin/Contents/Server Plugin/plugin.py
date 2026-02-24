#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    plugin.py
# Description: RAMSES ESP gateway bridge plugin for Indigo home automation.
#              Connects to RAMSES-ESP wireless HVAC gateway via MQTT, auto-discovers
#              the gateway ID and Evohome zone thermostats from the RAMSES-II radio
#              message stream, and creates/updates Indigo custom devices for each zone.
# Author:      CliveS & Claude Sonnet 4.5
# Date:        23-02-2026
# Version:     1.1.7

try:
    import indigo
except ImportError:
    pass

try:
    import paho.mqtt.client as mqtt
    PAHO_AVAILABLE = True
except ImportError:
    PAHO_AVAILABLE = False

import json
import re
import threading
import time
from datetime import datetime

# ==============================================================================
# CONSTANTS
# ==============================================================================

PLUGIN_VERSION         = "1.1.7"

MQTT_KEEPALIVE         = 60            # seconds for MQTT keepalive ping
MQTT_RECONNECT_DELAY   = 30            # seconds between reconnect attempts

RAMSES_ROOT            = "RAMSES/GATEWAY"
# Discovery: firmware publishes RAMSES/GATEWAY/<gw_id> = "online" (retained),
# plus RAMSES/GATEWAY/<gw_id>/info/firmware and .../info/version as sub-topics.
# We use a single-level wildcard on the gateway ID segment to catch the presence topic.
TOPIC_INFO_WILDCARD    = "RAMSES/GATEWAY/+"

# RAMSES-II opcodes (v1.0 scope: zone thermostat messages only)
OPCODE_ZONE_NAME       = "0004"        # zone name (broadcast by controller)
OPCODE_ZONE_TEMP       = "30C9"        # current zone temperatures (broadcast)
OPCODE_ZONE_SETPOINT   = "2309"        # zone setpoints (broadcast)
OPCODE_ZONE_MODE       = "2349"        # zone mode / override

# Temperature encoding
TEMP_UNKNOWN_RAW       = 0x7FFF        # sentinel value meaning unknown / not set
TEMP_SCALE             = 100.0         # raw int / TEMP_SCALE = degrees C

# Zone mode codes (byte 3 of 2349 payload)
ZONE_MODE_SCHEDULE     = 0x00          # following schedule
ZONE_MODE_PERMANENT    = 0x02          # permanent override

# Indigo device type ID (must match Devices.xml)
DEVICE_TYPE_ID         = "ramsesZoneThermostat"

# Device folder name — all zone devices are created inside this Indigo folder
DEVICE_FOLDER_NAME     = "RAMSES"

# Main thread polling interval
MAIN_LOOP_SLEEP        = 5.0           # seconds

# Gateway timestamps earlier than this year are treated as pre-NTP-sync junk.
# The RAMSES-ESP firmware publishes epoch time (1970) until NTP syncs successfully.
EPOCH_SENTINEL_YEAR    = 2020

# Setpoint limits
SETPOINT_MIN_C         = 5.0
SETPOINT_MAX_C         = 35.0


# ==============================================================================
# PLUGIN CLASS
# ==============================================================================

class Plugin(indigo.PluginBase):

    # --------------------------------------------------------------------------
    # Lifecycle
    # --------------------------------------------------------------------------

    def __init__(self, plugin_id, plugin_display_name, plugin_version, plugin_prefs):
        super(Plugin, self).__init__(plugin_id, plugin_display_name, plugin_version, plugin_prefs)
        self.debug = False

        # MQTT client state
        self.mqtt_client        = None
        self.mqtt_connected     = False
        self.mqtt_lock          = threading.Lock()   # protects mqtt_client access

        # Gateway identity
        self.gateway_id         = ""                 # e.g. "18:730"
        self.gateway_subscribed = False              # True once subscribed to gw rx topic

        # Pending zone state updates from MQTT callbacks -> processed by main thread
        # Structure: {zone_idx(int): {"temp": float, "setpoint": float, "mode": str,
        #                             "mode_byte": int, "controller_id": str, "ts": str}}
        # Dict keys are overwritten on repeat updates (only latest value matters)
        self.pending_updates    = {}
        # Pending zone name updates from 0004 messages -> {zone_idx(int): name(str)}
        # Applied by main thread: stores state and optionally renames the Indigo device.
        self.pending_zone_names = {}
        self.pending_lock       = threading.Lock()   # protects pending_updates, pending_zone_names, pending_gateway_id

        # New gateway ID discovered by MQTT callback thread, pending persist by main thread.
        # Writing pluginPrefs from the MQTT callback thread triggers closedPrefsConfigUi
        # which disconnects MQTT - so we defer the prefs write to the main thread.
        self.pending_gateway_id = ""                 # guarded by pending_lock

        # Known zone -> Indigo device ID mapping (rebuilt from existing devs at startup)
        self.zone_devices       = {}                 # {zone_idx(int): indigo_dev_id(int)}
        self.zone_lock          = threading.Lock()   # protects zone_devices

        # MQTT connection settings (loaded from pluginPrefs in startup / closedPrefsConfigUi)
        self.broker_host        = "192.168.1.x"
        self.broker_port        = 1883
        self.broker_username    = ""
        self.broker_password    = ""

        # Timestamp of last _mqtt_connect() call; prevents the main-loop health check
        # from triggering a reconnect before paho's async on_connect has had time to fire.
        self._last_connect_time = 0.0

    # --------------------------------------------------------------------------

    def startup(self):
        self.logger.info("=" * 60)
        self.logger.info(f"RAMSES ESP Plugin v{PLUGIN_VERSION} starting")
        self.logger.info("=" * 60)

        if not PAHO_AVAILABLE:
            self.logger.error(
                "paho-mqtt library not found in Contents/Packages/ - plugin cannot run. "
                "Check that the paho/ directory was copied correctly."
            )
            return

        self._read_prefs()

        # Rebuild zone_devices index from any existing Indigo devices (e.g. after restart)
        restored = 0
        for dev in indigo.devices.iter(f"self.{DEVICE_TYPE_ID}"):
            try:
                zone_idx = int(dev.address)
                with self.zone_lock:
                    self.zone_devices[zone_idx] = dev.id
                self.logger.info(f"  Restored Zone {zone_idx}: '{dev.name}' (dev ID {dev.id})")
                restored += 1

                # Seed zone_name from device name if still empty.
                # The Evohome controller (01:) ignores RQ 0004 from an 18: gateway,
                # so opcode 0004 only arrives when the controller broadcasts it naturally
                # (on startup / name change). Until then, derive zone_name from the
                # Indigo device name by stripping a trailing " Radiator" suffix.
                # A real 0004 message will overwrite this when it eventually arrives.
                if not dev.states.get("zone_name", ""):
                    derived = dev.name
                    if derived.endswith(" Radiator"):
                        derived = derived[:-len(" Radiator")]
                    try:
                        dev.updateStatesOnServer([{"key": "zone_name", "value": derived}])
                        self.logger.info(f"    zone_name seeded from device name: '{derived}'")
                    except Exception as exc:
                        self.logger.warning(f"    Could not seed zone_name for '{dev.name}': {exc}")

            except (ValueError, Exception) as exc:
                self.logger.warning(f"  Could not restore zone device '{dev.name}': {exc}")

        self.logger.info(f"  Restored {restored} existing zone device(s)")
        self.logger.info(f"  MQTT broker:  {self.broker_host}:{self.broker_port}")
        self.logger.info(f"  Gateway ID:   {self.gateway_id or '(awaiting discovery)'}")
        self.logger.info("=" * 60)
        # Note: MQTT connection is started in runConcurrentThread after a short delay

        # One-time flag: True once RQ 0004 has been sent to populate zone_name states.
        # Set False here so zone names are re-requested on every plugin restart.
        self._zone_names_requested = False

    # --------------------------------------------------------------------------

    def shutdown(self):
        self.logger.info("RAMSES ESP Plugin shutting down")
        self._mqtt_disconnect()

    # --------------------------------------------------------------------------

    def runConcurrentThread(self):
        """Main plugin loop. Starts MQTT, drains pending zone updates every 5s."""
        try:
            # Give startup() a moment to complete before connecting
            self.sleep(2)
            self._mqtt_connect()

            while True:
                # --- Drain pending updates from MQTT callbacks ---
                with self.pending_lock:
                    updates    = dict(self.pending_updates)
                    self.pending_updates.clear()
                    zone_names = dict(self.pending_zone_names)
                    self.pending_zone_names.clear()
                    new_gw_id  = self.pending_gateway_id
                    self.pending_gateway_id = ""

                # Persist new gateway ID to prefs (must be done on main thread)
                if new_gw_id:
                    self._persist_gateway_id(new_gw_id)

                # Apply zone name updates (store state + auto-rename device)
                for zone_idx, name in zone_names.items():
                    try:
                        self._apply_zone_name_update(zone_idx, name)
                    except Exception as exc:
                        self.logger.error(f"Error applying name for Zone {zone_idx}: {exc}")

                for zone_idx, data in updates.items():
                    try:
                        # Apply each update type present in the data dict.
                        # Offline flag is set by _on_disconnect and takes priority.
                        if data.get("offline"):
                            self._apply_offline_update(zone_idx)
                        else:
                            # Order matters: mode includes setpoint so check mode last
                            if "temp" in data:
                                self._apply_temp_update(zone_idx, data)
                            if "setpoint" in data and "mode" not in data:
                                self._apply_setpoint_update(zone_idx, data)
                            if "mode" in data:
                                self._apply_mode_update(zone_idx, data)
                    except Exception as exc:
                        self.logger.error(f"Error applying update for Zone {zone_idx}: {exc}")

                # --- One-time zone name request ---
                # Send RQ 0004 for all zones once we have MQTT + a known controller_id.
                # Ensures zone_name states are populated immediately after startup rather
                # than waiting for the controller to broadcast 0004 on its own schedule.
                if not self._zone_names_requested and self.mqtt_connected and self.gateway_id:
                    if self._request_zone_names():
                        self._zone_names_requested = True

                # --- Reconnect if MQTT dropped ---
                # Guard: allow at least MQTT_RECONNECT_DELAY seconds since the last
                # connect attempt before trying again.  This prevents the health check
                # from tearing down a brand-new paho connection before on_connect fires
                # (paho's async TCP handshake can take a second or two on a LAN).
                if not self.mqtt_connected:
                    secs_since_connect = time.time() - self._last_connect_time
                    if secs_since_connect >= MQTT_RECONNECT_DELAY:
                        self.logger.warning("MQTT not connected - attempting reconnect...")
                        self._mqtt_connect()
                        self.sleep(MQTT_RECONNECT_DELAY)
                    else:
                        # Still within the connect grace period - just keep polling
                        self.sleep(MAIN_LOOP_SLEEP)
                else:
                    self.sleep(MAIN_LOOP_SLEEP)

        except self.StopThread:
            pass

    # --------------------------------------------------------------------------
    # Plugin Prefs
    # --------------------------------------------------------------------------

    def validatePrefsConfigUi(self, values_dict):
        errors_dict = indigo.Dict()

        port_str = values_dict.get("mqtt_broker_port", "1883").strip()
        try:
            port = int(port_str)
            if not (1 <= port <= 65535):
                errors_dict["mqtt_broker_port"] = "Port must be between 1 and 65535"
        except ValueError:
            errors_dict["mqtt_broker_port"] = "Port must be a whole number"

        if not values_dict.get("mqtt_broker_host", "").strip():
            errors_dict["mqtt_broker_host"] = "Broker host is required"

        # Validate and auto-correct the gateway ID field.
        # Valid format: NN:NNNNNN (e.g. "18:203052"). Empty = auto-discover.
        # If the user typed it multiple times (e.g. "18:20305218:20305218:..."),
        # try to extract the first valid segment automatically.
        raw_gw = values_dict.get("discovered_gateway_id", "").strip()
        if raw_gw:
            if not re.match(r'^\d{2}:\d{6}$', raw_gw):
                match = re.search(r'(\d{2}:\d{6})(?!\d)', raw_gw)
                if match:
                    values_dict["discovered_gateway_id"] = match.group(1)
                else:
                    errors_dict["discovered_gateway_id"] = (
                        "Gateway ID must be in format NN:NNNNNN (e.g. 18:203052). "
                        "Clear the field to let the plugin discover it automatically."
                    )
        else:
            values_dict["discovered_gateway_id"] = ""

        if len(errors_dict) > 0:
            return (False, values_dict, errors_dict)
        return (True, values_dict)

    def closedPrefsConfigUi(self, values_dict, user_cancelled):
        if user_cancelled:
            return

        old_host = self.broker_host
        old_port = self.broker_port
        old_gw   = self.gateway_id

        self._read_prefs()

        broker_changed  = (self.broker_host != old_host or self.broker_port != old_port)
        gateway_cleared = (not self.gateway_id and old_gw)

        if broker_changed:
            self.logger.info("Broker settings changed - reconnecting MQTT")
            self._mqtt_disconnect()
            self._mqtt_connect()

        if gateway_cleared:
            self.logger.info("Gateway ID cleared - will re-discover on next MQTT message")
            self.gateway_subscribed = False

    # --------------------------------------------------------------------------
    # Device Lifecycle
    # --------------------------------------------------------------------------

    def deviceStartComm(self, dev):
        super(Plugin, self).deviceStartComm(dev)
        # Lock thermostat capabilities to heat-only on every start.
        # replacePluginPropsOnServer() triggers Indigo to rebuild the device's state list
        # based on the new props, so this must be called even if values haven't changed
        # to ensure Indigo picks up the correct capabilities after a plugin reload.
        try:
            props = dev.pluginProps
            changed = False
            capability_defaults = {
                "NumTemperatureInputs":         "1",
                "NumHumidityInputs":            "0",
                "SupportsHeatSetpoint":         True,
                "SupportsCoolSetpoint":         False,
                # SupportsHvacOperationMode must be True for the hvacOperationMode state to
                # exist. With False, the state is never created and updateStatesOnServer() fails.
                # We keep mode locked to Heat in actionControlThermostat() SetHvacMode handler.
                "SupportsHvacOperationMode":    True,
                "SupportsHvacFanMode":          False,
                # ShowCoolHeatEquipmentStateUI must be True for hvacHeaterIsOn to exist.
                # This is the "flame on" indicator used by HomeKit to show active heating.
                "ShowCoolHeatEquipmentStateUI": True,
            }
            for key, val in capability_defaults.items():
                if props.get(key) != val:
                    props[key] = val
                    changed = True
            if changed:
                dev.replacePluginPropsOnServer(props)
                # Re-fetch: replacePluginPropsOnServer() creates new built-in thermostat
                # states (hvacOperationMode, hvacHeaterIsOn) but the local dev object is
                # stale until refreshed. Without this, updateStatesOnServer() below fails.
                dev = indigo.devices[dev.id]

            # Ensure hvacOperationMode is always Heat.
            # Indigo defaults this to Off (0) which makes HomeKit and other integrations
            # show the device as "OFF". Evohome zones are heat-only — always in Heat mode.
            dev.updateStatesOnServer([
                {"key": "hvacOperationMode", "value": indigo.kHvacMode.Heat},
            ])
        except Exception as exc:
            self.logger.warning(f"deviceStartComm: could not set thermostat props for '{dev.name}': {exc}")

    def deviceStopComm(self, dev):
        super(Plugin, self).deviceStopComm(dev)

    def deviceDeleted(self, dev):
        """Remove the device from the zone_devices index when deleted by the user."""
        try:
            zone_idx = int(dev.address)
            with self.zone_lock:
                if zone_idx in self.zone_devices and self.zone_devices[zone_idx] == dev.id:
                    del self.zone_devices[zone_idx]
                    self.logger.info(f"Zone {zone_idx} device deleted from index")
        except (ValueError, Exception):
            pass

    # --------------------------------------------------------------------------
    # Thermostat Actions (built-in Indigo thermostat callback)
    # --------------------------------------------------------------------------

    def actionControlThermostat(self, action, dev):
        """
        Handle built-in Indigo thermostat actions.
        Called by Indigo for SetHeatSetpoint, Increase/DecreaseHeatSetpoint,
        and status-request actions from action groups, schedules, and triggers.
        Cool setpoint / HVAC mode / fan mode are not supported (heat-only zones).
        """
        try:
            if not dev.enabled:
                self.logger.warning(f"'{dev.name}' is disabled - ignoring thermostat action")
                return

            if action.thermostatAction == indigo.kThermostatAction.SetHeatSetpoint:
                new_sp = float(action.actionValue)
                self._validate_and_publish_setpoint(dev, new_sp, "set")

            elif action.thermostatAction == indigo.kThermostatAction.IncreaseHeatSetpoint:
                new_sp = dev.heatSetpoint + float(action.actionValue)
                self._validate_and_publish_setpoint(dev, new_sp, "increase")

            elif action.thermostatAction == indigo.kThermostatAction.DecreaseHeatSetpoint:
                new_sp = dev.heatSetpoint - float(action.actionValue)
                self._validate_and_publish_setpoint(dev, new_sp, "decrease")

            elif action.thermostatAction == indigo.kThermostatAction.SetHvacMode:
                # Evohome zones are heat-only — ignore Off/Cool requests and lock to Heat.
                # HomeKit (and other integrations) may send SetHvacMode(Off) when the user
                # taps the thermostat off. We silently re-assert Heat so the zone stays on.
                requested = action.actionValue
                if requested != indigo.kHvacMode.Heat:
                    self.logger.info(
                        f"'{dev.name}' SetHvacMode({requested}) ignored "
                        f"- Evohome zones are heat-only; mode stays Heat"
                    )
                try:
                    dev.updateStatesOnServer([
                        {"key": "hvacOperationMode", "value": indigo.kHvacMode.Heat},
                    ])
                except Exception as exc:
                    self.logger.warning(
                        f"Could not re-assert Heat mode for '{dev.name}': {exc}"
                    )

            elif action.thermostatAction in (
                indigo.kThermostatAction.RequestStatusAll,
                indigo.kThermostatAction.RequestSetpoints,
                indigo.kThermostatAction.RequestTemperatures,
                indigo.kThermostatAction.RequestMode,
                indigo.kThermostatAction.RequestEquipmentState,
            ):
                # Trigger an immediate zone refresh via RQ 30C9
                self.action_request_zone_update(action)

            else:
                # Cool setpoint / fan mode not applicable to Evohome heat zones
                if self.debug:
                    self.logger.debug(
                        f"'{dev.name}' thermostat action {action.thermostatAction} "
                        f"not supported (heat-only Evohome zone)"
                    )

        except Exception as exc:
            self.logger.error(f"Error in actionControlThermostat for '{dev.name}': {exc}")

    def _validate_and_publish_setpoint(self, dev, setpoint_c, action_str):
        """
        Clamp setpoint to valid range, publish W 2309 to RAMSES gateway,
        and optimistically update setpointHeat state immediately so the UI
        reflects the command before the next 2309 broadcast confirms it.
        """
        if not self.mqtt_connected:
            self.logger.error(
                f"Cannot {action_str} setpoint for '{dev.name}' - MQTT not connected"
            )
            return
        if not self.gateway_id:
            self.logger.error(
                f"Cannot {action_str} setpoint for '{dev.name}' - gateway not discovered yet"
            )
            return

        setpoint_c = round(max(SETPOINT_MIN_C, min(float(setpoint_c), SETPOINT_MAX_C)), 2)
        zone_idx   = int(dev.address)
        published  = self._publish_setpoint(zone_idx, setpoint_c)

        if not published:
            # _publish_setpoint already logged the specific error; nothing more to do
            return

        # Optimistic UI update — actual confirmation arrives in next 30C9/2309 broadcast
        try:
            dev.updateStatesOnServer([
                {"key": "setpointHeat", "value": setpoint_c,
                 "uiValue": f"{setpoint_c:.1f} degC"},
            ])
        except Exception as exc:
            self.logger.warning(
                f"Could not update setpointHeat state for '{dev.name}': {exc}"
            )

        self.logger.info(
            f"'{dev.name}' (Zone {zone_idx}) setpoint {action_str} -> {setpoint_c:.1f} degC"
        )

    # --------------------------------------------------------------------------
    # Custom Actions (defined in Actions.xml)
    # --------------------------------------------------------------------------

    def action_request_zone_update(self, plugin_action):
        """Send RQ 30C9 to controller to request immediate zone temperature refresh."""
        if not self.mqtt_connected:
            self.logger.warning("Cannot request zone update - MQTT not connected")
            return
        if not self.gateway_id:
            self.logger.warning("Cannot request zone update - gateway not discovered yet")
            return

        # Find the controller ID from any existing zone device
        controller_id = ""
        with self.zone_lock:
            zone_ids = dict(self.zone_devices)
        for zone_idx, dev_id in zone_ids.items():
            try:
                dev = indigo.devices[dev_id]
                cid = dev.states.get("zone_controller_id", "")
                if cid and cid.startswith("01:"):
                    controller_id = cid
                    break
            except Exception:
                pass

        if not controller_id:
            self.logger.warning(
                "Cannot request zone update - no controller ID known yet "
                "(wait for first 30C9 or 2309 message to arrive)"
            )
            return

        gw_addr  = self.gateway_id.replace("-", ":")
        msg_str  = f"RQ --- {gw_addr} {controller_id} --:------ 30C9 001 00"
        payload  = json.dumps({"msg": msg_str})
        topic    = self._gateway_tx_topic()

        try:
            with self.mqtt_lock:
                if self.mqtt_client is not None:
                    self.mqtt_client.publish(topic, payload, qos=0)
            self.logger.info(f"Zone update requested via {topic}: {msg_str}")
        except Exception as exc:
            self.logger.error(f"Failed to publish zone update request: {exc}")

    # --------------------------------------------------------------------------
    # MQTT Client Management
    # --------------------------------------------------------------------------

    def _mqtt_connect(self):
        """Create and connect paho MQTT client. Uses loop_start() for async I/O."""
        if not PAHO_AVAILABLE:
            return

        try:
            # Cleanly stop any existing client first
            with self.mqtt_lock:
                if self.mqtt_client is not None:
                    try:
                        self.mqtt_client.loop_stop()
                        self.mqtt_client.disconnect()
                    except Exception:
                        pass
                    self.mqtt_client = None
                    self.mqtt_connected = False

            client_id = f"indigo-ramses-esp-{int(time.time())}"

            # paho 1.6.1 (bundled) does not have CallbackAPIVersion
            client = mqtt.Client(
                client_id=client_id,
                clean_session=True,
                userdata=None
            )

            client.on_connect    = self._on_connect
            client.on_disconnect = self._on_disconnect
            client.on_message    = self._on_message

            if self.broker_username:
                client.username_pw_set(
                    username=self.broker_username,
                    password=self.broker_password
                )

            self._last_connect_time = time.time()
            self.logger.info(f"Connecting to MQTT broker {self.broker_host}:{self.broker_port}")
            client.connect(
                host=self.broker_host,
                port=self.broker_port,
                keepalive=MQTT_KEEPALIVE
            )
            client.loop_start()

            with self.mqtt_lock:
                self.mqtt_client = client

        except Exception as exc:
            self.logger.error(f"MQTT connection failed: {exc}")
            self.mqtt_connected = False

    def _mqtt_disconnect(self):
        """Gracefully stop the paho client."""
        try:
            with self.mqtt_lock:
                if self.mqtt_client is not None:
                    self.mqtt_client.loop_stop()
                    self.mqtt_client.disconnect()
                    self.mqtt_client = None
                    self.mqtt_connected = False
            self.logger.info("MQTT client disconnected")
        except Exception as exc:
            self.logger.warning(f"Error during MQTT disconnect: {exc}")

    # --------------------------------------------------------------------------
    # MQTT Callbacks (run on paho's background thread - NO Indigo API calls here)
    # --------------------------------------------------------------------------

    def _on_connect(self, client, userdata, flags, rc):
        """Called by paho when connection is established or fails."""
        if rc == 0:
            self.mqtt_connected = True
            self.logger.info(
                f"MQTT connected to {self.broker_host}:{self.broker_port}"
            )
            # Always subscribe to gateway discovery topic
            client.subscribe(TOPIC_INFO_WILDCARD, qos=0)
            self.logger.info(f"Subscribed to {TOPIC_INFO_WILDCARD}")

            # If gateway already known from prefs, also subscribe to its rx topic now
            if self.gateway_id and not self.gateway_subscribed:
                rx_topic = f"{RAMSES_ROOT}/{self.gateway_id}/rx"
                client.subscribe(rx_topic, qos=0)
                self.gateway_subscribed = True
                self.logger.info(f"Subscribed to {rx_topic}")
        else:
            self.mqtt_connected = False
            rc_messages = {
                1: "incorrect protocol version",
                2: "invalid client identifier",
                3: "server unavailable",
                4: "bad username or password",
                5: "not authorised"
            }
            reason = rc_messages.get(rc, f"code {rc}")
            self.logger.error(f"MQTT connection refused: {reason}")

    def _on_disconnect(self, client, userdata, rc):
        """Called by paho when disconnected."""
        self.mqtt_connected = False
        self.gateway_subscribed = False
        if rc != 0:
            self.logger.warning(
                f"MQTT unexpected disconnect (rc={rc}) - will reconnect in {MQTT_RECONNECT_DELAY}s"
            )
        else:
            self.logger.info("MQTT disconnected cleanly")

        # Queue offline status for all zone devices (applied by main thread)
        with self.pending_lock:
            with self.zone_lock:
                for zone_idx in self.zone_devices:
                    if zone_idx not in self.pending_updates:
                        self.pending_updates[zone_idx] = {}
                    self.pending_updates[zone_idx]["offline"] = True

    def _on_message(self, client, userdata, msg):
        """Called by paho for every received MQTT message. Must not call Indigo API."""
        try:
            topic   = msg.topic
            payload = msg.payload.decode("utf-8", errors="replace")

            if self.debug:
                self.logger.debug(f"MQTT rx [{topic}]: {payload[:200]}")

            parts = topic.split("/")
            # RAMSES/GATEWAY/<gw_id>          -> 3 parts: presence/status topic (payload="online")
            # RAMSES/GATEWAY/<gw_id>/info/...  -> 5 parts: firmware info sub-topics
            # RAMSES/GATEWAY/<gw_id>/rx        -> 4 parts: radio message stream
            if len(parts) == 3 and parts[0] == "RAMSES" and parts[1] == "GATEWAY":
                self._handle_info_message(topic, payload, parts)
            elif topic.endswith("/rx"):
                self._handle_rx_message(payload)

        except Exception as exc:
            self.logger.error(f"Error in _on_message: {exc}")

    # --------------------------------------------------------------------------
    # Gateway Discovery
    # --------------------------------------------------------------------------

    def _handle_info_message(self, topic, payload, parts):
        """
        Extract gateway ID from RAMSES/GATEWAY/<gw_id> presence topic.
        The firmware publishes this with payload "online" (retained) when it connects.
        Topic parts (pre-split by caller): ['RAMSES', 'GATEWAY', '<gw_id>']
        """
        try:
            discovered_id = parts[2].strip()
            if not discovered_id:
                return

            if self.gateway_id == discovered_id:
                return   # already known

            if self.gateway_id:
                self.logger.warning(
                    f"Second gateway seen: '{discovered_id}' "
                    f"(already using '{self.gateway_id}') - ignoring"
                )
                return

            self.logger.info(f"Gateway discovered: {discovered_id}")
            self._set_gateway_id(discovered_id)

        except Exception as exc:
            self.logger.error(f"Error in _handle_info_message: {exc}")

    def _set_gateway_id(self, gw_id):
        """Store gateway ID and queue persist to prefs (done by main thread). Subscribe to rx."""
        self.gateway_id = gw_id

        # Queue prefs write for the main thread - writing pluginPrefs from the MQTT
        # callback thread triggers closedPrefsConfigUi which disconnects MQTT.
        with self.pending_lock:
            self.pending_gateway_id = gw_id

        self._resubscribe_to_gateway()

    def _persist_gateway_id(self, gw_id):
        """Save gateway ID to plugin prefs. Called from main thread only."""
        try:
            prefs = self.pluginPrefs
            prefs["discovered_gateway_id"] = gw_id
            self.pluginPrefs = prefs
            self.logger.info(f"Gateway ID saved to plugin prefs: {gw_id}")
        except Exception as exc:
            self.logger.warning(f"Could not save gateway ID to prefs: {exc}")

    def _resubscribe_to_gateway(self):
        """Subscribe to RAMSES/GATEWAY/<gw_id>/rx once gateway ID is known."""
        if not self.gateway_id or not self.mqtt_connected:
            return

        rx_topic = f"{RAMSES_ROOT}/{self.gateway_id}/rx"
        try:
            with self.mqtt_lock:
                if self.mqtt_client is not None:
                    self.mqtt_client.subscribe(rx_topic, qos=0)
                    self.gateway_subscribed = True
                    self.logger.info(f"Subscribed to {rx_topic}")
        except Exception as exc:
            self.logger.error(f"Failed to subscribe to {rx_topic}: {exc}")

    # --------------------------------------------------------------------------
    # RAMSES-II Message Parsing
    # --------------------------------------------------------------------------

    def _handle_rx_message(self, json_str):
        """Parse JSON payload from rx topic and dispatch RAMSES message."""
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as exc:
            self.logger.warning(f"Invalid JSON on rx topic: {exc}")
            return

        msg_str = data.get("msg", "").strip()
        ts      = data.get("ts", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        if not msg_str:
            return

        self._parse_ramses_message(msg_str, ts)

    def _parse_ramses_message(self, msg_str, ts):
        """
        Parse RAMSES-II message string and dispatch to opcode handlers.

        Message format (9+ whitespace-separated fields):
          [0]  aaa    = RSSI or '---'
          [1]  XX     = verb: 'I', 'RQ', 'RP', 'W'
          [2]  bbb    = sequence '---'
          [3]  DEV1   = device address e.g. '01:123456'
          [4]  DEV2   = device address or '--:------'
          [5]  DEV3   = device address or '--:------'
          [6]  CODE   = 4-char hex opcode e.g. '30C9'
          [7]  nnn    = payload length (decimal bytes)
          [8]  PAYLOAD = hex-encoded payload string
        """
        try:
            fields = msg_str.split()
            if len(fields) < 9:
                if self.debug:
                    self.logger.debug(f"Short RAMSES msg ({len(fields)} fields): {msg_str}")
                return

            verb        = fields[1].strip()
            opcode      = fields[6].strip().upper()
            payload_hex = fields[8].strip().upper() if len(fields) > 8 else ""

            # Only process informational and reply messages
            if verb not in ("I", "RP"):
                return

            if self.debug:
                self.logger.debug(
                    f"RAMSES: verb={verb} opcode={opcode} "
                    f"len={fields[7]} payload={payload_hex[:40]}"
                )

            if opcode == OPCODE_ZONE_NAME:
                self._parse_opcode_0004(fields, payload_hex, ts)
            elif opcode == OPCODE_ZONE_TEMP:
                self._parse_opcode_30c9(fields, payload_hex, ts)
            elif opcode == OPCODE_ZONE_SETPOINT:
                self._parse_opcode_2309(fields, payload_hex, ts)
            elif opcode == OPCODE_ZONE_MODE:
                self._parse_opcode_2349(fields, payload_hex, ts)

        except Exception as exc:
            self.logger.error(
                f"Error parsing RAMSES message '{msg_str[:80]}': {exc}"
            )

    def _parse_temp_bytes(self, payload_hex, byte_offset):
        """
        Extract a 16-bit big-endian signed temperature from payload_hex.

        Args:
            payload_hex:  hex string (2 chars per byte)
            byte_offset:  byte index (0-based) of the 2-byte temperature value

        Returns:
            float temperature in degrees C, or None if payload too short or value unknown (0x7FFF)
        """
        hex_start = byte_offset * 2
        if len(payload_hex) < hex_start + 4:
            return None

        raw_hex = payload_hex[hex_start : hex_start + 4]
        raw_int = int(raw_hex, 16)

        if raw_int == TEMP_UNKNOWN_RAW:
            return None

        # Convert to signed 16-bit
        if raw_int >= 0x8000:
            raw_int -= 0x10000

        return raw_int / TEMP_SCALE

    def _extract_controller_id(self, fields):
        """
        Find the Evohome controller address in DEV1/DEV2/DEV3 message fields.
        Controller device class is '01' (Evohome controller / system manager).
        """
        for field in fields[3:6]:
            if field.startswith("01:") and field != "--:------":
                return field
        return ""

    def _parse_opcode_30c9(self, fields, payload_hex, ts):
        """
        30C9 - Zone temperatures.
        Payload: repeating 3-byte blocks - [zone_idx(1 byte)][temp_degC(2 bytes)]
        A single message may contain multiple zones.
        """
        controller_id = self._extract_controller_id(fields)
        block_count   = len(payload_hex) // 6   # 3 bytes = 6 hex chars per block

        for i in range(block_count):
            block_start = i * 6
            if len(payload_hex) < block_start + 6:
                break

            zone_idx = int(payload_hex[block_start : block_start + 2], 16)
            temp_c   = self._parse_temp_bytes(payload_hex, i * 3 + 1)

            if temp_c is None:
                continue

            if self.debug:
                self.logger.debug(f"30C9: Zone {zone_idx} = {temp_c:.2f}degC")

            with self.pending_lock:
                if zone_idx not in self.pending_updates:
                    self.pending_updates[zone_idx] = {}
                self.pending_updates[zone_idx]["temp"]          = temp_c
                self.pending_updates[zone_idx]["controller_id"] = controller_id
                self.pending_updates[zone_idx]["ts"]            = ts

    def _parse_opcode_2309(self, fields, payload_hex, ts):
        """
        2309 - Zone setpoints.
        Payload: same 3-byte block structure as 30C9.
        """
        controller_id = self._extract_controller_id(fields)
        block_count   = len(payload_hex) // 6

        for i in range(block_count):
            block_start = i * 6
            if len(payload_hex) < block_start + 6:
                break

            zone_idx   = int(payload_hex[block_start : block_start + 2], 16)
            setpoint_c = self._parse_temp_bytes(payload_hex, i * 3 + 1)

            if setpoint_c is None:
                continue

            if self.debug:
                self.logger.debug(f"2309: Zone {zone_idx} setpoint = {setpoint_c:.2f}degC")

            with self.pending_lock:
                if zone_idx not in self.pending_updates:
                    self.pending_updates[zone_idx] = {}
                self.pending_updates[zone_idx]["setpoint"]      = setpoint_c
                self.pending_updates[zone_idx]["controller_id"] = controller_id
                self.pending_updates[zone_idx]["ts"]            = ts

    def _parse_opcode_2349(self, fields, payload_hex, ts):
        """
        2349 - Zone mode / override. Single zone per message (7+ bytes):
          byte 0:   zone_idx
          bytes 1-2: setpoint (same encoding as 30C9/2309)
          byte 3:   mode code (0x00=schedule, 0x02=permanent override, others)
          bytes 4+: mode-specific (until datetime - not needed for v1.0)
        """
        if len(payload_hex) < 8:   # need at least 4 bytes = 8 hex chars
            return

        controller_id = self._extract_controller_id(fields)

        zone_idx   = int(payload_hex[0:2], 16)
        setpoint_c = self._parse_temp_bytes(payload_hex, 1)
        mode_byte  = int(payload_hex[6:8], 16)    # byte 3 = hex chars 6-7

        if setpoint_c is None:
            setpoint_c = 0.0

        if mode_byte == ZONE_MODE_SCHEDULE:
            mode_str = "schedule"
        elif mode_byte == ZONE_MODE_PERMANENT:
            mode_str = "permanent override"
        else:
            mode_str = f"mode 0x{mode_byte:02X}"

        if self.debug:
            self.logger.debug(
                f"2349: Zone {zone_idx} setpoint={setpoint_c:.2f}degC mode={mode_str}"
            )

        with self.pending_lock:
            if zone_idx not in self.pending_updates:
                self.pending_updates[zone_idx] = {}
            self.pending_updates[zone_idx]["setpoint"]      = setpoint_c
            self.pending_updates[zone_idx]["mode"]          = mode_str
            self.pending_updates[zone_idx]["mode_byte"]     = mode_byte
            self.pending_updates[zone_idx]["controller_id"] = controller_id
            self.pending_updates[zone_idx]["ts"]            = ts

    def _parse_opcode_0004(self, fields, payload_hex, ts):
        """
        0004 - Zone name.

        Payload structure (variable length):
          byte 0:   zone_idx
          byte 1:   unknown / always 00
          bytes 2+: zone name, UTF-8 encoded, padded with 00 bytes to a fixed width (20 bytes total)

        The total payload is typically 22 bytes (44 hex chars):
          [zone_idx 1B][00 1B][name 20B]
        Name bytes after the first 0x00 are padding and should be stripped.

        Example:
          Payload: 00002C6F66666963650000000000000000000000000000
          zone_idx = 0x00 = 0
          padding  = 0x00
          name_hex = "2C6F666669636500..." -> decode -> "Living Room" (strip nulls)
        """
        if len(payload_hex) < 6:
            # Need at least zone_idx + padding + 1 char of name
            return

        try:
            zone_idx = int(payload_hex[0:2], 16)

            # Name starts at byte 2 (hex offset 4), strip null bytes (padding)
            name_hex  = payload_hex[4:]
            raw_bytes = bytes.fromhex(name_hex)
            # Decode as UTF-8, strip null padding and whitespace
            name = raw_bytes.replace(b'\x00', b'').decode("utf-8", errors="replace").strip()

            if not name:
                if self.debug:
                    self.logger.debug(f"0004: Zone {zone_idx} name is empty - skipping")
                return

            if self.debug:
                self.logger.debug(f"0004: Zone {zone_idx} name = '{name}'")

            with self.pending_lock:
                self.pending_zone_names[zone_idx] = name

        except Exception as exc:
            self.logger.warning(f"Error parsing opcode 0004 payload '{payload_hex}': {exc}")

    # --------------------------------------------------------------------------
    # Zone / Indigo Device Management  (main thread only)
    # --------------------------------------------------------------------------

    def _find_zone_device(self, zone_idx):
        """
        Return the Indigo device for zone_idx, or None.
        Checks in-memory index first; falls back to iterating devices if stale.
        """
        with self.zone_lock:
            if zone_idx in self.zone_devices:
                dev_id = self.zone_devices[zone_idx]
                try:
                    return indigo.devices[dev_id]
                except KeyError:
                    # Device was deleted by the user
                    del self.zone_devices[zone_idx]

        # Fallback: scan all plugin devices by address
        for dev in indigo.devices.iter(f"self.{DEVICE_TYPE_ID}"):
            try:
                if int(dev.address) == zone_idx:
                    with self.zone_lock:
                        self.zone_devices[zone_idx] = dev.id
                    return dev
            except (ValueError, Exception):
                pass

        return None

    def _create_zone_device(self, zone_idx, controller_id):
        """
        Create a new Indigo custom device for a zone. Main thread only.
        All zones are numbered sequentially; no DHW special-casing (Combi boiler system).
        """
        device_name = f"RAMSES Zone {zone_idx}"

        self.logger.info(
            f"Auto-creating zone device: '{device_name}' (zone_idx={zone_idx}, "
            f"controller={controller_id})"
        )

        try:
            folder_id = self._get_or_create_folder(DEVICE_FOLDER_NAME)
            new_dev = indigo.device.create(
                protocol=indigo.kProtocol.Plugin,
                address=str(zone_idx),
                name=device_name,
                deviceTypeId=DEVICE_TYPE_ID,
                folder=folder_id
            )

            ts_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            new_dev.updateStatesOnServer([
                {"key": "temperatureInput1", "value": 0.0,          "uiValue": "0.00 degC"},
                {"key": "setpointHeat",      "value": 0.0,          "uiValue": "0.00 degC"},
                # hvacHeaterIsOn is NOT set here: it's a built-in thermostat state that Indigo
                # only creates after deviceStartComm() fires replacePluginPropsOnServer() to lock
                # the thermostat capability props.  Indigo defaults it to False automatically.
                {"key": "zone_mode",         "value": "schedule"},
                {"key": "zone_controller_id","value": controller_id},
                {"key": "zone_name",         "value": ""},
                {"key": "last_seen",         "value": ts_now},
                {"key": "online",            "value": "true"},
            ])

            with self.zone_lock:
                self.zone_devices[zone_idx] = new_dev.id

            self.logger.info(f"Created '{device_name}' (Indigo dev ID {new_dev.id})")
            return new_dev

        except Exception as exc:
            self.logger.error(f"Failed to create device for Zone {zone_idx}: {exc}")
            return None

    def _apply_temp_update(self, zone_idx, data):
        """Update temperatureInput1 (built-in thermostat state). Creates device if not yet known."""
        dev = self._find_zone_device(zone_idx)
        if dev is None:
            dev = self._create_zone_device(zone_idx, data.get("controller_id", ""))
        if dev is None:
            return

        temp_c        = data["temp"]
        controller_id = data.get("controller_id", "")
        ts            = self._format_ts(data.get("ts", ""))

        # hvacHeaterIsOn: True when zone temp is meaningfully below setpoint.
        # Used by HomeKit and other integrations to show the heating-active indicator.
        # 0.3 degC hysteresis prevents rapid toggling around the setpoint.
        try:
            setpoint   = float(dev.states.get("setpointHeat", 0.0))
            is_heating = temp_c < (setpoint - 0.3) if setpoint > SETPOINT_MIN_C else False
        except Exception:
            is_heating = False

        try:
            state_updates = [
                {"key": "temperatureInput1", "value": round(temp_c, 2),
                 "uiValue": f"{temp_c:.2f} degC"},
                {"key": "hvacOperationMode", "value": indigo.kHvacMode.Heat},
                {"key": "hvacHeaterIsOn",    "value": is_heating},
                {"key": "last_seen",         "value": ts},
                {"key": "online",            "value": "true"},
            ]
            # Only update zone_controller_id if non-empty — direct TRV messages
            # (e.g. 04:xxxxxx --:------ 04:xxxxxx 30C9) carry no 01: controller
            # address and must not overwrite a valid stored ID with an empty string.
            if controller_id:
                state_updates.append({"key": "zone_controller_id", "value": controller_id})
            dev.updateStatesOnServer(state_updates)
            if self.debug:
                self.logger.debug(f"Zone {zone_idx} temp -> {temp_c:.2f}degC")
        except Exception as exc:
            self.logger.error(f"Error updating Zone {zone_idx} temp state: {exc}")

    def _apply_setpoint_update(self, zone_idx, data):
        """Update setpointHeat (built-in thermostat state). Creates device if not yet known.

        Only called when a 2309 (setpoint) message arrives WITHOUT a concurrent 2349
        (zone mode) message — meaning the zone is on schedule. Infers zone_mode = 'schedule'.
        If a 2349 arrives in the same poll cycle, _apply_mode_update() runs instead.
        """
        dev = self._find_zone_device(zone_idx)
        if dev is None:
            dev = self._create_zone_device(zone_idx, data.get("controller_id", ""))
        if dev is None:
            return

        setpoint_c    = data["setpoint"]
        controller_id = data.get("controller_id", "")
        ts            = self._format_ts(data.get("ts", ""))

        try:
            state_updates = [
                {"key": "setpointHeat", "value": round(setpoint_c, 2),
                 "uiValue": f"{setpoint_c:.2f} degC"},
                {"key": "zone_mode",    "value": "schedule"},
                {"key": "last_seen",    "value": ts},
                {"key": "online",       "value": "true"},
            ]
            if controller_id:
                state_updates.append({"key": "zone_controller_id", "value": controller_id})
            dev.updateStatesOnServer(state_updates)
            if self.debug:
                self.logger.debug(f"Zone {zone_idx} setpoint -> {setpoint_c:.2f}degC (schedule)")
        except Exception as exc:
            self.logger.error(f"Error updating Zone {zone_idx} setpoint state: {exc}")

    def _apply_mode_update(self, zone_idx, data):
        """Update zone_mode and setpointHeat from 2349 (zone mode/override) message."""
        dev = self._find_zone_device(zone_idx)
        if dev is None:
            dev = self._create_zone_device(zone_idx, data.get("controller_id", ""))
        if dev is None:
            return

        setpoint_c    = data.get("setpoint", 0.0)
        mode_str      = data.get("mode", "schedule")
        controller_id = data.get("controller_id", "")
        ts            = self._format_ts(data.get("ts", ""))

        try:
            state_updates = [
                {"key": "setpointHeat", "value": round(setpoint_c, 2),
                 "uiValue": f"{setpoint_c:.2f} degC"},
                {"key": "zone_mode",    "value": mode_str},
                {"key": "last_seen",    "value": ts},
                {"key": "online",       "value": "true"},
            ]
            if controller_id:
                state_updates.append({"key": "zone_controller_id", "value": controller_id})
            dev.updateStatesOnServer(state_updates)
            if self.debug:
                self.logger.debug(
                    f"Zone {zone_idx} mode -> {mode_str} "
                    f"setpoint -> {setpoint_c:.2f}degC"
                )
        except Exception as exc:
            self.logger.error(f"Error updating Zone {zone_idx} mode state: {exc}")

    def _apply_offline_update(self, zone_idx):
        """Mark a zone device as offline (called after MQTT disconnect)."""
        dev = self._find_zone_device(zone_idx)
        if dev is None:
            return
        try:
            dev.updateStatesOnServer([
                {"key": "online",    "value": "false"},
                {"key": "last_seen", "value": "MQTT disconnected"},
            ])
        except Exception as exc:
            self.logger.error(f"Error setting Zone {zone_idx} offline: {exc}")

    def _apply_zone_name_update(self, zone_idx, name):
        """
        Store zone name in device state and rename the Indigo device if it still has
        the auto-generated name (e.g. 'RAMSES Zone 3'). Main thread only.

        Renaming only happens once: if the user has already renamed the device manually
        we leave it alone. We detect the auto-generated name by checking whether it
        matches the pattern 'RAMSES Zone <N>'.
        """
        dev = self._find_zone_device(zone_idx)
        if dev is None:
            # Device may not exist yet (name arrived before first temp). Just log.
            if self.debug:
                self.logger.debug(
                    f"Zone {zone_idx} name '{name}' received but device not yet created - "
                    f"will apply when device is created"
                )
            return

        try:
            # Always store the zone name as a device state
            current_stored = dev.states.get("zone_name", "")
            if current_stored != name:
                dev.updateStatesOnServer([{"key": "zone_name", "value": name}])
                self.logger.info(f"Zone {zone_idx} name state set to '{name}'")

            # Rename the Indigo device only if it still has the auto-generated name
            auto_name = f"RAMSES Zone {zone_idx}"
            if dev.name == auto_name:
                new_dev_name = f"RAMSES {name}"
                try:
                    dev.name = new_dev_name
                    dev.replaceOnServer()
                    self.logger.info(
                        f"Zone {zone_idx} device renamed: '{auto_name}' -> '{new_dev_name}'"
                    )
                except Exception as exc:
                    self.logger.warning(
                        f"Could not rename Zone {zone_idx} device to '{new_dev_name}': {exc}"
                    )
            elif self.debug:
                self.logger.debug(
                    f"Zone {zone_idx} device already named '{dev.name}' - not auto-renaming"
                )

        except Exception as exc:
            self.logger.error(f"Error applying zone name update for Zone {zone_idx}: {exc}")

    # --------------------------------------------------------------------------
    # TX / Command Publishing
    # --------------------------------------------------------------------------

    def _gateway_tx_topic(self):
        """Return the MQTT topic for sending commands to the RAMSES-ESP gateway."""
        return f"{RAMSES_ROOT}/{self.gateway_id}/tx"

    def _publish_setpoint(self, zone_idx, setpoint_c):
        """
        Publish a W 2309 setpoint command to the gateway tx topic.

        RAMSES-II W command format:
          W --- <gw_addr> <controller_id> --:------ 2309 003 ZZXXYY
        where:
          ZZ   = zone_idx as 2 hex chars
          XXYY = setpoint * 100 as big-endian 16-bit hex (4 chars)

        Example: Zone 1, 21.5 degC -> setpoint * 100 = 2150 = 0x0866
          payload_hex = "010866"
          msg = "W --- 18:730 01:123456 --:------ 2309 003 010866"
        """
        try:
            # Look up controller ID from the zone's device state
            dev = self._find_zone_device(zone_idx)
            if dev is None:
                self.logger.error(
                    f"Cannot publish setpoint - Zone {zone_idx} device not found"
                )
                return False

            controller_id = dev.states.get("zone_controller_id", "")
            if not controller_id or not controller_id.startswith("01:"):
                self.logger.error(
                    f"Cannot publish setpoint for Zone {zone_idx} - "
                    f"no valid controller ID (got '{controller_id}'). "
                    f"Wait for a 30C9 or 2309 message to be received first."
                )
                return False

            # Encode setpoint: multiply by 100, clamp within valid RAMSES range
            raw_setpoint = int(round(setpoint_c * TEMP_SCALE))
            raw_setpoint = max(0, min(raw_setpoint, TEMP_UNKNOWN_RAW - 1))

            payload_hex = f"{zone_idx:02X}{raw_setpoint:04X}"

            # Normalise gateway address format (wiki shows 18:730, but device may use 18-730)
            gw_addr = self.gateway_id.replace("-", ":")

            msg_str   = f"W --- {gw_addr} {controller_id} --:------ 2309 003 {payload_hex}"
            tx_payload = json.dumps({"msg": msg_str})
            topic     = self._gateway_tx_topic()

            with self.mqtt_lock:
                if self.mqtt_client is None or not self.mqtt_connected:
                    self.logger.error(
                        f"Cannot publish setpoint for Zone {zone_idx} - MQTT not connected"
                    )
                    return False
                self.mqtt_client.publish(topic, tx_payload, qos=0)

            self.logger.info(
                f"Setpoint {setpoint_c:.2f}degC sent to Zone {zone_idx} "
                f"via {topic} | msg: {msg_str}"
            )
            return True

        except Exception as exc:
            self.logger.error(
                f"Error publishing setpoint for Zone {zone_idx}: {exc}"
            )
            return False

    def _request_zone_names(self):
        """
        Send RQ 0004 for each zone to ask the controller to broadcast zone names.
        The controller responds with RP 0004 per zone, which is processed by
        _parse_opcode_0004() — populating the zone_name state on each device.
        Called once after MQTT connects when a controller_id is first available.

        Returns True if at least one RQ was sent; False if no controller_id yet.
        """
        # Find a valid controller_id from any zone device
        controller_id = ""
        for zone_idx in range(12):
            dev = self._find_zone_device(zone_idx)
            if dev:
                cid = dev.states.get("zone_controller_id", "")
                if cid.startswith("01:"):
                    controller_id = cid
                    break

        if not controller_id:
            if self.debug:
                self.logger.debug("RQ 0004: no controller_id available yet - will retry")
            return False

        success_count = 0
        for zone_idx in range(12):
            zone_hex = f"{zone_idx:02X}"
            gw_addr  = self.gateway_id.replace("-", ":")
            msg_str  = f"RQ --- {gw_addr} {controller_id} --:------ 0004 001 {zone_hex}"
            try:
                with self.mqtt_lock:
                    if self.mqtt_client and self.mqtt_connected:
                        topic = self._gateway_tx_topic()
                        self.mqtt_client.publish(topic, json.dumps({"msg": msg_str}), qos=0)
                        success_count += 1
            except Exception as exc:
                self.logger.warning(f"Error sending RQ 0004 for Zone {zone_idx}: {exc}")

        if success_count:
            self.logger.info(
                f"Sent RQ 0004 for {success_count} zones to populate zone_name states"
            )
        return success_count > 0

    # --------------------------------------------------------------------------
    # Helpers
    # --------------------------------------------------------------------------

    def _get_or_create_folder(self, folder_name):
        """Return the Indigo device folder ID for folder_name, creating it if needed.
        Must be called from the main thread only."""
        for folder in indigo.devices.folders:
            if folder.name == folder_name:
                return folder.id
        self.logger.info(f"Creating device folder: '{folder_name}'")
        new_folder = indigo.devices.folder.create(folder_name)
        return new_folder.id

    def _format_ts(self, ts_raw):
        """Convert an ISO 8601 gateway timestamp to a clean local datetime string.

        The RAMSES-ESP firmware timestamps the rx messages using its system clock.
        Until NTP synchronises successfully, the ESP32 defaults to Unix epoch (1970),
        so timestamps like "1970-01-01T05:42:17+00:00" are normal on first boot.
        Any timestamp before EPOCH_SENTINEL_YEAR is treated as invalid; a one-time
        warning is logged and the current local system time is substituted instead.

        Falls back to current local time if ts_raw cannot be parsed at all.
        """
        try:
            dt = datetime.fromisoformat(ts_raw)      # parse ISO 8601 (with tz offset)
            if dt.year < EPOCH_SENTINEL_YEAR:
                # Gateway NTP has not synced yet - ts is meaningless (epoch since boot)
                if not getattr(self, '_ntp_warn_logged', False):
                    self.logger.info(
                        f"Gateway timestamp is pre-NTP ({ts_raw[:19]}) - "
                        f"firmware NTP not synced. Using local time for last_seen."
                    )
                    self._ntp_warn_logged = True
                return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # Valid timestamp - reset the warning flag for next time
            self._ntp_warn_logged = False
            return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _read_prefs(self):
        """Load MQTT settings and gateway ID from plugin preferences."""
        prefs = self.pluginPrefs
        self.broker_host     = prefs.get("mqtt_broker_host",     "192.168.1.x").strip()
        self.broker_port     = int(prefs.get("mqtt_broker_port", 1883))
        self.broker_username = prefs.get("mqtt_username",        "").strip()
        self.broker_password = prefs.get("mqtt_password",        "").strip()
        self.debug           = bool(prefs.get("debug_logging",   False))

        # Extract gateway ID: use regex to find the first valid RAMSES device address
        # (format NN:NNNNNN, e.g. "18:203052"). This handles corruption where the user
        # typed the ID multiple times so Indigo stored "18:20305218:20305218:..." with
        # no whitespace — simple strip() cannot fix that, but regex can.
        raw_gw_id = prefs.get("discovered_gateway_id", "")
        # Pattern: exactly 2 digits, colon, exactly 6 digits, NOT followed by another digit.
        # \b doesn't work here because ':' is not a word character, so we use (?!\d) instead.
        # e.g. "18:20305218:203052" -> matches "18:203052" (the one NOT followed by a digit)
        match = re.search(r'(\d{2}:\d{6})(?!\d)', raw_gw_id)
        if match:
            self.gateway_id = match.group(1)
        else:
            self.gateway_id = raw_gw_id.strip()   # empty string or already valid

        # If the stored value was corrupted, rewrite it with the clean version
        if self.gateway_id != raw_gw_id:
            try:
                prefs["discovered_gateway_id"] = self.gateway_id
                self.pluginPrefs = prefs
                self.logger.info(
                    f"Gateway ID sanitised: was {repr(raw_gw_id)}, "
                    f"now {repr(self.gateway_id)}"
                )
            except Exception as exc:
                self.logger.warning(f"Could not save sanitised gateway ID: {exc}")
