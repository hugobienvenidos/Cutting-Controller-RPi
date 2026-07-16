"""
cip_zones.py — Cycle périodique ON/OFF pour une zone CIP.

Chaque zone (Cutting, Hybrid Left, Hybrid Right) a son propre minuteur :
tant qu'elle est activée (coil ENABLE) et qu'il n'y a pas de trip, la sortie
alterne ON pendant on_time_ms puis OFF pendant off_time_ms, en boucle.
"""

import time


class CipZoneTimer:
    """
    État interne d'un cycle CIP. Un objet par zone, réutilisé à chaque appel
    de update() (ne pas recréer à chaque itération, sinon le cycle repart à zéro).
    """

    def __init__(self):
        self._phase_on = False
        self._last_switch = time.monotonic()

    def update(self, enabled: bool, on_time_ms: int, off_time_ms: int, force_off: bool = False):
        """
        Retourne (sortie: bool, state_code: int).
        state_code : 0 = idle (désactivé ou coupé par sécurité), 1 = on, 2 = off (dans le cycle).
        """
        now = time.monotonic()

        if force_off or not enabled:
            self._phase_on = False
            self._last_switch = now
            return False, 0

        duration_ms = on_time_ms if self._phase_on else off_time_ms
        if duration_ms <= 0:
            duration_ms = 1  # évite un cycle bloqué si une durée est réglée à 0

        elapsed_ms = (now - self._last_switch) * 1000
        if elapsed_ms >= duration_ms:
            self._phase_on = not self._phase_on
            self._last_switch = now

        state_code = 1 if self._phase_on else 2
        return self._phase_on, state_code
