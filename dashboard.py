"""
dashboard.py — Interface de monitoring temps réel du contrôleur Fish3 (RPi).

Affiche l'état de tous les esclaves Modbus (VFD1/2, Gutting Left/Right, Vision
Left/Right) et des GPIO du CP-IO22 en lecture seule, avec rafraîchissement
automatique. Les paramètres CIP (activation par zone, durées ON/OFF) sont en
revanche éditables directement ici — ce sont des réglages purement locaux à
la RPi, pas exposés en Modbus.

IMPORTANT : doit tourner sur le thread PRINCIPAL (contrainte Tkinter) —
voir comment main.py l'appelle. Nécessite un environnement graphique sur
la RPi (bureau Raspberry Pi OS, ou `ssh -X` / VNC depuis un autre poste).
"""

import threading
import tkinter as tk
from tkinter import ttk

from shared_state import SharedState
from config import MODBUS_DEVICES, GPIO_IN, GPIO_OUT

REFRESH_MS = 500

OK_COLOR = "#2ecc71"
ALARM_COLOR = "#e74c3c"
NEUTRAL_COLOR = "#bdc3c7"


def build_dashboard(state: SharedState, stop_event: threading.Event):
    root = tk.Tk()
    root.title("Fish3 — Monitoring RPi")

    def on_close():
        stop_event.set()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)

    snap_holder = {"data": {"gpio_in": {}, "gpio_out": {}, "modbus": {}, "modbus_errors": {}}}
    refreshers = []

    # --- Barre supérieure ---
    top = ttk.Frame(root, padding=8)
    top.pack(fill="x")
    ttk.Label(top, text="Fish3 — Monitoring", font=("TkDefaultFont", 12, "bold")).pack(side="left")
    ttk.Button(top, text="Quitter", command=on_close).pack(side="right")

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=8, pady=8)

    # --- Helpers de construction des lignes ---
    def add_value_row(parent, row, label, get_fn, fmt="{}"):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=6, pady=3)
        var = tk.StringVar(value="—")
        ttk.Label(parent, textvariable=var, font=("TkDefaultFont", 10, "bold")).grid(
            row=row, column=1, sticky="w", padx=6
        )

        def refresh():
            try:
                val = get_fn(snap_holder["data"])
                var.set(fmt.format(val) if val is not None else "—")
            except Exception:
                var.set("—")

        refreshers.append(refresh)

    def add_bool_row(parent, row, label, get_fn, true_text="ON", false_text="OFF", alarm_style=False):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=6, pady=3)
        lbl = ttk.Label(parent, text="—", width=10, anchor="center")
        lbl.grid(row=row, column=1, sticky="w", padx=6)

        def refresh():
            try:
                val = get_fn(snap_holder["data"])
            except Exception:
                val = None
            if val is None:
                lbl.configure(text="—", background=root.cget("bg"))
            elif val:
                color = ALARM_COLOR if alarm_style else OK_COLOR
                lbl.configure(text=true_text, background=color, foreground="white")
            else:
                lbl.configure(text=false_text, background=NEUTRAL_COLOR, foreground="black")

        refreshers.append(refresh)

    def add_editable_bool_row(parent, row, label, get_fn, set_fn):
        """Checkbox éditable : change immédiatement la valeur au clic."""
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=6, pady=3)
        var = tk.BooleanVar(value=bool(get_fn(snap_holder["data"])))
        chk = ttk.Checkbutton(parent, variable=var, command=lambda: set_fn(var.get()))
        chk.grid(row=row, column=1, sticky="w", padx=6)

        def refresh():
            # Ne pas écraser la case pendant que l'utilisateur interagit avec elle
            if root.focus_get() is not chk:
                try:
                    var.set(bool(get_fn(snap_holder["data"])))
                except Exception:
                    pass

        refreshers.append(refresh)

    def add_editable_int_row(parent, row, label, get_fn, set_fn, minv=0, maxv=600000):
        """Spinbox + bouton Appliquer : la valeur ne change qu'au clic (évite les à-coups)."""
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=6, pady=3)
        var = tk.IntVar(value=get_fn(snap_holder["data"]) or 0)
        spin = ttk.Spinbox(parent, from_=minv, to=maxv, textvariable=var, width=10)
        spin.grid(row=row, column=1, padx=6)
        ttk.Button(parent, text="Appliquer", command=lambda: set_fn(var.get())).grid(row=row, column=2, padx=4)

        def refresh():
            if root.focus_get() is not spin:
                try:
                    var.set(get_fn(snap_holder["data"]) or 0)
                except Exception:
                    pass

        refreshers.append(refresh)
    tab = ttk.Frame(notebook, padding=10)
    notebook.add(tab, text="Vue d'ensemble")

    row = 0
    ttk.Label(tab, text="Communication Modbus", font=("TkDefaultFont", 10, "underline")).grid(
        row=row, column=0, columnspan=2, sticky="w", pady=(0, 6)
    )
    row += 1
    for dev_name in MODBUS_DEVICES:
        add_bool_row(
            tab, row, dev_name,
            lambda s, d=dev_name: (d in s["modbus"]) and (s["modbus_errors"].get(d) is None),
            true_text="OK", false_text="ERREUR", alarm_style=False,
        )
        row += 1

    row += 1
    ttk.Label(tab, text="Sécurité", font=("TkDefaultFont", 10, "underline")).grid(
        row=row, column=0, columnspan=2, sticky="w", pady=(6, 6)
    )
    row += 1
    add_bool_row(tab, row, "DOL Trip (GPIO)", lambda s: s["gpio_in"].get("dol_trip"),
                 true_text="TRIP", false_text="OK", alarm_style=True)
    row += 1
    for dev_name in ("gutting_left", "gutting_right"):
        add_bool_row(
            tab, row, f"{dev_name} — Motor Trip",
            lambda s, d=dev_name: s["modbus"].get(d, {}).get("motor_trip"),
            true_text="TRIP", false_text="OK", alarm_style=True,
        )
        row += 1
        add_bool_row(
            tab, row, f"{dev_name} — Alarme non acquittée",
            lambda s, d=dev_name: bool(s["modbus"].get(d, {}).get("alarm_unack", 0)),
            true_text="ALARME", false_text="OK", alarm_style=True,
        )
        row += 1

    # --- Onglet GPIO ---
    tab = ttk.Frame(notebook, padding=10)
    notebook.add(tab, text="GPIO (CP-IO22)")
    row = 0
    ttk.Label(tab, text="Entrées", font=("TkDefaultFont", 10, "underline")).grid(
        row=row, column=0, columnspan=2, sticky="w", pady=(0, 6)
    )
    row += 1
    for name in GPIO_IN:
        add_bool_row(tab, row, name, lambda s, n=name: s["gpio_in"].get(n))
        row += 1
    row += 1
    ttk.Label(tab, text="Sorties", font=("TkDefaultFont", 10, "underline")).grid(
        row=row, column=0, columnspan=2, sticky="w", pady=(6, 6)
    )
    row += 1
    for name in GPIO_OUT:
        add_bool_row(tab, row, name, lambda s, n=name: s["gpio_out"].get(n))
        row += 1

    # --- Onglet "Paramètres CIP" (local, pas de Modbus slave) ---
    tab = ttk.Frame(notebook, padding=10)
    notebook.add(tab, text="Paramètres CIP")
    row = 0
    ttk.Label(tab, text="Activation par zone", font=("TkDefaultFont", 10, "underline")).grid(
        row=row, column=0, columnspan=2, sticky="w", pady=(0, 6)
    )
    row += 1
    for coil_name, coil_label in (
        ("cip_cutting_enable", "CIP Cutting"),
        ("cip_hybrid_left_enable", "CIP Hybrid Left"),
        ("cip_hybrid_right_enable", "CIP Hybrid Right"),
    ):
        add_editable_bool_row(
            tab, row, coil_label,
            lambda s, n=coil_name: s["rpi_coils"].get(n),
            lambda v, n=coil_name: state.set_rpi_coil(n, v),
        )
        row += 1

    row += 1
    ttk.Label(tab, text="Durées de cycle CIP (ms)", font=("TkDefaultFont", 10, "underline")).grid(
        row=row, column=0, columnspan=2, sticky="w", pady=(6, 6)
    )
    row += 1
    for hr_name, hr_label in (
        ("cutting_on_time", "CIP Cutting ON_TIME"), ("cutting_off_time", "CIP Cutting OFF_TIME"),
        ("hybrid_left_on_time", "CIP Hybrid Left ON_TIME"), ("hybrid_left_off_time", "CIP Hybrid Left OFF_TIME"),
        ("hybrid_right_on_time", "CIP Hybrid Right ON_TIME"), ("hybrid_right_off_time", "CIP Hybrid Right OFF_TIME"),
    ):
        add_editable_int_row(
            tab, row, hr_label,
            lambda s, n=hr_name: s["rpi_holding"].get(n),
            lambda v, n=hr_name: state.set_rpi_holding(n, v),
            minv=0, maxv=600000,
        )
        row += 1

    row += 1
    ttk.Label(tab, text="Télémétrie", font=("TkDefaultFont", 10, "underline")).grid(
        row=row, column=0, columnspan=2, sticky="w", pady=(6, 6)
    )
    row += 1
    add_value_row(tab, row, "Presence mask", lambda s: s["rpi_input"].get("presence_mask"), fmt="0b{:04b}")
    row += 1
    add_bool_row(tab, row, "DOL Blades Trip", lambda s: bool(s["rpi_input"].get("dol_blades_trip")),
                 true_text="TRIP", false_text="OK", alarm_style=True)
    row += 1
    add_bool_row(tab, row, "DOL Blades State", lambda s: bool(s["rpi_input"].get("dol_blades_state")))
    row += 1
    for state_name, label in (
        ("cip_cutting_state", "CIP Cutting State"),
        ("cip_hybrid_left_state", "CIP Hybrid Left State"),
        ("cip_hybrid_right_state", "CIP Hybrid Right State"),
    ):
        add_value_row(
            tab, row, label,
            lambda s, n=state_name: {0: "idle", 1: "on", 2: "off"}.get(s["rpi_input"].get(n), "—"),
        )
        row += 1

    # --- Onglets VFD1 / VFD2 ---
    for vfd_name in ("vfd1", "vfd2"):
        tab = ttk.Frame(notebook, padding=10)
        notebook.add(tab, text=vfd_name.upper())
        add_value_row(tab, 0, "Vitesse (RPM)", lambda s, d=vfd_name: s["modbus"].get(d, {}).get("speed"))
        add_bool_row(tab, 1, "ON/OFF", lambda s, d=vfd_name: s["modbus"].get(d, {}).get("onoff"))

    # --- Onglets Gutting Left / Right ---
    for dev_name in ("gutting_left", "gutting_right"):
        tab = ttk.Frame(notebook, padding=10)
        notebook.add(tab, text=dev_name.replace("_", " ").title())

        def g(s, d=dev_name, key=None):
            return s["modbus"].get(d, {}).get(key)

        row = 0
        add_value_row(tab, row, "RPM Blade", lambda s, d=dev_name: g(s, d, "rpm_blade")); row += 1
        add_value_row(tab, row, "RPM Wheel 1", lambda s, d=dev_name: g(s, d, "rpm_wheel1")); row += 1
        add_value_row(tab, row, "RPM Wheel 2", lambda s, d=dev_name: g(s, d, "rpm_wheel2")); row += 1
        add_value_row(
            tab, row, "État éjecteur",
            lambda s, d=dev_name: {0: "idle", 1: "wait", 2: "fire"}.get(g(s, d, "ejector_state"), "—"),
        ); row += 1
        add_value_row(tab, row, "Compteur éjections", lambda s, d=dev_name: g(s, d, "ejector_count")); row += 1
        add_value_row(
            tab, row, "CIP State (télémétrie)",
            lambda s, d=dev_name: {0: "idle", 1: "on", 2: "off"}.get(g(s, d, "cip_state"), "—"),
        ); row += 1
        add_bool_row(tab, row, "Motor Trip", lambda s, d=dev_name: g(s, d, "motor_trip"),
                     true_text="TRIP", false_text="OK", alarm_style=True); row += 1
        add_bool_row(tab, row, "Motor ON (= miroir CIP)", lambda s, d=dev_name: g(s, d, "onoff")); row += 1
        add_bool_row(tab, row, "Belt running", lambda s, d=dev_name: g(s, d, "belt")); row += 1
        add_bool_row(tab, row, "Belly (instantané)", lambda s, d=dev_name: g(s, d, "belly")); row += 1
        add_value_row(tab, row, "Alarm mask", lambda s, d=dev_name: g(s, d, "alarm_mask"), fmt="0x{:02X}"); row += 1
        add_bool_row(tab, row, "Alarme non acquittée", lambda s, d=dev_name: bool(g(s, d, "alarm_unack") or 0),
                     true_text="ALARME", false_text="OK", alarm_style=True); row += 1
        add_value_row(
            tab, row, "Uptime",
            lambda s, d=dev_name: g(s, d, "uptime_s"),
            fmt="{}",
        ); row += 1
        add_value_row(
            tab, row, "Version firmware",
            lambda s, d=dev_name: g(s, d, "fw_version"),
            fmt="0x{:04X}",
        ); row += 1

    # --- Onglets Vision Left / Right ---
    for dev_name in ("vision_left", "vision_right"):
        tab = ttk.Frame(notebook, padding=10)
        notebook.add(tab, text=dev_name.replace("_", " ").title())
        add_value_row(tab, 0, "Fish counter", lambda s, d=dev_name: s["modbus"].get(d, {}).get("fish_counter"))
        add_value_row(tab, 1, "Gutting Good/Bad", lambda s, d=dev_name: s["modbus"].get(d, {}).get("good_bad"))
        add_value_row(tab, 2, "Ejected Fish", lambda s, d=dev_name: s["modbus"].get(d, {}).get("ejected_fish"))

    # --- Rafraîchissement périodique ---
    def periodic_refresh():
        if stop_event.is_set():
            return
        snap_holder["data"] = state.snapshot()
        for refresh in refreshers:
            try:
                refresh()
            except Exception:
                pass
        root.after(REFRESH_MS, periodic_refresh)

    root.after(REFRESH_MS, periodic_refresh)
    root.mainloop()
