"""Binary sensor platform for MakerWorld."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_USER, DOMAIN
from .coordinator import MakerWorldDataUpdateCoordinator


@dataclass
class MakerWorldBinarySensorDescription(BinarySensorEntityDescription):
    """Description of a MakerWorld binary sensor."""

    data_key: str = ""
    permission_key: Optional[str] = None


BANNED_PERMISSION_SENSORS = [
    MakerWorldBinarySensorDescription(
        key="makerworld_banned_comment",
        name="Banned Comment",
        data_key="Diagnostics",
        permission_key="comment",
    ),
    MakerWorldBinarySensorDescription(
        key="makerworld_banned_community",
        name="Banned Community",
        data_key="Diagnostics",
        permission_key="community",
    ),
    MakerWorldBinarySensorDescription(
        key="makerworld_banned_design_notify",
        name="Banned Design Notify",
        data_key="Diagnostics",
        permission_key="designNotify",
    ),
    MakerWorldBinarySensorDescription(
        key="makerworld_banned_private_msg",
        name="Banned Private Msg",
        data_key="Diagnostics",
        permission_key="privateMsg",
    ),
    MakerWorldBinarySensorDescription(
        key="makerworld_banned_redeem",
        name="Banned Redeem",
        data_key="Diagnostics",
        permission_key="redeem",
    ),
    MakerWorldBinarySensorDescription(
        key="makerworld_banned_upload",
        name="Banned Upload",
        data_key="Diagnostics",
        permission_key="upload",
    ),
    MakerWorldBinarySensorDescription(
        key="makerworld_banned_whole",
        name="Banned Whole",
        data_key="Diagnostics",
        permission_key="whole",
    ),
]

OTHER_BINARY_SENSORS = [
    MakerWorldBinarySensorDescription(
        key="makerworld_verified",
        name="Verified",
        data_key="Diagnostics",
    ),
    MakerWorldBinarySensorDescription(
        key="makerworld_commercial_licence",
        name="Commercial Licence",
        data_key="Diagnostics",
    ),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Set up MakerWorld binary sensors based on a config entry."""
    coordinator: MakerWorldDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    user = entry.data[CONF_USER].lstrip("@")

    entities = [
        MakerWorldBannedPermissionBinarySensor(coordinator, description, user)
        for description in BANNED_PERMISSION_SENSORS
    ]
    entities.extend(
        [MakerWorldFlagBinarySensor(coordinator, description, user) for description in OTHER_BINARY_SENSORS]
    )

    async_add_entities(entities)


class MakerWorldBannedPermissionBinarySensor(
    CoordinatorEntity[MakerWorldDataUpdateCoordinator], BinarySensorEntity
):
    """Binary sensor for a banned permission flag."""

    entity_description: MakerWorldBinarySensorDescription

    def __init__(
        self,
        coordinator: MakerWorldDataUpdateCoordinator,
        description: MakerWorldBinarySensorDescription,
        user: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._user = user
        self._attr_unique_id = f"{user}_{description.key}"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, user)},
            manufacturer="mplinuxgeek",
            name=f"MakerWorld Stats ({user})",
            model="MakerWorld Stats",
            configuration_url=f"https://makerworld.com/@{user}",
        )

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data or {}
        diagnostics = data.get(self.entity_description.data_key)
        if not isinstance(diagnostics, dict):
            return None
        banned = diagnostics.get("bannedPermission")
        if not isinstance(banned, dict):
            return None
        value = banned.get(self.entity_description.permission_key)
        if isinstance(value, bool):
            return value
        return None


class MakerWorldFlagBinarySensor(
    CoordinatorEntity[MakerWorldDataUpdateCoordinator], BinarySensorEntity
):
    """Binary sensor for profile flags."""

    entity_description: MakerWorldBinarySensorDescription

    def __init__(
        self,
        coordinator: MakerWorldDataUpdateCoordinator,
        description: MakerWorldBinarySensorDescription,
        user: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._user = user
        self._attr_unique_id = f"{user}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, user)},
            manufacturer="mplinuxgeek",
            name=f"MakerWorld Stats ({user})",
            model="MakerWorld Stats",
            configuration_url=f"https://makerworld.com/@{user}",
        )

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data or {}
        diagnostics = data.get(self.entity_description.data_key)
        if not isinstance(diagnostics, dict):
            return None
        if self.entity_description.key == "makerworld_verified":
            value = diagnostics.get("certificated")
        else:
            value = diagnostics.get("canSubscribeCommercialLicense")
        if isinstance(value, bool):
            return value
        return None
