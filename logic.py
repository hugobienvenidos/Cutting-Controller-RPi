"""
Thread logique métier : c'est le SEUL fichier où doivent vivre les règles.

Nouvelle logique CIP (3 zones indépendantes : Cutting, Hybrid Left, Hybrid Right) :
- Chaque zone est activée/désactivée via un coil (rpi_coils), écrit par un
  maître Modbus externe via rpi_slave_thread (adresse 3).
- Chaque zone cycle ON_TIME/OFF_TIME (ms), réglable via holding registers
  (rpi_holding), également piloté par ce même maître externe.
- DOL Trip coupe TOUT (CIP + VFD), quel que soit l'état des coils ENABLE.
- L'état de chaque zone (0 idle, 1 on, 2 off) et la télémétrie GPIO
  (presence, DOL Blades Trip/State) sont publiés dans rpi_input, exposés en
  lecture par rpi_slave_thread.
"""

import logging
import threading
import time

from config import MODBUS_DEVICES, LOGIC_INTERVAL
from shared_state import SharedState
from vfd_control import set_vfd_power
from cip_zones import CipZoneTimer

log = logging.getLogger(__name__)

# Association zone CIP -> sortie GPIO / clés coil+holding+state correspondantes
ZONES = {
    "cutting": {
        "gpio_output": "cip_cutting",
        "enable_coil": "cip_cutting_enable",
        "on_time_key": "cutting_on_time",
        "off_time_key": "cutting_off_time",
        "state_key": "cip_cutting_state",
    },
    "hybrid_left": {
        "gpio_output": "cip_hybrid_left",
        "enable_coil": "cip_hybrid_left_enable",
        "on_time_key": "hybrid_left_on_time",
        "off_time_key": "hybrid_left_off_time",
        "state_key": "cip_hybrid_left_state",
    },
    "hybrid_right": {
        "gpio_output": "cip_hybrid_right",
        "enable_coil": "cip_hybrid_right_enable",
        "on_time_key": "hybrid_right_on_time",
        "off_time_key": "hybrid_right_off_time",
        "state_key": "cip_hybrid_right_state",
    },
}


def logic_thread(state: SharedState, stop_event: threading.Event):
    log.info("Thread logique démarré")
    timers = {zone: CipZoneTimer() for zone in ZONES}

    while not stop_event.is_set():
        snap = state.snapshot()
        gpio_in = snap["gpio_in"]
        rpi_coils = snap["rpi_coils"]
        rpi_holding = snap["rpi_holding"]

        trip_active = bool(gpio_in.get("dol_trip"))

        if trip_active:
            for vfd_name in MODBUS_DEVICES:
                if "vfd" in vfd_name:
                    set_vfd_power(state, vfd_name, False)
            log.warning("DOL Trip actif -> CIP et VFD coupés")

        # --- Cycle CIP par zone ---
        for zone, cfg in ZONES.items():
            enabled = bool(rpi_coils.get(cfg["enable_coil"], False))
            on_time = rpi_holding.get(cfg["on_time_key"], 2000)
            off_time = rpi_holding.get(cfg["off_time_key"], 8000)

            output, state_code = timers[zone].update(
                enabled=enabled, on_time_ms=on_time, off_time_ms=off_time, force_off=trip_active,
            )
            state.request_gpio_out(cfg["gpio_output"], output)
            state.set_rpi_input(cfg["state_key"], state_code)

        # --- Télémétrie exposée en Modbus esclave (adresse 3) ---
        presence_mask = 0
        for i in range(1, 5):
            if gpio_in.get(f"presence_{i}"):
                presence_mask |= (1 << (i - 1))
        state.set_rpi_input("presence_mask", presence_mask)
        state.set_rpi_input("dol_blades_trip", int(trip_active))
        state.set_rpi_input(
            "dol_blades_state",
            int(bool(gpio_in.get("dol_cutting_onoff")) and not trip_active),
        )

        time.sleep(LOGIC_INTERVAL)

    log.info("Thread logique arrêté proprement")
