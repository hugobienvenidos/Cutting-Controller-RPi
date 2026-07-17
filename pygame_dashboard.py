"""
pygame_dashboard.py — Dashboard de monitoring temps réel (Pygame).

Remplace l'ancien dashboard Tkinter. Doit tourner sur le thread PRINCIPAL
(comme Tkinter, Pygame veut son event loop sur le thread principal pour
capter proprement les événements fenêtre/clavier). Voir comment main.py
l'appelle.

Affiche : fish count total, fish/min (calculé en interne à partir des deltas
de compteur), people presence, poissons éjectés (mauvais), good/bad brut,
courbe du fish/min sur les 5 dernières minutes, statut connexion par
appareil, alarme trip, état des 3 zones CIP, vitesse VFD1/2, RPM lame
Gutting Left/Right.

Nécessite : pip install pygame (voir requirements.txt)
"""

import threading
import time
from collections import deque

import pygame

from shared_state import SharedState

WIDTH, HEIGHT = 1100, 700
FPS = 20

HISTORY_WINDOW_S = 5 * 60      # fenêtre affichée sur le graphe (5 min)
HISTORY_SAMPLE_S = 2           # un échantillon toutes les 2s

# --- Palette ---
BG = (18, 20, 24)
PANEL = (30, 33, 40)
PANEL_BORDER = (50, 54, 62)
TEXT = (230, 230, 230)
MUTED = (140, 145, 150)
GREEN = (46, 204, 113)
RED = (231, 76, 60)
GREY = (90, 95, 100)
BLUE = (52, 152, 219)
ORANGE = (230, 126, 34)

MODBUS_DEVICE_ORDER = ["vfd1", "vfd2", "gutting_left", "gutting_right", "vision_left", "vision_right"]
CIP_ZONES = [
    ("cip_cutting_state", "CIP Cutting"),
    ("cip_hybrid_left_state", "CIP Hybrid Left"),
    ("cip_hybrid_right_state", "CIP Hybrid Right"),
]


def run_pygame_dashboard(state: SharedState, stop_event: threading.Event):
    pygame.init()
    pygame.display.set_caption("Fish3 — Monitoring")
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    clock = pygame.time.Clock()

    font_huge = pygame.font.SysFont("Arial", 46, bold=True)
    font_big = pygame.font.SysFont("Arial", 26, bold=True)
    font_med = pygame.font.SysFont("Arial", 18, bold=True)
    font_small = pygame.font.SysFont("Arial", 14)

    fonts = {"huge": font_huge, "big": font_big, "med": font_med, "small": font_small}

    history = deque(maxlen=int(HISTORY_WINDOW_S / HISTORY_SAMPLE_S))
    last_sample_time = 0.0
    last_total_count = None
    last_count_time = None

    running = True
    while running and not stop_event.is_set():
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False

        snap = state.snapshot()
        modbus = snap["modbus"]
        modbus_errors = snap["modbus_errors"]
        gpio_in = snap["gpio_in"]
        rpi_input = snap["rpi_input"]

        vision_left = modbus.get("vision_left", {})
        vision_right = modbus.get("vision_right", {})
        total_fish = (vision_left.get("fish_counter") or 0) + (vision_right.get("fish_counter") or 0)
        total_ejected = (vision_left.get("ejected_fish") or 0) + (vision_right.get("ejected_fish") or 0)

        now = time.monotonic()
        if now - last_sample_time >= HISTORY_SAMPLE_S:
            last_sample_time = now
            if last_total_count is not None and last_count_time is not None:
                delta_count = total_fish - last_total_count
                delta_min = (now - last_count_time) / 60.0
                rate = delta_count / delta_min if delta_min > 0 else 0.0
                history.append(max(rate, 0.0))
            last_total_count = total_fish
            last_count_time = now

        current_rate = history[-1] if history else 0.0
        trip_active = bool(gpio_in.get("dol_trip"))

        screen.fill(BG)
        _draw_header(screen, fonts, modbus, modbus_errors)
        _draw_alarm_banner(screen, fonts, trip_active)
        _draw_big_metrics(screen, fonts, total_fish, current_rate, total_ejected, vision_left, vision_right)
        _draw_presence(screen, fonts, gpio_in)
        _draw_cip_zones(screen, fonts, rpi_input)
        _draw_machinery(screen, fonts, modbus)
        _draw_graph(screen, fonts, history)

        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()
    stop_event.set()


# ----------------------------------------------------------------------
# Helpers de dessin
# ----------------------------------------------------------------------

def _panel(screen, rect, title, font):
    pygame.draw.rect(screen, PANEL, rect, border_radius=8)
    pygame.draw.rect(screen, PANEL_BORDER, rect, width=1, border_radius=8)
    if title:
        label = font.render(title, True, MUTED)
        screen.blit(label, (rect[0] + 12, rect[1] + 8))


def _draw_header(screen, fonts, modbus, modbus_errors):
    title = fonts["big"].render("FISH3 — Monitoring", True, TEXT)
    screen.blit(title, (20, 14))

    x = WIDTH - 20
    for name in reversed(MODBUS_DEVICE_ORDER):
        ok = (name in modbus) and (modbus_errors.get(name) is None)
        color = GREEN if ok else RED
        radius = 7
        x -= 16
        pygame.draw.circle(screen, color, (x, 26), radius)
        label = fonts["small"].render(name, True, MUTED)
        x -= label.get_width() + 8
        screen.blit(label, (x, 18))
        x -= 14


def _draw_alarm_banner(screen, fonts, trip_active):
    rect = (20, 54, WIDTH - 40, 34)
    color = RED if trip_active else GREEN
    text = "DOL TRIP ACTIF — CIP ET VFD COUPÉS" if trip_active else "SYSTÈME OK — AUCUN TRIP"
    pygame.draw.rect(screen, color, rect, border_radius=6)
    label = fonts["med"].render(text, True, (20, 20, 20) if not trip_active else (255, 255, 255))
    screen.blit(label, (rect[0] + 12, rect[1] + 6))


def _draw_big_metrics(screen, fonts, total_fish, current_rate, total_ejected, vision_left, vision_right):
    y = 100
    h = 130
    cards = [
        ("Fish Count (total)", f"{total_fish}", TEXT),
        ("Fish / min", f"{current_rate:.1f}", BLUE),
        ("Poissons éjectés (bad)", f"{total_ejected}", ORANGE),
        ("Good/Bad (brut L/R)", f"{vision_left.get('good_bad', '—')} / {vision_right.get('good_bad', '—')}", MUTED),
    ]
    card_w = (WIDTH - 40 - 3 * 16) // 4
    x = 20
    for title, value, color in cards:
        rect = (x, y, card_w, h)
        _panel(screen, rect, title, fonts["small"])
        val_label = fonts["huge"].render(value, True, color)
        screen.blit(val_label, (x + 16, y + 40))
        x += card_w + 16


def _draw_presence(screen, fonts, gpio_in):
    rect = (20, 250, 260, 130)
    _panel(screen, rect, "People Presence", fonts["small"])
    for i in range(4):
        active = bool(gpio_in.get(f"presence_{i + 1}"))
        cx = rect[0] + 40 + i * 55
        cy = rect[1] + 75
        pygame.draw.circle(screen, GREEN if active else GREY, (cx, cy), 20)
        label = fonts["small"].render(f"P{i + 1}", True, TEXT)
        screen.blit(label, (cx - label.get_width() // 2, cy + 26))


def _draw_cip_zones(screen, fonts, rpi_input):
    rect = (300, 250, 300, 130)
    _panel(screen, rect, "Zones CIP", fonts["small"])
    state_labels = {0: ("IDLE", GREY), 1: ("ON", GREEN), 2: ("OFF", MUTED)}
    y = rect[1] + 36
    for key, label_text in CIP_ZONES:
        code = rpi_input.get(key, 0)
        text, color = state_labels.get(code, ("—", GREY))
        name_label = fonts["small"].render(label_text, True, TEXT)
        screen.blit(name_label, (rect[0] + 14, y))
        badge_rect = (rect[0] + rect[2] - 70, y - 4, 56, 22)
        pygame.draw.rect(screen, color, badge_rect, border_radius=4)
        state_label = fonts["small"].render(text, True, (20, 20, 20))
        screen.blit(state_label, (badge_rect[0] + 8, badge_rect[1] + 3))
        y += 30


def _draw_machinery(screen, fonts, modbus):
    rect = (620, 250, WIDTH - 640, 130)
    _panel(screen, rect, "Machines", fonts["small"])
    vfd1 = modbus.get("vfd1", {})
    vfd2 = modbus.get("vfd2", {})
    gutting_left = modbus.get("gutting_left", {})
    gutting_right = modbus.get("gutting_right", {})

    lines = [
        f"VFD1 (Belt pocket)   : {vfd1.get('speed', '—')} RPM  [{'ON' if vfd1.get('onoff') else 'OFF'}]",
        f"VFD2 (Belt infeed)   : {vfd2.get('speed', '—')} RPM  [{'ON' if vfd2.get('onoff') else 'OFF'}]",
        f"Gutting Left  — RPM Blade : {gutting_left.get('rpm_blade', '—')}",
        f"Gutting Right — RPM Blade : {gutting_right.get('rpm_blade', '—')}",
    ]
    y = rect[1] + 36
    for line in lines:
        label = fonts["small"].render(line, True, TEXT)
        screen.blit(label, (rect[0] + 14, y))
        y += 22


def _draw_graph(screen, fonts, history):
    rect = (20, 400, WIDTH - 40, 280)
    _panel(screen, rect, "Fish / min — 5 dernières minutes", fonts["small"])

    plot_x, plot_y = rect[0] + 16, rect[1] + 40
    plot_w, plot_h = rect[2] - 32, rect[3] - 60

    pygame.draw.line(screen, PANEL_BORDER, (plot_x, plot_y), (plot_x, plot_y + plot_h), 1)
    pygame.draw.line(screen, PANEL_BORDER, (plot_x, plot_y + plot_h), (plot_x + plot_w, plot_y + plot_h), 1)

    if len(history) < 2:
        label = fonts["small"].render("Historique en cours de constitution...", True, MUTED)
        screen.blit(label, (plot_x + 10, plot_y + plot_h // 2))
        return

    max_val = max(max(history), 1)
    points = []
    n = len(history)
    for i, val in enumerate(history):
        px = plot_x + int(i / (n - 1) * plot_w)
        py = plot_y + plot_h - int((val / max_val) * plot_h)
        points.append((px, py))

    pygame.draw.lines(screen, BLUE, False, points, 2)

    max_label = fonts["small"].render(f"{max_val:.0f}", True, MUTED)
    screen.blit(max_label, (plot_x - 4, plot_y - 4))
    zero_label = fonts["small"].render("0", True, MUTED)
    screen.blit(zero_label, (plot_x - 4, plot_y + plot_h - 8))
