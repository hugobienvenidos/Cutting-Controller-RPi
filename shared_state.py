"""
État partagé entre les threads GPIO, Modbus, logique métier et esclave Modbus RPi.

C'est le seul point de contact entre les threads : personne ne s'appelle
directement, tout passe par cet objet protégé par un lock.
"""

import copy
import threading

from config import RPI_SLAVE_DEFAULT_HOLDING


class SharedState:
    def __init__(self):
        self._lock = threading.Lock()
        self._data = {
            "gpio_in": {},    # dernières valeurs lues sur le CP-IO22 (entrées)
            "gpio_out": {},   # demandes de sortie à appliquer sur le CP-IO22
            "modbus": {},     # dernières lectures par device Modbus (dict par nom)
            "modbus_errors": {},  # dernier message d'erreur par device (ou None si OK)
            "modbus_out": {},  # demandes d'écriture en attente : {device: {"speed": 1200}}

            # --- Rôle "esclave" de la RPi (adresse 3), piloté par un maître externe ---
            "rpi_coils": {
                "cip_cutting_enable": False,
                "cip_hybrid_left_enable": False,
                "cip_hybrid_right_enable": False,
            },
            "rpi_holding": dict(RPI_SLAVE_DEFAULT_HOLDING),  # on/off times CIP (ms)
            "rpi_input": {  # télémétrie calculée par logic_thread, exposée en lecture
                "presence_mask": 0,
                "dol_blades_trip": 0,
                "dol_blades_state": 0,
                "cip_cutting_state": 0,
                "cip_hybrid_left_state": 0,
                "cip_hybrid_right_state": 0,
            },
        }

    # --- GPIO ---
    def set_gpio_in(self, key: str, value: bool):
        with self._lock:
            self._data["gpio_in"][key] = value

    def request_gpio_out(self, key: str, value: bool):
        with self._lock:
            self._data["gpio_out"][key] = value

    # --- Modbus (maître, vers les autres appareils) ---
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

    # --- Rôle esclave RPi (adresse 3) ---
    def set_rpi_coil(self, name: str, value: bool):
        """Appelé par rpi_slave_thread quand un maître externe écrit un coil."""
        with self._lock:
            self._data["rpi_coils"][name] = bool(value)

    def get_rpi_coils(self) -> dict:
        with self._lock:
            return dict(self._data["rpi_coils"])

    def set_rpi_holding(self, name: str, value):
        """Appelé par rpi_slave_thread quand un maître externe écrit un holding register."""
        with self._lock:
            self._data["rpi_holding"][name] = value

    def get_rpi_holding(self) -> dict:
        with self._lock:
            return dict(self._data["rpi_holding"])

    def set_rpi_input(self, name: str, value):
        """Appelé par logic_thread pour publier une valeur de télémétrie (lue par rpi_slave_thread)."""
        with self._lock:
            self._data["rpi_input"][name] = value

    # --- Lecture globale (snapshot) ---
    def snapshot(self) -> dict:
        """Retourne une copie complète et cohérente de l'état courant."""
        with self._lock:
            return copy.deepcopy(self._data)
