"""MakerWorld integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import CONF_COOKIE, DEFAULT_SCAN_INTERVAL, DOMAIN, PLATFORMS
from .coordinator import MakerWorldDataUpdateCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up MakerWorld from a config entry."""
    # Migration: cookie used to be stored in options; keep one source of truth in entry data.
    if CONF_COOKIE in entry.options:
        new_data = dict(entry.data)
        opt_cookie = entry.options.get(CONF_COOKIE)
        if isinstance(opt_cookie, str) and opt_cookie.strip():
            new_data[CONF_COOKIE] = opt_cookie
        new_options = dict(entry.options)
        new_options.pop(CONF_COOKIE, None)
        hass.config_entries.async_update_entry(entry, data=new_data, options=new_options)

    session = async_get_clientsession(hass)

    coordinator: DataUpdateCoordinator = MakerWorldDataUpdateCoordinator(
        hass,
        session=session,
        config=entry.data,
        options=entry.options,
        update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
