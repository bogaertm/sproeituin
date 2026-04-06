"""Select entiteit voor LCD pagina — Btechnics Sproeituin."""
from __future__ import annotations
from homeassistant.components import mqtt
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .const import DOMAIN

LCD_OPTIES = ["status", "temp", "moisture", "water", "zone"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    base = entry.data.get("mqtt_base_topic", "sproeituin")
    name = entry.data.get("device_name", "Sproeituin")
    async_add_entities([LcdPaginaSelect(hass, entry, base, name)])


class LcdPaginaSelect(SelectEntity):
    def __init__(self, hass, entry, base, name):
        self.hass = hass
        self._base = base
        self._attr_name = f"{name} LCD weergave"
        self._attr_unique_id = f"{entry.entry_id}_lcd_pagina"
        self._attr_options = LCD_OPTIES
        self._attr_current_option = "status"
        self._attr_icon = "mdi:monitor"

    async def async_select_option(self, option: str) -> None:
        self._attr_current_option = option
        self.async_write_ha_state()
        await mqtt.async_publish(self.hass, f"{self._base}/cmd/lcd", option)
