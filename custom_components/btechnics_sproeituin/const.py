"""Constanten voor Btechnics Sproeituin."""
DOMAIN = "btechnics_sproeituin"
PLATFORMS = ["sensor", "button", "switch", "number", "select"]

MQTT_TOPICS = {
    "status":   "{base}/status",
    "sensoren": "{base}/sensoren",
    "positie":  "{base}/positie",
    "waterlog": "{base}/waterlog",
    "cmd_start": "{base}/cmd/start",
    "cmd_stop":  "{base}/cmd/stop",
    "cmd_home":  "{base}/cmd/home",
    "cmd_lcd":   "{base}/cmd/lcd",
    "cmd_zone":  "{base}/cmd/zone",
    "cmd_jog":   "{base}/cmd/jog",
}

CONF_MQTT_BASE  = "mqtt_base_topic"
CONF_MQTT_HOST  = "mqtt_host"
CONF_MQTT_PORT  = "mqtt_port"
CONF_DEVICE_NAME = "device_name"
