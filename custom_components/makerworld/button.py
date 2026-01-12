"""Button platform for MakerWorld."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_USER, DOMAIN
from .coordinator import MakerWorldDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Set up MakerWorld button based on a config entry."""
    coordinator: MakerWorldDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    user = entry.data[CONF_USER].lstrip("@")

    async_add_entities([MakerWorldRefreshButton(coordinator, user)])


class MakerWorldRefreshButton(CoordinatorEntity[MakerWorldDataUpdateCoordinator], ButtonEntity):
    """Button to trigger a manual refresh."""

    def __init__(self, coordinator: MakerWorldDataUpdateCoordinator, user: str) -> None:
        super().__init__(coordinator)
        self._user = user
        self._attr_unique_id = f"{user}_makerworld_refresh"
        self._attr_name = "Refresh"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, user)},
            manufacturer="mplinuxgeek",
            name=f"MakerWorld Stats ({user})",
            model="MakerWorld Stats",
            configuration_url=f"https://makerworld.com/@{user}",
        )

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.coordinator.async_refresh()
