"""Nummerieke entiteiten voor Btechnics Sproeituin."""
from __future__ import annotations
import json
from homeassistant.components import mqtt
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from .const import DOMAIN, ZONES_DEFAULT


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    base = entry.data.get("mqtt_base_topic", "sproeituin")
    name = entry.data.get("device_name", "Sproeituin")
    entities = [JogStapgrootte(entry, name), DemoMl(hass, entry, base, name)]
    for zone_id, zone_naam, x, y, ml in ZONES_DEFAULT:
        entities.append(ZoneMl(hass, entry, base, zone_id, zone_naam, ml))
    async_add_entities(entities)


class JogStapgrootte(NumberEntity, RestoreEntity):
    def __init__(self, entry, name):
        self._attr_name = f"{name} Jog stapgrootte"
        self._attr_unique_id = f"{entry.entry_id}_jog_stap"
        self._attr_native_min_value = 1
        self._attr_native_max_value = 200
        self._attr_native_step = 1
        self._attr_native_value = 10
        self._attr_native_unit_of_measurement = "mm"
        self._attr_mode = NumberMode.BOX
        self._attr_icon = "mdi:arrow-expand-all"

    async def async_added_to_hass(self) -> None:
        last = await self.async_get_last_state()
        if last and last.state not in ("unknown", "unavailable"):
            try:
                self._attr_native_value = int(float(last.state))
            except ValueError:
                pass

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = int(value)
        self.async_write_ha_state()


class DemoMl(NumberEntity, RestoreEntity):
    """Hoeveelheid ml per plant bij demo sproei."""
    def __init__(self, hass, entry, base, name):
        self.hass = hass
        self._base = base
        self._attr_name = f"{name} Demo ml"
        self._attr_unique_id = f"{entry.entry_id}_demo_ml"
        self._attr_native_min_value = 5
        self._attr_native_max_value = 200
        self._attr_native_step = 5
        self._attr_native_value = 20
        self._attr_native_unit_of_measurement = "ml"
        self._attr_mode = NumberMode.BOX
        self._attr_icon = "mdi:water-plus"

    async def async_added_to_hass(self) -> None:
        last = await self.async_get_last_state()
        if last and last.state not in ("unknown", "unavailable"):
            try:
                self._attr_native_value = int(float(last.state))
            except ValueError:
                pass

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = int(value)
        self.async_write_ha_state()
        await mqtt.async_publish(self.hass, f"{self._base}/cmd/demo_ml", str(int(value)))


class ZoneMl(NumberEntity, RestoreEntity):
    """Watervolume in ml voor een zone."""
    def __init__(self, hass, entry, base, zone_id, zone_naam, default_ml):
        self.hass = hass
        self._base = base
        self._zone_id = zone_id
        self._attr_name = f"{zone_naam} ml"
        self._attr_unique_id = f"{entry.entry_id}_zone_{zone_id}_ml"
        self._attr_native_min_value = 5
        self._attr_native_max_value = 500
        self._attr_native_step = 5
        self._attr_native_value = default_ml
        self._attr_native_unit_of_measurement = "ml"
        self._attr_mode = NumberMode.BOX
        self._attr_icon = "mdi:water"

    async def async_added_to_hass(self) -> None:
        last = await self.async_get_last_state()
        if last and last.state not in ("unknown", "unavailable"):
            try:
                self._attr_native_value = int(float(last.state))
            except ValueError:
                pass
        # Sync met MQTT zones topic
        @callback
        def zones_ontvangen(msg):
            try:
                import json as _json
                zones = _json.loads(msg.payload)
                for z in zones:
                    if z.get("id") == self._zone_id:
                        self._attr_native_value = z.get("ml", self._attr_native_value)
                        self.async_write_ha_state()
            except Exception:
                pass
        await mqtt.async_subscribe(self.hass, f"{self._base}/zones", zones_ontvangen)

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = int(value)
        self.async_write_ha_state()
        payload = json.dumps({"id": self._zone_id, "ml": int(value)})
        await mqtt.async_publish(self.hass, f"{self._base}/cmd/zone", payload)
