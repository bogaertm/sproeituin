"""Btechnics Sproeituin integratie voor Home Assistant."""
from __future__ import annotations
import logging
import json
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.components import mqtt
from .const import DOMAIN, PLATFORMS

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = entry.data
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    base = entry.data.get("mqtt_base_topic", "sproeituin")

    async def handle_start(call: ServiceCall) -> None:
        await mqtt.async_publish(hass, f"{base}/cmd/start", "start")

    async def handle_stop(call: ServiceCall) -> None:
        await mqtt.async_publish(hass, f"{base}/cmd/stop", "stop")

    async def handle_home(call: ServiceCall) -> None:
        await mqtt.async_publish(hass, f"{base}/cmd/home", "home")

    async def handle_jog(call: ServiceCall) -> None:
        payload = json.dumps({
            "as": call.data.get("as", "x"),
            "mm": call.data.get("mm", 10)
        })
        await mqtt.async_publish(hass, f"{base}/cmd/jog", payload)

    async def handle_zone(call: ServiceCall) -> None:
        payload = json.dumps({
            "id":     call.data.get("id", 0),
            "name":   call.data.get("name", "Plant"),
            "x":      call.data.get("x", 0),
            "y":      call.data.get("y", 0),
            "ml":     call.data.get("ml", 50),
            "active": call.data.get("active", True)
        })
        await mqtt.async_publish(hass, f"{base}/cmd/zone", payload)

    hass.services.async_register(DOMAIN, "start",          handle_start)
    hass.services.async_register(DOMAIN, "stop",           handle_stop)
    hass.services.async_register(DOMAIN, "home",           handle_home)
    hass.services.async_register(DOMAIN, "jog",            handle_jog)
    hass.services.async_register(DOMAIN, "zone_instellen", handle_zone)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
