"""
Thread GPIO : lecture des entrées et écriture des sorties du CP-IO22.

Gère la machine "Cutting/CIP" pilotée en direct (pas de Modbus ici).
"""

import logging
import threading
import time

import pigpio

from config import GPIO_IN, GPIO_OUT, GPIO_POLL_INTERVAL
from shared_state import SharedState

log = logging.getLogger(__name__)


def gpio_thread(state: SharedState, stop_event: threading.Event):
    pi = pigpio.pi()
    if not pi.connected:
        log.error("Impossible de se connecter à pigpiod (démarré ? `sudo pigpiod`)")
        return

    for name, pin in GPIO_IN.items():
        pi.set_mode(pin, pigpio.INPUT)
        # PUD_DOWN par défaut : à adapter selon le câblage (opto NPN/PNP)
        pi.set_pull_up_down(pin, pigpio.PUD_DOWN)

    for name, pin in GPIO_OUT.items():
        pi.set_mode(pin, pigpio.OUTPUT)
        pi.write(pin, 0)  # état de repos sécurisé au démarrage

    log.info("Thread GPIO démarré (%d entrées, %d sorties)", len(GPIO_IN), len(GPIO_OUT))

    try:
        while not stop_event.is_set():
            # 1. Lecture des entrées
            for name, pin in GPIO_IN.items():
                state.set_gpio_in(name, bool(pi.read(pin)))

            # 2. Application des sorties demandées par le thread logique
            snap = state.snapshot()
            for name, value in snap["gpio_out"].items():
                if name in GPIO_OUT:
                    pi.write(GPIO_OUT[name], 1 if value else 0)

            time.sleep(GPIO_POLL_INTERVAL)
    finally:
        # Sécurité : on coupe toutes les sorties en sortant du thread
        for pin in GPIO_OUT.values():
            pi.write(pin, 0)
        pi.stop()
        log.info("Thread GPIO arrêté proprement")