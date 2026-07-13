"""
API de contrôle des VFD (Belt pocket / Belt infeed).

À utiliser depuis n'importe où (logic.py, une future interface MQTT,
un script de test manuel, etc.) sans avoir à connaître les noms de champs
internes ("speed", "onoff") ni le mécanisme de file d'attente Modbus.
"""

from shared_state import SharedState


def set_vfd_speed(state: SharedState, vfd_name: str, speed_rpm: int):
    """
    Demande un changement de vitesse pour un VFD.
    vfd_name : "vfd1" (Belt pocket) ou "vfd2" (Belt infeed)
    """
    state.request_modbus_write(vfd_name, "speed", speed_rpm)


def set_vfd_power(state: SharedState, vfd_name: str, on: bool):
    """Démarre ou arrête un VFD."""
    state.request_modbus_write(vfd_name, "onoff", on)


def get_vfd_status(state: SharedState, vfd_name: str) -> dict | None:
    """Retourne la dernière lecture connue d'un VFD, ou None si pas encore lue."""
    return state.snapshot()["modbus"].get(vfd_name)