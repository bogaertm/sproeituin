"""Nummerieke entiteiten voor Btechnics Sproeituin."""
from __future__ import annotations
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from .const import DOMAIN


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    name = entry.data.get("device_name", "Sproeituin")
    async_add_entities([JogStapgrootte(entry, name)])


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
