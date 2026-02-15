"""Button platform for Daelim SmartHome (Elevator call)."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, MANUFACTURER

_LOGGER = logging.getLogger(__name__)

ELEVATOR_DEVICE = ("EV-000000", "엘리베이터")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Daelim elevator call button."""
    data = hass.data[DOMAIN][entry.entry_id]
    client = data["client"]
    entry_id = entry.entry_id
    complex_name = entry.data["complex"]

    entity = DaelimElevatorButton(
        client,
        entry_id,
        ELEVATOR_DEVICE[0],
        ELEVATOR_DEVICE[1],
        complex_name,
    )
    async_add_entities([entity])


class DaelimElevatorButton(ButtonEntity):
    """Daelim elevator call button."""

    _attr_icon = "mdi:elevator"

    def __init__(
        self,
        client,
        entry_id: str,
        device_id: str,
        name: str,
        complex_name: str,
    ) -> None:
        """Initialize elevator button."""
        self._client = client
        self._entry_id = entry_id
        self._device_id = device_id
        self._attr_name = name
        self._attr_unique_id = f"{entry_id}_{device_id}_elevator"
        self._complex_name = complex_name

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}_{self._device_id}")},
            manufacturer=MANUFACTURER,
            model=self._complex_name,
            name=self._attr_name,
        )

    async def async_press(self) -> None:
        """Call elevator."""
        await self._client.elevator_call()
