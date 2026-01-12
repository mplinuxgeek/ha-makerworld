"""Sensor platform for MakerWorld."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_USER, DOMAIN
from .coordinator import MakerWorldDataUpdateCoordinator


@dataclass
class MakerWorldSensorDescription(SensorEntityDescription):
    """Description of a MakerWorld sensor."""

    data_key: str = ""
    top_key: Optional[str] = None


SUMMARY_SENSORS = [
    MakerWorldSensorDescription(key="makerworld_likes", name="Likes", data_key="Likes"),
    MakerWorldSensorDescription(
        key="makerworld_downloads", name="Downloads", data_key="Downloads"
    ),
    MakerWorldSensorDescription(key="makerworld_prints", name="Prints", data_key="Prints"),
    MakerWorldSensorDescription(key="makerworld_points", name="Points", data_key="Points"),
    MakerWorldSensorDescription(
        key="makerworld_followers", name="Followers", data_key="Followers"
    ),
    MakerWorldSensorDescription(
        key="makerworld_boosts_received",
        name="Boosts Received",
        data_key="Boosts Received",
    ),
    MakerWorldSensorDescription(key="makerworld_models", name="Models", data_key="Models"),
]

TOP_SENSORS = [
    MakerWorldSensorDescription(
        key="makerworld_most_liked_model",
        name="Most Liked Model",
        data_key="Top",
        top_key="Most Liked Model",
    ),
    MakerWorldSensorDescription(
        key="makerworld_most_downloaded_model",
        name="Most Downloaded Model",
        data_key="Top",
        top_key="Most Downloaded Model",
    ),
    MakerWorldSensorDescription(
        key="makerworld_most_printed_model",
        name="Most Printed Model",
        data_key="Top",
        top_key="Most Printed Model",
    ),
]

OTHER_DIAGNOSTIC_SENSORS = [
    MakerWorldSensorDescription(
        key="makerworld_last_update",
        name="Last Update",
        data_key="last_update",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    MakerWorldSensorDescription(
        key="makerworld_badges",
        name="Badges",
        data_key="Diagnostics",
    ),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Set up MakerWorld sensors based on a config entry."""
    coordinator: MakerWorldDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    user = entry.data[CONF_USER].lstrip("@")

    entities = [
        MakerWorldSensor(coordinator, description, user)
        for description in SUMMARY_SENSORS + TOP_SENSORS + OTHER_DIAGNOSTIC_SENSORS
    ]

    async_add_entities(entities)


class MakerWorldSensor(CoordinatorEntity[MakerWorldDataUpdateCoordinator], SensorEntity):
    """Representation of a MakerWorld sensor."""

    entity_description: MakerWorldSensorDescription

    def __init__(
        self,
        coordinator: MakerWorldDataUpdateCoordinator,
        description: MakerWorldSensorDescription,
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
        if description.key == "makerworld_last_update":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> Any:
        data = self.coordinator.data or {}
        
        if self.entity_description.key == "makerworld_last_update":
            return data.get("last_update")
        
        if self.entity_description.top_key:
            top = data.get(self.entity_description.data_key, {})
            if not isinstance(top, dict):
                return None
            model = top.get(self.entity_description.top_key)
            if not isinstance(model, dict):
                return None
            return model.get("title")

        if self.entity_description.key == "makerworld_badges":
            diagnostics = data.get(self.entity_description.data_key)
            if not isinstance(diagnostics, dict):
                return None
            badges = diagnostics.get("badges")
            if not isinstance(badges, list):
                return None
            titles = [
                badge.get("title")
                for badge in badges
                if isinstance(badge, dict) and isinstance(badge.get("title"), str)
            ]
            return ", ".join(titles) if titles else None

        return data.get(self.entity_description.data_key)

    @property
    def extra_state_attributes(self) -> Dict[str, Any] | None:
        data = self.coordinator.data or {}
        if self.entity_description.key == "makerworld_badges":
            diagnostics = data.get(self.entity_description.data_key)
            if not isinstance(diagnostics, dict):
                return None
            badges = diagnostics.get("badges")
            if not isinstance(badges, list):
                return None
            titles = [
                badge.get("title")
                for badge in badges
                if isinstance(badge, dict) and isinstance(badge.get("title"), str)
            ]
            return {
                "badges": titles,
                "verified": diagnostics.get("certificated"),
                "commercial_licence": diagnostics.get("canSubscribeCommercialLicense"),
            }

        if not self.entity_description.top_key:
            return None

        top = data.get(self.entity_description.data_key, {})
        if not isinstance(top, dict):
            return None
        model = top.get(self.entity_description.top_key)
        if not isinstance(model, dict):
            return None

        metric_key = None
        if self.entity_description.top_key == "Most Liked Model":
            metric_key = "likeCount"
        elif self.entity_description.top_key == "Most Downloaded Model":
            metric_key = "downloadCount"
        elif self.entity_description.top_key == "Most Printed Model":
            metric_key = "printCount"

        metric_value = model.get(metric_key) if metric_key else None

        return {
            "title": model.get("title"),
            "url": model.get("url"),
            "id": model.get("id"),
            "count": metric_value,
        }
