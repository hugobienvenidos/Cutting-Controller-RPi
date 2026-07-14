"""
État partagé entre les threads GPIO, Modbus et logique métier.

C'est le seul point de contact entre les threads : personne ne s'appelle
directement, tout passe par cet objet protégé par un lock.
"""

import copy
import threading


class SharedState:
    def __init__(self):
        self._lock = threading.Lock()
        self._data = {
            "gpio_in": {},    # dernières valeurs lues sur le CP-IO22 (entrées)
            "gpio_out": {},   # demandes de sortie à appliquer sur le CP-IO22
            "modbus": {},     # dernières lectures par device Modbus (dict par nom)
            "modbus_errors": {},  # dernier message d'erreur par device (ou None si OK)
            "modbus_out": {},  # demandes d'écriture en attente : {device: {"speed": 1200}}
        }

    # --- GPIO ---
    def set_gpio_in(self, key: str, value: bool):
        with self._lock:
            self._data["gpio_in"][key] = value

    def request_gpio_out(self, key: str, value: bool):
        with self._lock:
            self._data["gpio_out"][key] = value

    # --- Modbus ---
    def set_modbus(self, device: str, values: dict):
        with self._lock:
            self._data["modbus"][device] = values
            self._data["modbus_errors"][device] = None

    def set_modbus_error(self, device: str, message: str):
        with self._lock:
            self._data["modbus_errors"][device] = message

    def request_modbus_write(self, device: str, field: str, value):
        """Appelé par logic_thread pour demander une écriture (ex: vitesse VFD, DOL ON/OFF)."""
        with self._lock:
            self._data["modbus_out"].setdefault(device, {})[field] = value

    def pop_modbus_writes(self) -> dict:
        """Appelé par modbus_thread : récupère et vide la file de demandes en attente."""
        with self._lock:
            pending = self._data["modbus_out"]
            self._data["modbus_out"] = {}
            return pending

    # --- Lecture globale (snapshot) ---
    def snapshot(self) -> dict:
        """Retourne une copie complète et cohérente de l'état courant."""
        with self._lock:
            return copy.deepcopy(self._data)
