"""
Configuration centrale du contrôleur Fish3 (Raspberry Pi).

Tout ce qui dépend du câblage physique ou de l'adressage Modbus
doit être modifié ICI uniquement, jamais dans les autres fichiers.

Adresses conformes à Modbus_Addresses_Cutting_Gutting_RPI.xlsx.
"""

# --- Bus RS485 (Modbus RTU maître) ---
SERIAL_PORT = "/dev/ttyUSB0"   # adaptateur USB-RS485
BAUDRATE = 9600
PARITY = "N"
STOPBITS = 1
BYTESIZE = 8
MODBUS_TIMEOUT = 1.0

# --- Adresses esclaves Modbus (Slave ID, d'après Cutting-Gutting-Controllers-Registers-IO.xlsx) ---
MODBUS_DEVICES = {
    "vfd1": 1,             # Belt pocket
    "vfd2": 2,             # Belt infeed
    # 3 = la RPi elle-même -> les I/O CIP (adresse 3 sur le fichier Excel)
    # sont gérées en local (dashboard), pas exposées en Modbus ici
    "gutting_left": 4,     # Gutting Machine Left
    "vision_left": 5,      # Vision System Left
    "gutting_right": 6,    # Gutting Machine Right
    "vision_right": 7,     # Vision System Right
}
# NOTE : Electricity Meter / Water Meter ne sont pas dans ce fichier Excel ->
# retirés de MODBUS_DEVICES en attendant leurs vraies adresses.

# --- CP-IO22 : mapping GPIO (à corriger avec le manuel officiel) ---
# Inchangé : la machine "Cutting" (présence, DOL Trip, DOL Cutting ON/OFF,
# CIP Cutting) reste pilotée en direct par la RPi, indépendamment du Modbus.
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

# --- Conversion adresses "1xxxx/4xxxx/0xxxx" du fichier Excel -> offset 0-based ---
# NOTE : le fichier Excel utilise 1xxxx pour les INPUT REGISTERS (pas les
# discrete inputs du standard Modicon strict) -> convention interne au projet,
# pas le standard Modicon officiel. On la garde telle quelle par cohérence
# avec le document fourni.
def modicon_offset(address) -> int:
    """Convertit une adresse du fichier Excel (ex: 10011, 40001) en offset 0-based."""
    if isinstance(address, str):
        address = int(address)
    if address >= 40001:
        return address - 40001   # holding register
    if address >= 10001:
        return address - 10001   # input register (convention du fichier Excel)
    return address - 1           # coil


# --- Gutting Machine (Left=3, Right=5) — bloc complet, identique aux 2 machines ---
# Correspond exactement au firmware ESP32-S3 "Fish Cutting/Gutting Controller".
GUTTING_REGISTERS = {
    # Input registers (10001-10019 -> offsets 0-18)
    "input_start": 0,
    "input_count": 19,
    "rpm_blade_offset": 0,          # 10001
    "rpm_wheel1_offset": 1,         # 10002
    "rpm_wheel2_offset": 2,         # 10003
    "input_mask_offset": 3,         # 10004
    "output_mask_offset": 4,        # 10005
    "ejector_state_offset": 5,      # 10006 (0 idle, 1 wait, 2 fire)
    "ejector_count_lo_offset": 6,   # 10007
    "ejector_count_hi_offset": 7,   # 10008
    "cip_state_offset": 8,          # 10009 - télémétrie seule, pas utilisé pour piloter
    "motor_trip_offset": 9,         # 10010
    "motor_on_offset": 10,          # 10011 - télémétrie (ne pilote plus le CIP directement)
    "belt_offset": 11,              # 10012
    "belly_offset": 12,             # 10013
    "alarm_mask_offset": 13,        # 10014
    "alarm_unack_offset": 14,       # 10015
    "sys_state_offset": 15,         # 10016
    "uptime_lo_offset": 16,         # 10017
    "uptime_hi_offset": 17,         # 10018
    "fw_version_offset": 18,        # 10019

    # Holding registers (40001-40009 -> offsets 0-8)
    # NOTE : le fichier Excel affiche "40002" en double pour plusieurs lignes
    # (probablement une erreur de recopie) -> on suppose une suite logique
    # 40001..40009, cohérente avec l'ordre de l'enum HR_* du firmware.
    "hr_eject_delay_offset": 0,     # 40001
    "hr_eject_duration_offset": 1,  # 40002
    "hr_cip_on_offset": 2,          # 40003
    "hr_cip_off_offset": 3,         # 40004
    "hr_ppr_blade_offset": 4,       # 40005
    "hr_ppr_wheel1_offset": 5,      # 40006
    "hr_ppr_wheel2_offset": 6,      # 40007
    "hr_blade_rpm_min_offset": 7,   # 40008
    "hr_debounce_ms_offset": 8,     # 40009

    # Coils (00001-00003 -> offsets 0-2)
    "co_eject_enable_offset": 0,    # 00001
    "co_cip_enable_offset": 1,      # 00002 - non utilisé (RPi pilote le CIP directement)
    "co_alarm_ack_offset": 2,       # 00003
}

# --- Vision System (Left=4, Right=6) ---
VISION_REGISTERS = {
    "input_start": 0,
    "input_count": 3,
    "fish_counter_offset": 0,    # 10001
    "good_bad_offset": 1,        # 10002 - registre combiné (pas good/bad séparés)
    "ejected_fish_offset": 2,    # 10003
    "hr_ml_model_offset": 0,     # 40001 (holding register séparé, R/W)
}

# --- CIP ---
# L'ancien miroir direct "Motor ON -> CIP" est remplacé par un cycle périodique
# ON_TIME/OFF_TIME piloté par coils/holding gérés en local (voir CIP_ZONE_*
# et la logique ZONES dans logic.py). "Motor ON" (motor_on_offset ci-dessus)
# reste disponible en télémétrie mais ne pilote plus directement le CIP.

# --- VFD1 / VFD2 ---
# Le fichier Excel indique juste "Check VFD" pour l'adresse -> les vraies
# adresses de registre restent à récupérer dans la doc Modbus du variateur.
VFD_REGISTERS = {
    "holding_start": 0,
    "holding_count": 2,
    "speed_offset": 0,
    "onoff_offset": 1,
}

# --- Cadences de boucle (secondes) ---
GPIO_POLL_INTERVAL = 0.05
MODBUS_POLL_INTERVAL = 0.5
LOGIC_INTERVAL = 0.1

# --- MQTT ---
# À adapter à ton broker réel (adresse, port, identifiants, TLS).
MQTT_BROKER_HOST = "localhost"
MQTT_BROKER_PORT = 1883          # 8883 si MQTT_USE_TLS = True
MQTT_USE_TLS = False
MQTT_USERNAME = None             # ex: "fish3-rpi"
MQTT_PASSWORD = None
MQTT_CLIENT_ID = "fish3-rpi-controller"
MQTT_TOPIC_PREFIX = "fish3"
MQTT_PUBLISH_INTERVAL = 1.0      # secondes entre 2 publications d'état

# Champs "holding register" exposés en écriture par appareil (topics de commande)
MQTT_WRITABLE_FIELDS = {
    "vfd": ["speed", "onoff"],
    "gutting": [
        "eject_delay", "eject_duration", "cip_on", "cip_off",
        "ppr_blade", "ppr_wheel1", "ppr_wheel2", "blade_rpm_min", "debounce_ms",
    ],
    "vision": ["ml_model"],
}

# --- Paramètres locaux CIP (Cutting + Hybrid Left/Right) ---
# Ces paramètres sont uniquement internes à la RPi (pas de Modbus slave) :
# activation par zone (interface graphique) + durée de cycle ON/OFF (ms).
# Correspond aux champs de Cutting-Gutting-Controllers-Registers-IO.xlsx,
# mais gérés en local plutôt qu'exposés en Modbus (la RPi est déjà Master).
CIP_ZONE_ENABLE_KEYS = {
    "cutting": "cip_cutting_enable",
    "hybrid_left": "cip_hybrid_left_enable",
    "hybrid_right": "cip_hybrid_right_enable",
}

CIP_ZONE_DEFAULT_TIMES = {
    "cutting_on_time": 2000, "cutting_off_time": 8000,
    "hybrid_left_on_time": 2000, "hybrid_left_off_time": 8000,
    "hybrid_right_on_time": 2000, "hybrid_right_off_time": 8000,
}

# Mapping zone CIP -> topic MQTT / clés SharedState correspondantes.
# Topics distincts des devices Modbus (MODBUS_DEVICES) car ce sont des
# paramètres locaux (rpi_coils / rpi_holding / rpi_input), pas du Modbus.
CIP_ZONE_MQTT_MAP = {
    "cip_cutting": {
        "enable_key": "cip_cutting_enable",
        "on_time_key": "cutting_on_time",
        "off_time_key": "cutting_off_time",
        "state_key": "cip_cutting_state",
    },
    "cip_hybrid_left": {
        "enable_key": "cip_hybrid_left_enable",
        "on_time_key": "hybrid_left_on_time",
        "off_time_key": "hybrid_left_off_time",
        "state_key": "cip_hybrid_left_state",
    },
    "cip_hybrid_right": {
        "enable_key": "cip_hybrid_right_enable",
        "on_time_key": "hybrid_right_on_time",
        "off_time_key": "hybrid_right_off_time",
        "state_key": "cip_hybrid_right_state",
    },
}