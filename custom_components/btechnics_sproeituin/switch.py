"""Zones aan/uit voor Btechnics Sproeituin."""
from __future__ import annotations
import json
from homeassistant.components import mqtt
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .const import DOMAIN

ZONES = [
    (0, "Basilicum",      200,  112, 50),
    (1, "Munt",           600,  112, 60),
    (2, "Rozemarijn",    1000,  112, 40),
    (3, "Tijm",          1400,  112, 35),
    (4, "Peterselie",    1800,  112, 45),
    (5, "Salie",          200,  337, 40),
    (6, "Citroenmelisse", 600,  337, 55),
    (7, "Oregano",       1000,  337, 40),
    (8, "Bieslook",      1400,  337, 50),
    (9, "Koriander",     1800,  337, 45),
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    base = entry.data.get("mqtt_base_topic", "sproeituin")
    async_add_entities([ZoneSwitch(hass, entry, base, *z) for z in ZONES])


class ZoneSwitch(SwitchEntity):
    def __init__(self, hass, entry, base, zone_id, naam, x, y, ml):
        self.hass = hass
        self._base = base
        self._zone_id = zone_id
        self._naam = naam
        self._x = x
        self._y = y
        self._ml = ml
        self._attr_name = f"Zone {zone_id} {naam}"
        self._attr_unique_id = f"{entry.entry_id}_zone_{zone_id}"
        self._attr_icon = "mdi:flower"
        self._attr_is_on = True

    async def async_turn_on(self, **kwargs):
        self._attr_is_on = True
        self.async_write_ha_state()
        await self._publish(True)

    async def async_turn_off(self, **kwargs):
        self._attr_is_on = False
        self.async_write_ha_state()
        await self._publish(False)

    async def _publish(self, active: bool):
        payload = json.dumps({
            "id": self._zone_id, "name": self._naam,
            "x": self._x, "y": self._y,
            "ml": self._ml, "active": active
        })
        await mqtt.async_publish(self.hass, f"{self._base}/cmd/zone", payload)
