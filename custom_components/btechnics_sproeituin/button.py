"""Knoppen voor Btechnics Sproeituin."""
from __future__ import annotations
import json
from homeassistant.components import mqtt
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .const import DOMAIN


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    base = entry.data.get("mqtt_base_topic", "sproeituin")
    name = entry.data.get("device_name", "Sproeituin")
    stap_entity = f"number.{name.lower()}_jog_stapgrootte"
    async_add_entities([
        SproeituinButton(hass, entry, base, name, "Start",    "mdi:play",          f"{base}/cmd/start", "start"),
        SproeituinButton(hass, entry, base, name, "Stop",     "mdi:stop",          f"{base}/cmd/stop",  "stop"),
        SproeituinButton(hass, entry, base, name, "Home",     "mdi:home",          f"{base}/cmd/home",  "home"),
        SproeituinButton(hass, entry, base, name, "Noodstop", "mdi:alert-octagon", f"{base}/cmd/stop",  "stop"),
        JogButton(hass, entry, base, name, "Jog X+",  "mdi:arrow-right", "x",  1, stap_entity),
        JogButton(hass, entry, base, name, "Jog X-",  "mdi:arrow-left",  "x", -1, stap_entity),
        JogButton(hass, entry, base, name, "Jog Y+",  "mdi:arrow-up",    "y",  1, stap_entity),
        JogButton(hass, entry, base, name, "Jog Y-",  "mdi:arrow-down",  "y", -1, stap_entity),
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


class JogButton(ButtonEntity):
    def __init__(self, hass, entry, base, name, label, icon, axis, richting, stap_entity):
        self.hass = hass
        self._base = base
        self._axis = axis
        self._richting = richting          # +1 of -1
        self._stap_entity = stap_entity   # entity_id van JogStapgrootte
        self._attr_name = f"{name} {label}"
        self._attr_unique_id = f"{entry.entry_id}_jog_{axis}_{'pos' if richting > 0 else 'neg'}"
        self._attr_icon = icon

    async def async_press(self) -> None:
        # Lees stapgrootte uit de number entity, standaard 10mm als entity niet gevonden
        stap = 10
        state = self.hass.states.get(self._stap_entity)
        if state and state.state not in ("unknown", "unavailable"):
            try:
                stap = int(float(state.state))
            except ValueError:
                pass
        mm = stap * self._richting
        payload = json.dumps({"as": self._axis, "mm": mm})
        await mqtt.async_publish(self.hass, f"{self._base}/cmd/jog", payload)
