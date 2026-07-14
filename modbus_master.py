"""
Thread Modbus RTU maître : interroge les esclaves sur le bus RS485
(VFD1, VFD2, Hybrid Left, Hybrid Right, compteurs électricité/eau).
"""

import logging
import threading
import time

from pymodbus.client import ModbusSerialClient

from config import (
    SERIAL_PORT, BAUDRATE, PARITY, STOPBITS, BYTESIZE, MODBUS_TIMEOUT,
    MODBUS_DEVICES, MODBUS_POLL_INTERVAL, HYBRID_REGISTERS, VFD_REGISTERS,
    CIP_MIRROR, modicon_offset, CUTTING_CONTROLLER_REGISTERS,
)
from shared_state import SharedState

log = logging.getLogger(__name__)


def _read_onoff_status(client: ModbusSerialClient, addr: int, mirror_cfg: dict) -> bool | None:
    """Lit le bit ON/OFF d'une machine à l'adresse Modicon donnée dans CIP_MIRROR."""
    offset = modicon_offset(mirror_cfg["on_status_address"])
    rtype = mirror_cfg["register_type"]

    if rtype == "holding":
        res = client.read_holding_registers(offset, 1, addr)
        return bool(res.registers[0]) if not res.isError() else None
    if rtype == "input":
        res = client.read_input_registers(offset, 1, addr)
        return bool(res.registers[0]) if not res.isError() else None
    if rtype == "coil":
        res = client.read_coils(offset, 1, addr)
        return res.bits[0] if not res.isError() else None
    if rtype == "discrete":
        res = client.read_discrete_inputs(offset, 1, addr)
        return res.bits[0] if not res.isError() else None
    raise ValueError(f"register_type inconnu: {rtype}")


def _read_hybrid(client: ModbusSerialClient, addr: int, device_name: str) -> dict | None:
    """Lit l'état d'un contrôleur Hybrid Left/Right (statut ON + diagnostics)."""
    r = HYBRID_REGISTERS
    regs = client.read_input_registers(r["input_start"], r["input_count"], addr)
    if regs.isError():
        return None

    onoff = None
    if device_name in CIP_MIRROR:
        onoff = _read_onoff_status(client, addr, CIP_MIRROR[device_name])

    return {
        "onoff": onoff,
        "fish_counter": regs.registers[r["fish_counter_offset"]],
        "good": regs.registers[r["good_offset"]],
        "bad": regs.registers[r["bad_offset"]],
        "belly_pct": regs.registers[r["belly_pct_offset"]] / r["belly_pct_scale"],
    }


def _read_vfd(client: ModbusSerialClient, addr: int) -> dict | None:
    """Lit vitesse + état ON/OFF d'un variateur (registres à adapter selon la doc du VFD)."""
    r = VFD_REGISTERS
    regs = client.read_holding_registers(r["holding_start"], r["holding_count"], addr)
    if regs.isError():
        return None
    return {
        "speed": regs.registers[r["speed_offset"]],
        "onoff": bool(regs.registers[r["onoff_offset"]]),
    }


def _read_cutting_controller(client: ModbusSerialClient, addr: int) -> dict | None:
    """Lit la télémétrie du Cutting/Gutting Controller (ESP32-S3). CIP volontairement ignoré."""
    r = CUTTING_CONTROLLER_REGISTERS
    regs = client.read_input_registers(r["input_start"], r["input_count"], addr)
    if regs.isError():
        return None
    reg = regs.registers
    return {
        "rpm_blade": reg[r["rpm_blade_offset"]],
        "rpm_wheel1": reg[r["rpm_wheel1_offset"]],
        "rpm_wheel2": reg[r["rpm_wheel2_offset"]],
        "ejector_state": reg[r["ejector_state_offset"]],  # 0 idle, 1 wait, 2 fire
        "ejector_count": reg[r["ejector_count_lo_offset"]] | (reg[r["ejector_count_hi_offset"]] << 16),
        "motor_trip": bool(reg[r["motor_trip_offset"]]),
        "motor_on": bool(reg[r["motor_on_offset"]]),
        "belt": bool(reg[r["belt_offset"]]),
        "belly": bool(reg[r["belly_offset"]]),
        "alarm_mask": reg[r["alarm_mask_offset"]],
        "alarm_unack": reg[r["alarm_unack_offset"]],
        "uptime_s": reg[r["uptime_lo_offset"]] | (reg[r["uptime_hi_offset"]] << 16),
        "fw_version": reg[r["fw_version_offset"]],
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
                except Exception as exc:
                    log.warning("Erreur écriture Modbus sur %s: %s", name, exc)
                    state.set_modbus_error(name, str(exc))

            # 2. Puis lit l'état de chaque esclave
            for name, addr in MODBUS_DEVICES.items():
                try:
                    if name == "cutting_controller":
                        data = _read_cutting_controller(client, addr)
                    elif "hybrid" in name:
                        data = _read_hybrid(client, addr, name)
                    elif "vfd" in name:
                        data = _read_vfd(client, addr)
                    else:
                        # elec_meter / water_meter : à implémenter selon leur doc Modbus
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
    client.write_register(VFD_REGISTERS["speed_offset"], speed_rpm, addr)


def write_vfd_onoff(client: ModbusSerialClient, addr: int, state_on: bool):
    client.write_register(VFD_REGISTERS["onoff_offset"], 1 if state_on else 0, addr)