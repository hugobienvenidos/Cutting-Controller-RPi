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
    # 3 = la RPi elle-même (voir RPI_SLAVE_* plus bas) -> pas un device à interroger ici
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
# ON_TIME/OFF_TIME piloté par coils/holding registers (voir RPI_SLAVE_* plus bas
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

# --- RPi en tant que Modbus SLAVE (adresse 3) de ses propres I/O ---
# Transport : Modbus TCP par défaut (pas besoin d'un 2e adaptateur RS485).
# Si tu préfères un 2e bus RS485 physique, dis-le et on adapte rpi_modbus_slave.py.
RPI_SLAVE_ID = 3
RPI_SLAVE_TCP_HOST = "0.0.0.0"   # écoute sur toutes les interfaces réseau
RPI_SLAVE_TCP_PORT = 502          # port Modbus TCP standard (peut nécessiter root/setcap sous Linux)

# Coils (00001-00003) — activation de chaque zone CIP, écrits par un maître externe
RPI_SLAVE_COILS = {
    "cip_cutting_enable": 0,        # 00001
    "cip_hybrid_left_enable": 1,    # 00002
    "cip_hybrid_right_enable": 2,   # 00003
}

# Input registers (10001-10006) — télémétrie en lecture seule pour un maître externe
RPI_SLAVE_INPUT_REGISTERS = {
    "presence_mask": 0,           # 10001 (bit0-3 = presence_1..4)
    "dol_blades_trip": 1,         # 10002
    "dol_blades_state": 2,        # 10003
    "cip_cutting_state": 3,       # 10004 (0 idle, 1 on, 2 off)
    "cip_hybrid_left_state": 4,   # 10005
    "cip_hybrid_right_state": 5,  # 10006
}

# Holding registers (40001-40006) — durées de cycle CIP en ms, réglables par un maître externe
RPI_SLAVE_HOLDING_REGISTERS = {
    "cutting_on_time": 0,          # 40001
    "cutting_off_time": 1,         # 40002
    "hybrid_left_on_time": 2,      # 40003
    "hybrid_left_off_time": 3,     # 40004
    "hybrid_right_on_time": 4,     # 40005
    "hybrid_right_off_time": 5,    # 40006
}

# Valeurs par défaut du cycle CIP (ms) au démarrage, avant tout réglage externe
RPI_SLAVE_DEFAULT_HOLDING = {
    "cutting_on_time": 2000, "cutting_off_time": 8000,
    "hybrid_left_on_time": 2000, "hybrid_left_off_time": 8000,
    "hybrid_right_on_time": 2000, "hybrid_right_off_time": 8000,
}
