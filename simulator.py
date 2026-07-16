"""
simulator.py — Simulateur Modbus RTU pour tester le contrôleur Fish3 sans matériel réel.

Simule TOUS les esclaves définis dans config.MODBUS_DEVICES (VFD1/2,
Gutting Left/Right, Vision Left/Right) sur un seul bus RS485 virtuel,
avec une interface graphique pour piloter/afficher chaque registre.

Adresses conformes à Modbus_Addresses_Cutting_Gutting_RPI.xlsx.

Un port série ne peut être ouvert que par un seul programme à la fois.
Pour tester en même temps que main.py, utilise un port série virtuel :

    sudo apt install socat
    socat -d -d pty,raw,echo=0 pty,raw,echo=0

Ça affiche 2 chemins, ex: /dev/pts/3 et /dev/pts/4.
- Mets /dev/pts/3 comme port dans CE simulateur (champ en haut de la fenêtre)
- Mets /dev/pts/4 comme SERIAL_PORT dans config.py pour main.py

Nécessite : pip install pymodbus (déjà dans requirements.txt)
"""

import asyncio
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from pymodbus.datastore import ModbusSequentialDataBlock, ModbusServerContext
from pymodbus.server import ModbusSerialServer

# Compatibilité : pymodbus a renommé ModbusSlaveContext -> ModbusDeviceContext
# selon les versions. On essaie les deux pour que ce fichier marche sans
# devoir figer une version précise de pymodbus.
try:
    from pymodbus.datastore import ModbusDeviceContext as _DeviceContext
except ImportError:
    from pymodbus.datastore import ModbusSlaveContext as _DeviceContext

from config import (
    MODBUS_DEVICES, VFD_REGISTERS, GUTTING_REGISTERS, VISION_REGISTERS,
    SERIAL_PORT, BAUDRATE, PARITY, STOPBITS, BYTESIZE,
)

BLOCK_SIZE = 100  # taille généreuse de chaque bloc de registres, par simplicité

# Codes internes pymodbus pour setValues/getValues (identiques aux function codes Modbus)
FX_COIL = 1
FX_DISCRETE = 2
FX_HOLDING = 3
FX_INPUT = 4


def _make_slave_context() -> "_DeviceContext":
    """Bloc de registres vide (tout à 0) pour un esclave simulé."""
    return _DeviceContext(
        di=ModbusSequentialDataBlock(0, [0] * BLOCK_SIZE),
        co=ModbusSequentialDataBlock(0, [0] * BLOCK_SIZE),
        hr=ModbusSequentialDataBlock(0, [0] * BLOCK_SIZE),
        ir=ModbusSequentialDataBlock(0, [0] * BLOCK_SIZE),
    )


class ModbusSimulator:
    """Gère le serveur Modbus RTU (dans un thread dédié) et les contextes esclaves."""

    def __init__(self):
        self.slaves = {addr: _make_slave_context() for addr in MODBUS_DEVICES.values()}
        # Compatibilité : le paramètre s'appelle "slaves" dans les anciennes
        # versions de pymodbus, "devices" dans les plus récentes.
        try:
            self.context = ModbusServerContext(devices=self.slaves, single=False)
        except TypeError:
            self.context = ModbusServerContext(slaves=self.slaves, single=False)
        self._thread = None

    def start(self, port, baudrate, parity, stopbits, bytesize):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run, args=(port, baudrate, parity, stopbits, bytesize), daemon=True
        )
        self._thread.start()

    async def _async_run(self, port, baudrate, parity, stopbits, bytesize):
        server = ModbusSerialServer(
            context=self.context, port=port, baudrate=baudrate,
            parity=parity, stopbits=stopbits, bytesize=bytesize,
        )
        print(f"[simulator] serveur RTU créé sur {port} @ {baudrate} {parity}{bytesize}{stopbits}")
        await server.serve_forever()

    def _run(self, port, baudrate, parity, stopbits, bytesize):
        import traceback
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                self._async_run(port, baudrate, parity, stopbits, bytesize)
            )
        except Exception:
            print("[simulator] ERREUR — le serveur s'est arrêté :")
            traceback.print_exc()

    # --- Accès direct au datastore (utilisés par les widgets de l'interface) ---
    def set_holding(self, slave_addr, offset, value):
        self.slaves[slave_addr].setValues(FX_HOLDING, offset, [int(value)])

    def get_holding(self, slave_addr, offset):
        return self.slaves[slave_addr].getValues(FX_HOLDING, offset, count=1)[0]

    def set_input(self, slave_addr, offset, value):
        self.slaves[slave_addr].setValues(FX_INPUT, offset, [int(value)])

    def get_input(self, slave_addr, offset):
        return self.slaves[slave_addr].getValues(FX_INPUT, offset, count=1)[0]


def build_gui():
    root = tk.Tk()
    root.title("Simulateur Modbus RTU — Fish3")

    sim = ModbusSimulator()
    refreshers = []  # callables appelés périodiquement pour rafraîchir l'affichage

    # --- Barre de connexion ---
    top = ttk.Frame(root, padding=8)
    top.pack(fill="x")

    ttk.Label(top, text="Port série :").grid(row=0, column=0, sticky="w")
    port_var = tk.StringVar(value=SERIAL_PORT)
    ttk.Entry(top, textvariable=port_var, width=15).grid(row=0, column=1, padx=4)

    ttk.Label(top, text="Baud :").grid(row=0, column=2, sticky="w")
    baud_var = tk.StringVar(value=str(BAUDRATE))
    ttk.Entry(top, textvariable=baud_var, width=8).grid(row=0, column=3, padx=4)

    ttk.Label(top, text="Parité :").grid(row=0, column=4, sticky="w")
    parity_var = tk.StringVar(value=PARITY)
    ttk.Entry(top, textvariable=parity_var, width=3).grid(row=0, column=5, padx=4)

    status_var = tk.StringVar(value="Arrêté")
    status_label = ttk.Label(top, textvariable=status_var, foreground="red")

    def on_start():
        try:
            sim.start(port_var.get(), int(baud_var.get()), parity_var.get(), STOPBITS, BYTESIZE)
            status_var.set("En cours sur " + port_var.get())
            status_label.configure(foreground="green")
        except Exception as exc:
            messagebox.showerror("Erreur de démarrage", str(exc))

    ttk.Button(top, text="Démarrer serveur", command=on_start).grid(row=0, column=6, padx=8)
    status_label.grid(row=0, column=7, padx=12)

    # --- Onglets par appareil ---
    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=8, pady=8)

    def add_int_field(parent, row, label, get_fn, set_fn, minv=0, maxv=65535):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=4, pady=3)
        var = tk.IntVar(value=get_fn())
        spin = ttk.Spinbox(parent, from_=minv, to=maxv, textvariable=var, width=10)
        spin.grid(row=row, column=1, padx=4)
        ttk.Button(parent, text="Appliquer", command=lambda: set_fn(var.get())).grid(row=row, column=2, padx=4)

        def refresh():
            if root.focus_get() is not spin:  # ne pas écraser une saisie en cours
                var.set(get_fn())
        refreshers.append(refresh)

    def add_bool_field(parent, row, label, get_fn, set_fn):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=4, pady=3)
        var = tk.BooleanVar(value=bool(get_fn()))
        ttk.Checkbutton(parent, variable=var, command=lambda: set_fn(var.get())).grid(
            row=row, column=1, sticky="w", padx=4
        )

        def refresh():
            var.set(bool(get_fn()))
        refreshers.append(refresh)

    # --- VFD1 / VFD2 ---
    for vfd_name in ("vfd1", "vfd2"):
        addr = MODBUS_DEVICES[vfd_name]
        tab = ttk.Frame(notebook, padding=10)
        notebook.add(tab, text=vfd_name.upper())
        r = VFD_REGISTERS
        add_int_field(
            tab, 0, "Vitesse (RPM)",
            lambda a=addr, o=r["speed_offset"]: sim.get_holding(a, o),
            lambda v, a=addr, o=r["speed_offset"]: sim.set_holding(a, o, v),
            minv=0, maxv=3000,
        )
        add_bool_field(
            tab, 1, "ON/OFF",
            lambda a=addr, o=r["onoff_offset"]: sim.get_holding(a, o),
            lambda v, a=addr, o=r["onoff_offset"]: sim.set_holding(a, o, v),
        )

    # --- Gutting Left / Right (bloc complet : RPM, éjecteur, trip, alarmes...) ---
    for name in ("gutting_left", "gutting_right"):
        addr = MODBUS_DEVICES[name]
        tab = ttk.Frame(notebook, padding=10)
        notebook.add(tab, text=name.replace("_", " ").title())
        r = GUTTING_REGISTERS

        int_fields = [
            ("RPM Blade", "rpm_blade_offset", 0, 5000),
            ("RPM Wheel 1", "rpm_wheel1_offset", 0, 5000),
            ("RPM Wheel 2", "rpm_wheel2_offset", 0, 5000),
            ("Ejector state (0=idle,1=wait,2=fire)", "ejector_state_offset", 0, 2),
            ("CIP State (télémétrie)", "cip_state_offset", 0, 2),
            ("Alarm mask", "alarm_mask_offset", 0, 255),
        ]
        bool_fields = [
            ("Motor Trip", "motor_trip_offset"),
            ("Motor ON (= miroir CIP)", "motor_on_offset"),
            ("Belt running", "belt_offset"),
            ("Belly (instantané)", "belly_offset"),
        ]

        row = 0
        for label, offkey, minv, maxv in int_fields:
            off = r[offkey]
            add_int_field(
                tab, row, label,
                lambda a=addr, o=off: sim.get_input(a, o),
                lambda v, a=addr, o=off: sim.set_input(a, o, v),
                minv=minv, maxv=maxv,
            )
            row += 1
        for label, offkey in bool_fields:
            off = r[offkey]
            add_bool_field(
                tab, row, label,
                lambda a=addr, o=off: sim.get_input(a, o),
                lambda v, a=addr, o=off: sim.set_input(a, o, v),
            )
            row += 1

    # --- Vision Left / Right ---
    for name in ("vision_left", "vision_right"):
        addr = MODBUS_DEVICES[name]
        tab = ttk.Frame(notebook, padding=10)
        notebook.add(tab, text=name.replace("_", " ").title())
        r = VISION_REGISTERS
        add_int_field(
            tab, 0, "Fish counter",
            lambda a=addr, o=r["fish_counter_offset"]: sim.get_input(a, o),
            lambda v, a=addr, o=r["fish_counter_offset"]: sim.set_input(a, o, v),
            minv=0, maxv=999999,
        )
        add_int_field(
            tab, 1, "Gutting Good/Bad",
            lambda a=addr, o=r["good_bad_offset"]: sim.get_input(a, o),
            lambda v, a=addr, o=r["good_bad_offset"]: sim.set_input(a, o, v),
            minv=0, maxv=65535,
        )
        add_int_field(
            tab, 2, "Ejected Fish",
            lambda a=addr, o=r["ejected_fish_offset"]: sim.get_input(a, o),
            lambda v, a=addr, o=r["ejected_fish_offset"]: sim.set_input(a, o, v),
            minv=0, maxv=999999,
        )

    # --- Rafraîchissement périodique de l'affichage (montre les écritures du maître) ---
    def periodic_refresh():
        for refresh in refreshers:
            try:
                refresh()
            except Exception:
                pass
        root.after(1000, periodic_refresh)

    root.after(1000, periodic_refresh)
    root.mainloop()


if __name__ == "__main__":
    build_gui()
