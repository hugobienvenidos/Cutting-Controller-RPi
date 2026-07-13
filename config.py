"""
Configuration centrale du contrôleur Fish3 (Raspberry Pi).

Tout ce qui dépend du câblage physique ou de l'adressage Modbus
doit être modifié ICI uniquement, jamais dans les autres fichiers.
"""

# --- Bus RS485 (Modbus RTU maître) ---
SERIAL_PORT = "/dev/ttyUSB0"   # adaptateur USB-RS485
BAUDRATE = 9600
PARITY = "N"
STOPBITS = 1
BYTESIZE = 8
MODBUS_TIMEOUT = 1.0            # secondes

# --- Adresses esclaves Modbus ---
MODBUS_DEVICES = {
    "vfd1": 1,           # Belt pocket
    "vfd2": 2,           # Belt infeed
    "hybrid_left": 10,   # ESP32 - DOL/CIP Timer/compteurs/belly Left
    "hybrid_right": 11,  # ESP32 - idem côté droit
    "elec_meter": 20,
    "water_meter": 21,
}

# --- CP-IO22 : mapping GPIO (à corriger avec le manuel officiel) ---
GPIO_IN = {
    "presence_1": 4,
    "presence_2": 5,
    "presence_3": 6,
    "presence_4": 7,
    "dol_trip": 8,
    "dol_cutting_onoff": 9,
}

GPIO_OUT = {
    "cip_cutting": 17,
    "cip_hybrid_left": 27,
    "cip_hybrid_right": 22,
}

# --- Conversion adresses Modicon (4xxxx/3xxxx/1xxxx/0xxxx) -> offset 0-based pymodbus ---
def modicon_offset(address: int) -> int:
    """
    Convertit une adresse Modicon (ex: 40010) en offset 0-based pour pymodbus.
    4xxxx = holding register, 3xxxx = input register,
    1xxxx = discrete input, 0xxxx/1-9999 = coil.
    """
    if address >= 40001:
        return address - 40001
    if address >= 30001:
        return address - 30001
    if address >= 10001:
        return address - 10001
    return address - 1


# --- Miroir direct état machine -> sortie CIP ---
# "on_status_address" = adresse Modicon telle que documentée sur la machine.
CIP_MIRROR = {
    "hybrid_left": {
        "on_status_address": 40010,
        "register_type": "holding",       # holding | input | coil | discrete
        "cip_output": "cip_hybrid_left",
    },
    "hybrid_right": {
        "on_status_address": 40011,        # à corriger avec la vraie adresse
        "register_type": "holding",
        "cip_output": "cip_hybrid_right",
    },
}

# --- Registres de diagnostic (fish counter, good/bad, belly %) ---
HYBRID_REGISTERS = {
    "input_start": 2,           # premier input register à lire
    "input_count": 4,
    "fish_counter_offset": 0,
    "good_offset": 1,
    "bad_offset": 2,
    "belly_pct_offset": 3,
    "belly_pct_scale": 100,
}

VFD_REGISTERS = {
    "holding_start": 0,   # premier holding register à lire
    "holding_count": 2,
    "speed_offset": 0,
    "onoff_offset": 1,
}


GPIO_POLL_INTERVAL = 0.05
MODBUS_POLL_INTERVAL = 0.5
LOGIC_INTERVAL = 0.1

# --- Seuils métier ---
BELLY_ORIENTATION_THRESHOLD_PCT = 80