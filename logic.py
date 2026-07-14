"""
Thread logique métier : c'est le SEUL fichier où doivent vivre les règles.

Logique (simple) :
- DOL Trip actif -> coupe TOUT le CIP (cutting + gutting left + gutting right).
- Sinon, chaque sortie CIP suit en miroir l'état ON/OFF de sa machine
  (Hybrid Left ON -> CIP Left ON, etc.), défini dans config.CIP_MIRROR.
- Le cutting suit le DOL Cutting ON/OFF.
"""

import logging
import threading
import time

from config import CIP_MIRROR, MODBUS_DEVICES, LOGIC_INTERVAL
from shared_state import SharedState
from vfd_control import set_vfd_power

log = logging.getLogger(__name__)


def logic_thread(state: SharedState, stop_event: threading.Event):
    log.info("Thread logique démarré")

    while not stop_event.is_set():
        snap = state.snapshot()
        gpio_in = snap["gpio_in"]
        modbus = snap["modbus"]

        trip_active = bool(gpio_in.get("dol_trip"))

        if trip_active:
            # Sécurité : le trip coupe tout le CIP + les 2 VFD, sans exception.
            state.request_gpio_out("cip_cutting", False)
            for mirror_cfg in CIP_MIRROR.values():
                state.request_gpio_out(mirror_cfg["cip_output"], False)
            for vfd_name in MODBUS_DEVICES:
                if "vfd" in vfd_name:
                    set_vfd_power(state, vfd_name, False)
            log.warning("DOL Trip actif -> CIP et VFD coupés")
        else:
            # Cutting piloté par son propre ON/OFF
            state.request_gpio_out("cip_cutting", bool(gpio_in.get("dol_cutting_onoff")))

            # Miroir direct pour chaque machine définie dans CIP_MIRROR
            for device_name, mirror_cfg in CIP_MIRROR.items():
                data = modbus.get(device_name)
                machine_on = bool(data.get("onoff")) if data else False
                state.request_gpio_out(mirror_cfg["cip_output"], machine_on)

        time.sleep(LOGIC_INTERVAL)

    log.info("Thread logique arrêté proprement")
