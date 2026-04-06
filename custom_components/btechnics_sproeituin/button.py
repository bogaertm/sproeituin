"""Knoppen voor Btechnics Sproeituin."""
from __future__ import annotations
from homeassistant.components import mqtt
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .const import DOMAIN


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    base = entry.data.get("mqtt_base_topic", "sproeituin")
    name = entry.data.get("device_name", "Sproeituin")
    async_add_entities([
        SproeituinButton(hass, entry, base, name, "Start",    "mdi:play",           f"{base}/cmd/start", "start"),
        SproeituinButton(hass, entry, base, name, "Stop",     "mdi:stop",           f"{base}/cmd/stop",  "stop"),
        SproeituinButton(hass, entry, base, name, "Home",     "mdi:home",           f"{base}/cmd/home",  "home"),
        SproeituinButton(hass, entry, base, name, "Noodstop", "mdi:alert-octagon",  f"{base}/cmd/stop",  "stop"),
    ])


class SproeituinButton(ButtonEntity):
    def __init__(self, hass, entry, base, name, label, icon, topic, payload):
        self.hass = hass
        self._topic = topic
        self._payload = payload
        self._attr_name = f"{name} {label}"
        self._attr_unique_id = f"{entry.entry_id}_btn_{label.lower()}"
        self._attr_icon = icon

    async def async_press(self) -> None:
        await mqtt.async_publish(self.hass, self._topic, self._payload)
