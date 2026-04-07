"""Tekst entiteiten voor Btechnics Sproeituin — zone namen aanpassen."""
from __future__ import annotations
import json
from homeassistant.components import mqtt
from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from .const import DOMAIN, ZONES_DEFAULT


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    base = entry.data.get("mqtt_base_topic", "sproeituin")
    entities = []
    for zone_id, zone_naam, x, y, ml in ZONES_DEFAULT:
        entities.append(ZoneNaam(hass, entry, base, zone_id, zone_naam))
    async_add_entities(entities)


class ZoneNaam(TextEntity, RestoreEntity):
    """Zone naam aanpassen — stuurt update naar Pi via MQTT."""
    def __init__(self, hass, entry, base, zone_id, default_naam):
        self.hass = hass
        self._base = base
        self._zone_id = zone_id
        self._attr_name = f"Zone {zone_id} naam"
        self._attr_unique_id = f"{entry.entry_id}_zone_{zone_id}_naam"
        self._attr_native_value = default_naam
        self._attr_native_min = 1
        self._attr_native_max = 32
        self._attr_icon = "mdi:flower-outline"

    async def async_added_to_hass(self) -> None:
        last = await self.async_get_last_state()
        if last and last.state not in ("unknown", "unavailable"):
            self._attr_native_value = last.state
        # Sync met MQTT zones topic
        @callback
        def zones_ontvangen(msg):
            try:
                zones = json.loads(msg.payload)
                for z in zones:
                    if z.get("id") == self._zone_id:
                        self._attr_native_value = z.get("name", self._attr_native_value)
                        self.async_write_ha_state()
            except Exception:
                pass
        await mqtt.async_subscribe(self.hass, f"{self._base}/zones", zones_ontvangen)

    async def async_set_value(self, value: str) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()
        payload = json.dumps({"id": self._zone_id, "name": value})
        await mqtt.async_publish(self.hass, f"{self._base}/cmd/zone", payload)
