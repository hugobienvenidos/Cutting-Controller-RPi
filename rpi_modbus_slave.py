"""
rpi_modbus_slave.py — Expose les I/O de la RPi elle-même comme esclave Modbus
(adresse 3), en plus de son rôle de maître (modbus_master.py) sur les autres
appareils (VFD1/2, Gutting Left/Right, Vision Left/Right).

Transport : Modbus TCP (RPI_SLAVE_TCP_HOST/PORT dans config.py) — pas besoin
d'un 2e adaptateur RS485 physique, juste le réseau. Si un lien RTU est
préféré à la place, remplace ModbusTcpServer par ModbusSerialServer (voir
simulator.py pour le même pattern).

Principe : ce thread fait le pont, dans les deux sens, entre le SharedState
et un datastore Modbus local :
- rpi_input (mis à jour par logic_thread)     -> input registers (lecture externe)
- coils / holding registers écrits en externe -> rpi_coils / rpi_holding
  (relus ensuite par logic_thread pour piloter les 3 zones CIP)

NOTE API pymodbus : ce projet est figé sur la version 3.12.0 (voir requirements.txt) —
la 3.14+ a cassé l'API serveur (ModbusDeviceContext dépréciée au profit de SimData/SimDevice).
"""

import asyncio
import logging
import threading
import time
import traceback

from pymodbus.datastore import ModbusSequentialDataBlock, ModbusServerContext
from pymodbus.server import ModbusTcpServer

# Compatibilité : pymodbus a renommé ModbusSlaveContext -> ModbusDeviceContext
# selon les versions (voir simulator.py pour le même mécanisme).
try:
    from pymodbus.datastore import ModbusDeviceContext as _DeviceContext
except ImportError:
    from pymodbus.datastore import ModbusSlaveContext as _DeviceContext

from config import (
    RPI_SLAVE_ID, RPI_SLAVE_TCP_HOST, RPI_SLAVE_TCP_PORT,
    RPI_SLAVE_COILS, RPI_SLAVE_INPUT_REGISTERS, RPI_SLAVE_HOLDING_REGISTERS,
)
from shared_state import SharedState

log = logging.getLogger(__name__)

BLOCK_SIZE = 20
SYNC_INTERVAL = 0.2  # secondes entre 2 synchronisations shared_state <-> datastore

FX_COIL = 1
FX_HOLDING = 3
FX_INPUT = 4


def _build_context():
    device_ctx = _DeviceContext(
        di=ModbusSequentialDataBlock(0, [0] * BLOCK_SIZE),
        co=ModbusSequentialDataBlock(0, [0] * BLOCK_SIZE),
        hr=ModbusSequentialDataBlock(0, [0] * BLOCK_SIZE),
        ir=ModbusSequentialDataBlock(0, [0] * BLOCK_SIZE),
    )
    try:
        context = ModbusServerContext(devices={RPI_SLAVE_ID: device_ctx}, single=False)
    except TypeError:
        context = ModbusServerContext(slaves={RPI_SLAVE_ID: device_ctx}, single=False)
    return context, device_ctx


def _sync_loop(device_ctx, state: SharedState, stop_event: threading.Event):
    """Synchronise en continu (200 ms) le datastore Modbus <-> le SharedState, dans les 2 sens."""
    while not stop_event.is_set():
        try:
            # 1. Écritures externes (coils/holding) -> shared_state, relues ensuite par logic_thread
            for name, offset in RPI_SLAVE_COILS.items():
                value = device_ctx.getValues(FX_COIL, offset, count=1)[0]
                state.set_rpi_coil(name, bool(value))

            for name, offset in RPI_SLAVE_HOLDING_REGISTERS.items():
                value = device_ctx.getValues(FX_HOLDING, offset, count=1)[0]
                state.set_rpi_holding(name, value)

            # 2. Télémétrie interne (calculée par logic_thread) -> datastore, pour lecture externe
            rpi_input = state.snapshot()["rpi_input"]
            for name, offset in RPI_SLAVE_INPUT_REGISTERS.items():
                device_ctx.setValues(FX_INPUT, offset, [int(rpi_input.get(name, 0))])

        except Exception as exc:
            log.warning("Erreur de synchronisation esclave RPi : %s", exc)

        time.sleep(SYNC_INTERVAL)


def rpi_slave_thread(state: SharedState, stop_event: threading.Event):
    context, device_ctx = _build_context()

    # Valeurs par défaut au démarrage (reprises du SharedState, ex: on/off times CIP)
    holding_snapshot = state.get_rpi_holding()
    for name, offset in RPI_SLAVE_HOLDING_REGISTERS.items():
        device_ctx.setValues(FX_HOLDING, offset, [int(holding_snapshot.get(name, 0))])

    sync_thread = threading.Thread(
        target=_sync_loop, args=(device_ctx, state, stop_event), name="RPiSlaveSync", daemon=True,
    )
    sync_thread.start()

    async def _async_run():
        server = ModbusTcpServer(context=context, address=(RPI_SLAVE_TCP_HOST, RPI_SLAVE_TCP_PORT))
        log.info(
            "Serveur Modbus TCP (esclave RPi, ID=%d) démarré sur %s:%d",
            RPI_SLAVE_ID, RPI_SLAVE_TCP_HOST, RPI_SLAVE_TCP_PORT,
        )
        await server.serve_forever()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_async_run())
    except Exception:
        log.error("Le serveur Modbus TCP (esclave RPi) s'est arrêté :")
        traceback.print_exc()
