"""DataUpdateCoordinator for Daelim SmartHome."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .client import DaelimClient

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = 30


class DaelimDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for Daelim SmartHome device data."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: DaelimClient,
        entry_id: str,
    ) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Daelim SmartHome",
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        self.entry_id = entry_id
        self._control_info: dict[str, Any] = {}
        self._menu_items: list[dict] = []

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch device data."""
        result: dict[str, Any] = {
            "light": [],
            "wallsocket": [],
            "outlet": [],
            "heating": [],
            "heater": [],
            "cooling": [],
            "cooler": [],
            "gas": [],
            "fan": [],
        }

        for device_type in ["light", "wallsocket", "heating", "cooling", "gas", "fan"]:
            resp = await self.client.device_query(device_type, "all")
            if resp and "item" in resp:
                for item in resp["item"]:
                    if item.get("device") == device_type:
                        result[device_type].append(item)

        return result

    def set_control_info(self, control_info: dict[str, Any]) -> None:
        """Set control info from menu response."""
        self._control_info = control_info

    def get_control_devices(self, device_type: str) -> list[dict]:
        """Get devices from control info for lazy init."""
        return self._control_info.get(device_type, [])


class DaelimEventCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for door/vehicle/camera event (FCM push only, no polling)."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: DaelimClient,
        entry_id: str,
    ) -> None:
        """Initialize event coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Daelim SmartHome Events",
            update_interval=None,
        )
        self.client = client
        self.entry_id = entry_id

    def trigger_from_fcm(
        self,
        door_communal: bool = False,
        door_front: bool = False,
        vehicle: bool = False,
        camera_motion: bool = False,
    ) -> None:
        """Trigger sensor update from FCM push (call from any thread)."""
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
