"""
mqtt_bridge.py — Pont MQTT pour le contrôleur Fish3.

Publie en LECTURE SEULE l'état de tous les esclaves (VFD1/2, Gutting Left/Right,
Vision Left/Right) + GPIO, et s'abonne aux topics de commande pour les
paramètres inscriptibles (holding registers). Une commande reçue prend effet
via le même mécanisme que le reste du code (request_gpio_out /
request_modbus_write) — aucune logique dupliquée ici.

Topics :
  Publication (retained, lecture seule) :
    <prefix>/<device>/state           -> JSON {"timestamp": ISO8601, ...valeurs...}
    <prefix>/gpio/state                -> JSON {"timestamp": ..., "in": {...}, "out": {...}}
    <prefix>/cip_cutting/state         -> JSON {"timestamp": ..., "enable": bool, "on_time": ms, "off_time": ms, "state": 0/1/2}
    <prefix>/cip_hybrid_left/state     -> idem
    <prefix>/cip_hybrid_right/state    -> idem

  Abonnement (commande -> prend effet automatiquement) :
    <prefix>/vfd1/set/speed            -> payload = valeur numérique
    <prefix>/vfd1/set/onoff            -> payload = "0"/"1"/"true"/"false"
    <prefix>/vfd2/set/speed, .../onoff
    <prefix>/gutting_left/set/<champ>  -> eject_delay, eject_duration, cip_on,
                                           cip_off, ppr_blade, ppr_wheel1,
                                           ppr_wheel2, blade_rpm_min, debounce_ms
    <prefix>/gutting_right/set/<champ> -> idem
    <prefix>/vision_left/set/ml_model
    <prefix>/vision_right/set/ml_model
    <prefix>/cip_cutting/set/enable     -> payload = "0"/"1"/"true"/"false"
    <prefix>/cip_cutting/set/on_time    -> payload = valeur numérique (ms)
    <prefix>/cip_cutting/set/off_time   -> payload = valeur numérique (ms)
    <prefix>/cip_hybrid_left/set/<champ>  -> idem (enable, on_time, off_time)
    <prefix>/cip_hybrid_right/set/<champ> -> idem

NOTE API paho-mqtt (>=2.1) : callback API v2 (CallbackAPIVersion.VERSION2) —
voir requirements.txt. Signatures on_connect/on_message conformes à cette version.
"""

import json
import logging
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

from config import (
    MQTT_BROKER_HOST, MQTT_BROKER_PORT, MQTT_USE_TLS, MQTT_USERNAME,
    MQTT_PASSWORD, MQTT_CLIENT_ID, MQTT_TOPIC_PREFIX, MQTT_PUBLISH_INTERVAL,
    MQTT_WRITABLE_FIELDS, MODBUS_DEVICES, CIP_ZONE_MQTT_MAP,
)
from shared_state import SharedState

log = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_bool(payload: str) -> bool:
    return payload.strip().lower() in ("1", "true", "on", "yes")


def _device_kind(name: str) -> str | None:
    for kind in ("vfd", "gutting", "vision"):
        if kind in name:
            return kind
    return None


def _writable_fields_for(name: str) -> list[str]:
    kind = _device_kind(name)
    return MQTT_WRITABLE_FIELDS.get(kind, []) if kind else []


def mqtt_thread(state: SharedState, stop_event: threading.Event):
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=MQTT_CLIENT_ID)

    if MQTT_USERNAME:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    if MQTT_USE_TLS:
        client.tls_set()

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            log.info("MQTT connecté à %s:%d", MQTT_BROKER_HOST, MQTT_BROKER_PORT)
            for name in MODBUS_DEVICES:
                for field in _writable_fields_for(name):
                    topic = f"{MQTT_TOPIC_PREFIX}/{name}/set/{field}"
                    client.subscribe(topic)
                    log.info("MQTT abonné : %s", topic)
            for zone in CIP_ZONE_MQTT_MAP:
                for field in ("enable", "on_time", "off_time"):
                    topic = f"{MQTT_TOPIC_PREFIX}/{zone}/set/{field}"
                    client.subscribe(topic)
                    log.info("MQTT abonné : %s", topic)
        else:
            log.error("Échec connexion MQTT (code %s)", reason_code)

    def on_message(client, userdata, msg):
        try:
            parts = msg.topic.split("/")
            if len(parts) != 4 or parts[0] != MQTT_TOPIC_PREFIX or parts[2] != "set":
                return
            _, name, _, field = parts
            payload = msg.payload.decode().strip()

            if name in CIP_ZONE_MQTT_MAP:
                zone_cfg = CIP_ZONE_MQTT_MAP[name]
                if field == "enable":
                    state.set_rpi_coil(zone_cfg["enable_key"], _parse_bool(payload))
                elif field == "on_time":
                    state.set_rpi_holding(zone_cfg["on_time_key"], int(float(payload)))
                elif field == "off_time":
                    state.set_rpi_holding(zone_cfg["off_time_key"], int(float(payload)))
                else:
                    log.warning("MQTT commande sur champ CIP inconnu: %s/%s", name, field)
                    return
                log.info("MQTT commande appliquée : %s/%s = %s", name, field, payload)
                return

            device = name
            if device not in MODBUS_DEVICES:
                log.warning("MQTT commande sur device inconnu: %s", device)
                return
            if field not in _writable_fields_for(device):
                log.warning("MQTT commande sur champ non-writable: %s/%s", device, field)
                return

            if field == "onoff":
                value = _parse_bool(payload)
            else:
                value = float(payload) if "." in payload else int(payload)

            state.request_modbus_write(device, field, value)
            log.info("MQTT commande appliquée : %s/%s = %s", device, field, value)

        except Exception as exc:
            log.warning("Erreur traitement message MQTT (%s): %s", msg.topic, exc)

    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(MQTT_BROKER_HOST, MQTT_BROKER_PORT, keepalive=60)
    except Exception as exc:
        log.error("Connexion MQTT impossible (%s:%d) : %s", MQTT_BROKER_HOST, MQTT_BROKER_PORT, exc)
        return

    client.loop_start()
    log.info("Thread MQTT démarré")

    try:
        while not stop_event.is_set():
            snap = state.snapshot()
            timestamp = _now_iso()

            for device, data in snap["modbus"].items():
                payload = json.dumps({"timestamp": timestamp, **data})
                client.publish(f"{MQTT_TOPIC_PREFIX}/{device}/state", payload, retain=True)

            gpio_payload = json.dumps({
                "timestamp": timestamp,
                "in": snap["gpio_in"],
                "out": snap["gpio_out"],
            })
            client.publish(f"{MQTT_TOPIC_PREFIX}/gpio/state", gpio_payload, retain=True)

            rpi_coils = snap["rpi_coils"]
            rpi_holding = snap["rpi_holding"]
            rpi_input = snap["rpi_input"]
            for zone, zone_cfg in CIP_ZONE_MQTT_MAP.items():
                cip_payload = json.dumps({
                    "timestamp": timestamp,
                    "enable": rpi_coils.get(zone_cfg["enable_key"]),
                    "on_time": rpi_holding.get(zone_cfg["on_time_key"]),
                    "off_time": rpi_holding.get(zone_cfg["off_time_key"]),
                    "state": rpi_input.get(zone_cfg["state_key"]),
                })
                client.publish(f"{MQTT_TOPIC_PREFIX}/{zone}/state", cip_payload, retain=True)

            time.sleep(MQTT_PUBLISH_INTERVAL)
    finally:
        client.loop_stop()
        client.disconnect()
        log.info("Thread MQTT arrêté proprement")