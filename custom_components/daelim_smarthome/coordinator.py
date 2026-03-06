"""Coordinator for Daelim SmartHome event sensors."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class DaelimEventCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for door/vehicle/camera event."""

    def __init__(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Initialize event coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Daelim SmartHome Events",
            update_interval=None,
        )

    def trigger_from_fcm(
        self,
        door_communal: bool = False,
        door_front: bool = False,
        vehicle: bool = False,
        camera_motion: bool = False,
    ) -> None:
        """Trigger sensor update from FCM push."""
        data: dict[str, Any] = {
            "door_communal_trigger": door_communal,
            "door_front_trigger": door_front,
            "vehicle_trigger": vehicle,
            "camera_motion_trigger": camera_motion,
        }
        self.async_set_updated_data(data)

    async def _async_update_data(self) -> dict[str, Any]:
        """Initial data only - updates come via FCM push."""
        return {
            "door_front_trigger": False,
            "door_communal_trigger": False,
            "vehicle_trigger": False,
            "camera_motion_trigger": False,
        }
