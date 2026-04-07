"""Constanten voor Btechnics Sproeituin."""
DOMAIN = "btechnics_sproeituin"
PLATFORMS = ["sensor", "button", "switch", "number", "text"]

CONF_MQTT_BASE   = "mqtt_base_topic"
CONF_DEVICE_NAME = "device_name"

ZONES_DEFAULT = [
    (0, "Basilicum",       200,  112, 50),
    (1, "Munt",            600,  112, 60),
    (2, "Rozemarijn",     1000,  112, 40),
    (3, "Tijm",           1400,  112, 35),
    (4, "Peterselie",     1800,  112, 45),
    (5, "Salie",           200,  337, 40),
    (6, "Citroenmelisse",  600,  337, 55),
    (7, "Oregano",        1000,  337, 40),
    (8, "Bieslook",       1400,  337, 50),
    (9, "Koriander",      1800,  337, 45),
]
