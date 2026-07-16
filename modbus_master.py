"""
Thread Modbus RTU maître : interroge les esclaves sur le bus RS485
(VFD1, VFD2, Gutting Machine Left/Right, Vision System Left/Right).

Adresses conformes à Modbus_Addresses_Cutting_Gutting_RPI.xlsx.

NOTE API pymodbus : ce projet est figé sur la version 3.12.0 (voir requirements.txt).
count et l'identifiant esclave sont keyword-only et se nomment "device_id"
(anciennement "slave") dans cette version. La 3.14+ a cassé l'API serveur
(ModbusDeviceContext dépréciée au profit de SimData/SimDevice), d'où le pin
strict sur 3.12.0 plutôt qu'un ">=".
"""

import logging
import threading
import time

from pymodbus.client import ModbusSerialClient

from config import (
    SERIAL_PORT, BAUDRATE, PARITY, STOPBITS, BYTESIZE, MODBUS_TIMEOUT,
    MODBUS_DEVICES, MODBUS_POLL_INTERVAL, GUTTING_REGISTERS, VISION_REGISTERS,
    VFD_REGISTERS,
)
from shared_state import SharedState

log = logging.getLogger(__name__)


def _read_gutting(client: ModbusSerialClient, addr: int) -> dict | None:
    """
    Lit l'état complet d'une Gutting Machine (Left ou Right) : RPM, éjecteur,
    trip, "onoff" (= Motor ON, utilisé pour le miroir CIP), alarmes, etc.
    CIP State est lu à titre de télémétrie seule (la RPi pilote le CIP elle-même).
    """
    r = GUTTING_REGISTERS
    regs = client.read_input_registers(r["input_start"], count=r["input_count"], device_id=addr)
    if regs.isError():
        return None
    reg = regs.registers
    return {
        "rpm_blade": reg[r["rpm_blade_offset"]],
        "rpm_wheel1": reg[r["rpm_wheel1_offset"]],
        "rpm_wheel2": reg[r["rpm_wheel2_offset"]],
        "ejector_state": reg[r["ejector_state_offset"]],  # 0 idle, 1 wait, 2 fire
        "ejector_count": reg[r["ejector_count_lo_offset"]] | (reg[r["ejector_count_hi_offset"]] << 16),
        "cip_state": reg[r["cip_state_offset"]],           # télémétrie seule
        "motor_trip": bool(reg[r["motor_trip_offset"]]),
        "onoff": bool(reg[r["motor_on_offset"]]),          # "Motor ON" -> miroir CIP
        "belt": bool(reg[r["belt_offset"]]),
        "belly": bool(reg[r["belly_offset"]]),
        "alarm_mask": reg[r["alarm_mask_offset"]],
        "alarm_unack": reg[r["alarm_unack_offset"]],
        "uptime_s": reg[r["uptime_lo_offset"]] | (reg[r["uptime_hi_offset"]] << 16),
        "fw_version": reg[r["fw_version_offset"]],
    }


def _read_vision(client: ModbusSerialClient, addr: int) -> dict | None:
    """Lit les compteurs d'un Vision System (fish counter, good/bad, ejected fish)."""
    r = VISION_REGISTERS
    regs = client.read_input_registers(r["input_start"], count=r["input_count"], device_id=addr)
    if regs.isError():
        return None
    return {
        "fish_counter": regs.registers[r["fish_counter_offset"]],
        "good_bad": regs.registers[r["good_bad_offset"]],
        "ejected_fish": regs.registers[r["ejected_fish_offset"]],
    }


def _read_vfd(client: ModbusSerialClient, addr: int) -> dict | None:
    """Lit vitesse + état ON/OFF d'un variateur (registres à adapter selon la doc du VFD)."""
    r = VFD_REGISTERS
    regs = client.read_holding_registers(r["holding_start"], count=r["holding_count"], device_id=addr)
    if regs.isError():
        return None
    return {
        "speed": regs.registers[r["speed_offset"]],
        "onoff": bool(regs.registers[r["onoff_offset"]]),
    }


def modbus_thread(state: SharedState, stop_event: threading.Event):
    client = ModbusSerialClient(
        port=SERIAL_PORT, baudrate=BAUDRATE, parity=PARITY,
        stopbits=STOPBITS, bytesize=BYTESIZE, timeout=MODBUS_TIMEOUT,
    )

    if not client.connect():
        log.error("Connexion RS485 impossible sur %s", SERIAL_PORT)
        return

    log.info("Thread Modbus démarré (%d esclaves)", len(MODBUS_DEVICES))

    try:
        while not stop_event.is_set():
            # 1. Applique d'abord les demandes d'écriture en attente (priorité aux commandes)
            pending_writes = state.pop_modbus_writes()
            for name, fields in pending_writes.items():
                addr = MODBUS_DEVICES.get(name)
                if addr is None:
                    continue
                try:
                    if "vfd" in name:
                        if "speed" in fields:
                            write_vfd_speed(client, addr, fields["speed"])
                        if "onoff" in fields:
                            write_vfd_onoff(client, addr, fields["onoff"])
                    elif "gutting" in name:
                        for field, value in fields.items():
                            write_gutting_param(client, addr, field, value)
                    elif "vision" in name:
                        for field, value in fields.items():
                            write_vision_param(client, addr, field, value)
                except Exception as exc:
                    log.warning("Erreur écriture Modbus sur %s: %s", name, exc)
                    state.set_modbus_error(name, str(exc))

            # 2. Puis lit l'état de chaque esclave
            for name, addr in MODBUS_DEVICES.items():
                try:
                    if "gutting" in name:
                        data = _read_gutting(client, addr)
                    elif "vision" in name:
                        data = _read_vision(client, addr)
                    elif "vfd" in name:
                        data = _read_vfd(client, addr)
                    else:
                        continue

                    if data is not None:
                        state.set_modbus(name, data)
                    else:
                        state.set_modbus_error(name, "réponse Modbus en erreur")

                except Exception as exc:
                    log.warning("Erreur Modbus sur %s (adresse %d): %s", name, addr, exc)
                    state.set_modbus_error(name, str(exc))

            time.sleep(MODBUS_POLL_INTERVAL)
    finally:
        client.close()
        log.info("Thread Modbus arrêté proprement")


def write_vfd_speed(client: ModbusSerialClient, addr: int, speed_rpm: int):
    client.write_register(VFD_REGISTERS["speed_offset"], speed_rpm, device_id=addr)


def write_vfd_onoff(client: ModbusSerialClient, addr: int, state_on: bool):
    client.write_register(VFD_REGISTERS["onoff_offset"], 1 if state_on else 0, device_id=addr)


def write_gutting_param(client: ModbusSerialClient, addr: int, field: str, value):
    """Écrit un paramètre R/W (holding register) d'une Gutting Machine, ex: 'eject_delay'."""
    offset_key = f"hr_{field}_offset"
    if offset_key not in GUTTING_REGISTERS:
        raise ValueError(f"Champ inconnu pour Gutting Machine: {field}")
    client.write_register(GUTTING_REGISTERS[offset_key], int(value), device_id=addr)


def write_vision_param(client: ModbusSerialClient, addr: int, field: str, value):
    """Écrit un paramètre R/W (holding register) d'un Vision System, ex: 'ml_model'."""
    offset_key = f"hr_{field}_offset"
    if offset_key not in VISION_REGISTERS:
        raise ValueError(f"Champ inconnu pour Vision System: {field}")
    client.write_register(VISION_REGISTERS[offset_key], int(value), device_id=addr)
