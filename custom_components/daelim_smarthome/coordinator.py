"""Coordinator for Daelim SmartHome event sensors."""

from __future__ import annotations

import logging
from datetime import timedelta
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


class DaelimEnergyCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for periodic EMS energy data."""

    def __init__(
        self,
        hass: HomeAssistant,
        client,
    ) -> None:
        """Initialize energy coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Daelim SmartHome Energy",
            update_interval=timedelta(hours=1),
        )
        self._client = client

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch EMS monthly and yearly energy usage."""
        energy = None
        energy_yearly: dict[str, dict | None] = {}

        try:
            energy = await self._client.query_energy_monthly()
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Failed to fetch monthly energy usage: %s", err)

        try:
            energy_yearly = await self._client.query_all_energy_yearly()
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Failed to fetch yearly energy usage: %s", err)

        return {
            "energy": energy,
            "energy_yearly": energy_yearly,
        }
