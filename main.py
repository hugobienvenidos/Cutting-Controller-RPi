"""
Point d'entrée du contrôleur Fish3 (Raspberry Pi).

Démarre 3 threads indépendants :
- gpio_thread    : CP-IO22 (machine Cutting/CIP, pilotage direct 24V)
- modbus_thread  : maître Modbus RTU RS485 (VFD1/2, Hybrid Left/Right, compteurs)
- logic_thread   : règles métier, seul point où décider des actions

Prérequis :
- pigpiod démarré : `sudo pigpiod`
- pymodbus installé : `pip install pymodbus`
"""

import logging
import threading
import time

from shared_state import SharedState
from io_cutting import gpio_thread
from modbus_master import modbus_thread
from logic import logic_thread

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(threadName)s] %(levelname)s: %(message)s",
)

log = logging.getLogger(__name__)


def main():
    state = SharedState()
    stop_event = threading.Event()

    threads = [
        threading.Thread(target=gpio_thread, args=(state, stop_event), name="GPIO", daemon=True),
        threading.Thread(target=modbus_thread, args=(state, stop_event), name="Modbus", daemon=True),
        threading.Thread(target=logic_thread, args=(state, stop_event), name="Logic", daemon=True),
    ]

    for t in threads:
        t.start()

    log.info("Contrôleur Fish3 démarré (Ctrl+C pour arrêter)")

    try:
        while True:
            # Supervision simple : signale si un thread meurt de manière inattendue
            for t in threads:
                if not t.is_alive():
                    log.error("Thread %s s'est arrêté de manière inattendue !", t.name)
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Arrêt demandé, fermeture propre...")
        stop_event.set()
        for t in threads:
            t.join(timeout=2)
        log.info("Arrêt terminé")


if __name__ == "__main__":
    main()