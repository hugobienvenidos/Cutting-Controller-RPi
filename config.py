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
MODBUS_TIMEOUT = 1.0

# --- Adresses esclaves Modbus ---
# NOTE : le Cutting Controller (ESP32) est déployé par défaut en MB_SLAVE_ID=1 /
# 19200 8E1 dans son config.h -> il faudra changer ces deux constantes côté
# firmware (MB_SLAVE_ID -> 30, MB_BAUD -> 9600, MB_CONFIG -> SERIAL_8N1) pour
# matcher le bus existant, puisque vfd1 occupe déjà l'adresse 1.
MODBUS_DEVICES = {
    "vfd1": 1,           # Belt pocket
    "vfd2": 2,           # Belt infeed
    "cutting_controller": 30,  # ESP32-S3 Fish Cutting/Gutting Controller
    "gutting_left": 10,   # Gutting Machine gauche : DOL ON/OFF, CIP Timer, belly %
    "gutting_right": 11,  # Gutting Machine droite : idem
    "vision_left": 12,    # Vision System gauche : fish counter, good/bad
    "vision_right": 13,   # Vision System droite : idem
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
# "on_status_address" = adresse Modicon telle que documentée sur la Gutting Machine.
CIP_MIRROR = {
    "gutting_left": {
        "on_status_address": 40010,
        "register_type": "holding",       # holding | input | coil | discrete
        "cip_output": "cip_hybrid_left",
    },
    "gutting_right": {
        "on_status_address": 40011,        # à corriger avec la vraie adresse
        "register_type": "holding",
        "cip_output": "cip_hybrid_right",
    },
}

# --- Cutting/Gutting Controller (ESP32-S3, monitoring télémétrie uniquement) ---
# CIP volontairement absent : c'est la RPI qui pilote le CIP cutting (cip_cutting),
# pas ce contrôleur -> on ignore IR_CIP_STATE / HR_CIP_ON / HR_CIP_OFF / CO_CIP_ENABLE.
CUTTING_CONTROLLER_REGISTERS = {
    "input_start": 0,
    "input_count": 19,  # IR_COUNT du firmware (0..18)
    # offsets dans le bloc lu (correspondent à l'enum IR_* du firmware) :
    "rpm_blade_offset": 0,
    "rpm_wheel1_offset": 1,
    "rpm_wheel2_offset": 2,
    "inputs_mask_offset": 3,
    "outputs_mask_offset": 4,
    "ejector_state_offset": 5,     # 0 idle, 1 wait, 2 fire
    "ejector_count_lo_offset": 6,
    "ejector_count_hi_offset": 7,
    # offset 8 = IR_CIP_STATE -> ignoré volontairement
    "motor_trip_offset": 9,
    "motor_on_offset": 10,
    "belt_offset": 11,
    "belly_offset": 12,
    "alarm_mask_offset": 13,
    "alarm_unack_offset": 14,
    "sys_state_offset": 15,
    "uptime_lo_offset": 16,
    "uptime_hi_offset": 17,
    "fw_version_offset": 18,
}


# --- Registres Gutting Machine (belly %) et Vision System (compteurs) ---
# Offsets à vérifier avec la doc réelle de chaque machine (valeurs de départ ici).
GUTTING_REGISTERS = {
    "input_start": 2,           # premier input register à lire (belly %)
    "input_count": 1,
    "belly_pct_offset": 0,
    "belly_pct_scale": 100,
}

VISION_REGISTERS = {
    "input_start": 0,           # premier input register à lire (compteurs)
    "input_count": 3,
    "fish_counter_offset": 0,
    "good_offset": 1,
    "bad_offset": 2,
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
