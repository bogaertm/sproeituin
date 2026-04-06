"""Sensoren voor Btechnics Sproeituin."""
from __future__ import annotations
import json
import logging
from homeassistant.components import mqtt
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    base = entry.data.get("mqtt_base_topic", "sproeituin")
    name = entry.data.get("device_name", "Sproeituin")
    entities = [
        SproeituinStatusSensor(hass, entry, base, name),
        SproeituinJsonSensor(hass, entry, base, name, "temp",     "Temperatuur",      "\u00b0C", SensorDeviceClass.TEMPERATURE,     SensorStateClass.MEASUREMENT),
        SproeituinJsonSensor(hass, entry, base, name, "humidity", "Luchtvochtigheid", "%",        SensorDeviceClass.HUMIDITY,        SensorStateClass.MEASUREMENT),
        SproeituinJsonSensor(hass, entry, base, name, "vpd",      "VPD",              "kPa",      None,                              SensorStateClass.MEASUREMENT),
        SproeituinJsonSensor(hass, entry, base, name, "water_ml", "Water sessie",     "ml",       None,                              SensorStateClass.MEASUREMENT),
        SproeituinJsonSensor(hass, entry, base, name, "rssi",     "WiFi signaal",     "dBm",      SensorDeviceClass.SIGNAL_STRENGTH, SensorStateClass.MEASUREMENT),
        SproeituinPositieSensor(hass, entry, base, name, "x", "Positie X", "mm"),
        SproeituinPositieSensor(hass, entry, base, name, "y", "Positie Y", "mm"),
        SproeituinMoistureSensor(hass, entry, base, name),
        SproeituinWaterlogSensor(hass, entry, base, name),
        SproeituinLogSensor(hass, entry, base, name),
    ]
    async_add_entities(entities)


class SproeituinStatusSensor(SensorEntity):
    def __init__(self, hass, entry, base, name):
        self.hass = hass
        self._base = base
        self._attr_name = f"{name} Status"
        self._attr_unique_id = f"{entry.entry_id}_status"
        self._attr_icon = "mdi:sprinkler"
        self._attr_native_value = None

    async def async_added_to_hass(self):
        @callback
        def message_received(msg):
            self._attr_native_value = msg.payload
            self.async_write_ha_state()
        await mqtt.async_subscribe(self.hass, f"{self._base}/status", message_received)


class SproeituinJsonSensor(SensorEntity):
    def __init__(self, hass, entry, base, name, key, label, unit, device_class, state_class):
        self.hass = hass
        self._base = base
        self._key = key
        self._attr_name = f"{name} {label}"
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_native_value = None

    async def async_added_to_hass(self):
        @callback
        def message_received(msg):
            try:
                data = json.loads(msg.payload)
                val = data.get(self._key)
                if val is not None:
                    self._attr_native_value = round(float(val), 2)
                    self.async_write_ha_state()
            except Exception:
                pass
        await mqtt.async_subscribe(self.hass, f"{self._base}/sensoren", message_received)


class SproeituinMoistureSensor(SensorEntity):
    """Bodemvochtigheid als % — converteert raw ADC 0-1023."""
    def __init__(self, hass, entry, base, name):
        self.hass = hass
        self._base = base
        self._attr_name = f"{name} Bodemvochtigheid"
        self._attr_unique_id = f"{entry.entry_id}_moisture"
        self._attr_native_unit_of_measurement = "%"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:water-percent"
        self._attr_native_value = None

    async def async_added_to_hass(self):
        @callback
        def message_received(msg):
            try:
                data = json.loads(msg.payload)
                raw = data.get("moisture")
                if raw is not None:
                    pct = round((1 - int(raw) / 1023) * 100, 1)
                    self._attr_native_value = pct
                    self.async_write_ha_state()
            except Exception:
                pass
        await mqtt.async_subscribe(self.hass, f"{self._base}/sensoren", message_received)


class SproeituinPositieSensor(SensorEntity):
    def __init__(self, hass, entry, base, name, key, label, unit):
        self.hass = hass
        self._base = base
        self._key = key
        self._attr_name = f"{name} {label}"
        self._attr_unique_id = f"{entry.entry_id}_pos_{key}"
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = "mdi:arrow-left-right" if key == "x" else "mdi:arrow-up-down"
        self._attr_native_value = None

    async def async_added_to_hass(self):
        @callback
        def message_received(msg):
            try:
                data = json.loads(msg.payload)
                self._attr_native_value = data.get(self._key)
                self.async_write_ha_state()
            except Exception:
                pass
        await mqtt.async_subscribe(self.hass, f"{self._base}/positie", message_received)


class SproeituinWaterlogSensor(SensorEntity):
    def __init__(self, hass, entry, base, name):
        self.hass = hass
        self._base = base
        self._attr_name = f"{name} Waterlog"
        self._attr_unique_id = f"{entry.entry_id}_waterlog"
        self._attr_icon = "mdi:water"
        self._attr_native_value = None

    async def async_added_to_hass(self):
        @callback
        def message_received(msg):
            try:
                data = json.loads(msg.payload)
                self._attr_native_value = f"{data.get('zone', '?')}: {data.get('ml', '?')}ml"
                self.async_write_ha_state()
            except Exception:
                pass
        await mqtt.async_subscribe(self.hass, f"{self._base}/waterlog", message_received)


class SproeituinLogSensor(SensorEntity):
    def __init__(self, hass, entry, base, name):
        self.hass = hass
        self._base = base
        self._attr_name = f"{name} Log"
        self._attr_unique_id = f"{entry.entry_id}_log"
        self._attr_icon = "mdi:text-box-outline"
        self._attr_native_value = None

    async def async_added_to_hass(self):
        @callback
        def message_received(msg):
            self._attr_native_value = msg.payload
            self.async_write_ha_state()
        await mqtt.async_subscribe(self.hass, f"{self._base}/log", message_received)
