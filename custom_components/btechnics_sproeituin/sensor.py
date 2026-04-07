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
        SproeituinPositieSensor(hass, entry, base, name, "x", "Positie X", "mm"),
        SproeituinPositieSensor(hass, entry, base, name, "y", "Positie Y", "mm"),
        SproeituinWaterlogSensor(hass, entry, base, name),
        SproeituinWaterlogTotaalSensor(hass, entry, base, name),
        SproeituinAlarmSensor(hass, entry, base, name),
        SproeituinZonesSensor(hass, entry, base, name),
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
        self._attr_name = f"{name} Laatste Sproei"
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


class SproeituinWaterlogTotaalSensor(SensorEntity):
    """Totaal water per plant uit waterlog/overzicht."""
    def __init__(self, hass, entry, base, name):
        self.hass = hass
        self._base = base
        self._attr_name = f"{name} Waterlog Overzicht"
        self._attr_unique_id = f"{entry.entry_id}_waterlog_overzicht"
        self._attr_icon = "mdi:chart-bar"
        self._attr_native_value = None
        self._extra = {}

    @property
    def extra_state_attributes(self):
        return self._extra

    async def async_added_to_hass(self):
        @callback
        def message_received(msg):
            try:
                data = json.loads(msg.payload)
                self._extra = data
                totaal = sum(v.get("totaal_ml", 0) for v in data.values())
                self._attr_native_value = round(totaal, 1)
                self.async_write_ha_state()
            except Exception:
                pass
        await mqtt.async_subscribe(self.hass, f"{self._base}/waterlog/overzicht", message_received)


class SproeituinAlarmSensor(SensorEntity):
    def __init__(self, hass, entry, base, name):
        self.hass = hass
        self._base = base
        self._attr_name = f"{name} Alarm"
        self._attr_unique_id = f"{entry.entry_id}_alarm"
        self._attr_icon = "mdi:alert"
        self._attr_native_value = None

    async def async_added_to_hass(self):
        @callback
        def message_received(msg):
            try:
                if msg.payload:
                    data = json.loads(msg.payload)
                    self._attr_native_value = f"{data.get('type','?')}: {data.get('bericht','?')}"
                else:
                    self._attr_native_value = None
                self.async_write_ha_state()
            except Exception:
                self._attr_native_value = msg.payload
                self.async_write_ha_state()
        await mqtt.async_subscribe(self.hass, f"{self._base}/alarm", message_received)


class SproeituinZonesSensor(SensorEntity):
    """Aantal actieve zones."""
    def __init__(self, hass, entry, base, name):
        self.hass = hass
        self._base = base
        self._attr_name = f"{name} Zones"
        self._attr_unique_id = f"{entry.entry_id}_zones"
        self._attr_icon = "mdi:map-marker-multiple"
        self._attr_native_value = None
        self._extra = {}

    @property
    def extra_state_attributes(self):
        return self._extra

    async def async_added_to_hass(self):
        @callback
        def message_received(msg):
            try:
                data = json.loads(msg.payload)
                actief = sum(1 for z in data if z.get("active", False))
                self._attr_native_value = actief
                self._extra = {"zones": data}
                self.async_write_ha_state()
            except Exception:
                pass
        await mqtt.async_subscribe(self.hass, f"{self._base}/zones", message_received)


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
