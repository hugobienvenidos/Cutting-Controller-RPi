"""
Point d'entrée du contrôleur Fish3 (Raspberry Pi).

Démarre 4 threads indépendants :
- gpio_thread   : CP-IO22 (machine Cutting/CIP, pilotage direct 24V)
- modbus_thread : maître Modbus RTU RS485 (VFD1/2, Gutting Left/Right, Vision Left/Right)
- logic_thread  : règles métier (cycle CIP 3 zones), seul point où décider des actions
- mqtt_thread   : publie l'état + s'abonne aux commandes des paramètres writable

Les paramètres CIP (activation par zone, durées ON/OFF) sont des réglages
locaux, gérés via MQTT ou directement dans le SharedState — pas de Modbus
slave pour ça.

Le thread principal lance le dashboard de monitoring (Pygame) — contrainte
obligatoire, Pygame veut son event loop sur le thread principal.

Prérequis :
- pigpiod démarré : `sudo pigpiod`
- pymodbus installé : `pip install pymodbus==3.12.0`
- paho-mqtt installé : `pip install paho-mqtt`
- pygame installé : `pip install pygame`
- Environnement graphique pour le dashboard (bureau RPi OS, ou `ssh -X`/VNC)

Utilisation :
    python main.py            # avec dashboard graphique
    python main.py --no-gui   # sans interface (déploiement headless / service systemd)
"""

import logging
import sys
import threading
import time

from shared_state import SharedState
from io_cutting import gpio_thread
from modbus_master import modbus_thread
from logic import logic_thread
from mqtt_bridge import mqtt_thread

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(threadName)s] %(levelname)s: %(message)s",
)

log = logging.getLogger(__name__)


def main():
    no_gui = "--no-gui" in sys.argv

    state = SharedState()
    stop_event = threading.Event()

    threads = [
        threading.Thread(target=gpio_thread, args=(state, stop_event), name="GPIO", daemon=True),
        threading.Thread(target=modbus_thread, args=(state, stop_event), name="Modbus", daemon=True),
        threading.Thread(target=logic_thread, args=(state, stop_event), name="Logic", daemon=True),
        threading.Thread(target=mqtt_thread, args=(state, stop_event), name="MQTT", daemon=True),
    ]

    for t in threads:
        t.start()

    log.info("Contrôleur Fish3 démarré")

    if no_gui:
        log.info("Mode --no-gui (Ctrl+C pour arrêter)")
        try:
            while True:
                for t in threads:
                    if not t.is_alive():
                        log.error("Thread %s s'est arrêté de manière inattendue !", t.name)
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    else:
        from pygame_dashboard import run_pygame_dashboard
        log.info("Dashboard Pygame démarré (Echap ou ferme la fenêtre pour arrêter)")
        run_pygame_dashboard(state, stop_event)  # bloque ici jusqu'à fermeture de la fenêtre

    log.info("Arrêt demandé, fermeture propre...")
    stop_event.set()
    for t in threads:
        t.join(timeout=2)
    log.info("Arrêt terminé")


if __name__ == "__main__":
    main()
