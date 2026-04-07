"""Knoppen voor Btechnics Sproeituin."""
from __future__ import annotations
import json
from homeassistant.components import mqtt
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .const import DOMAIN, ZONES_DEFAULT


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    base = entry.data.get("mqtt_base_topic", "sproeituin")
    name = entry.data.get("device_name", "Sproeituin")
    name_slug = name.lower().replace(" ", "_")
    stap_entity = f"number.{name_slug}_jog_stapgrootte"

    entities = [
        SproeituinButton(hass, entry, base, name, "Start",         "mdi:play",            f"{base}/cmd/start",  ""),
        SproeituinButton(hass, entry, base, name, "Stop",          "mdi:stop",            f"{base}/cmd/stop",   ""),
        SproeituinButton(hass, entry, base, name, "Home",          "mdi:home",            f"{base}/cmd/home",   ""),
        SproeituinButton(hass, entry, base, name, "Reset",         "mdi:restart",         f"{base}/cmd/reset",  ""),
        SproeituinButton(hass, entry, base, name, "Noodstop",      "mdi:alert-octagon",   f"{base}/cmd/stop",   ""),
        SproeituinButton(hass, entry, base, name, "Demo",          "mdi:sprinkler",       f"{base}/cmd/demo",   ""),
        SproeituinButton(hass, entry, base, name, "Zone toevoegen","mdi:map-marker-plus", f"{base}/cmd/zone_toevoegen", ""),
        JogButton(hass, entry, base, name, "Jog X+", "mdi:arrow-right", "x",  1, stap_entity),
        JogButton(hass, entry, base, name, "Jog X-", "mdi:arrow-left",  "x", -1, stap_entity),
        JogButton(hass, entry, base, name, "Jog Y+", "mdi:arrow-up",    "y",  1, stap_entity),
        JogButton(hass, entry, base, name, "Jog Y-", "mdi:arrow-down",  "y", -1, stap_entity),
    ]

    for zone_id, zone_naam, x, y, ml in ZONES_DEFAULT:
        entities.append(PositieOpslaanButton(hass, entry, base, zone_id, zone_naam))
        entities.append(ZoneVerwijderenButton(hass, entry, base, zone_id, zone_naam))

    async_add_entities(entities)


class SproeituinButton(ButtonEntity):
    def __init__(self, hass, entry, base, name, label, icon, topic, payload):
        self.hass = hass
        self._topic = topic
        self._payload = payload
        self._attr_name = f"{name} {label}"
        self._attr_unique_id = f"{entry.entry_id}_btn_{label.lower().replace(' ', '_')}"
        self._attr_icon = icon

    async def async_press(self) -> None:
        await mqtt.async_publish(self.hass, self._topic, self._payload)


class JogButton(ButtonEntity):
    def __init__(self, hass, entry, base, name, label, icon, axis, richting, stap_entity):
        self.hass = hass
        self._base = base
        self._axis = axis
        self._richting = richting
        self._stap_entity = stap_entity
        self._attr_name = f"{name} {label}"
        richting_str = "pos" if richting > 0 else "neg"
        self._attr_unique_id = f"{entry.entry_id}_jog_{axis}_{richting_str}"
        self._attr_icon = icon

    async def async_press(self) -> None:
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


class PositieOpslaanButton(ButtonEntity):
    """Sla huidige XY positie op als de positie van deze zone."""
    def __init__(self, hass, entry, base, zone_id, zone_naam):
        self.hass = hass
        self._base = base
        self._zone_id = zone_id
        self._attr_name = f"{zone_naam} positie opslaan"
        self._attr_unique_id = f"{entry.entry_id}_positie_opslaan_{zone_id}"
        self._attr_icon = "mdi:map-marker-check"

    async def async_press(self) -> None:
        payload = json.dumps({"id": self._zone_id})
        await mqtt.async_publish(self.hass, f"{self._base}/cmd/positie_opslaan", payload)


class ZoneVerwijderenButton(ButtonEntity):
    """Verwijder deze zone van de Pi."""
    def __init__(self, hass, entry, base, zone_id, zone_naam):
        self.hass = hass
        self._base = base
        self._zone_id = zone_id
        self._attr_name = f"{zone_naam} verwijderen"
        self._attr_unique_id = f"{entry.entry_id}_zone_verwijderen_{zone_id}"
        self._attr_icon = "mdi:map-marker-remove"

    async def async_press(self) -> None:
        payload = json.dumps({"id": self._zone_id})
        await mqtt.async_publish(self.hass, f"{self._base}/cmd/zone_verwijderen", payload)
