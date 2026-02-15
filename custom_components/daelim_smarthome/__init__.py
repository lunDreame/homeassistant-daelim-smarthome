"""Daelim SmartHome integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .client import DaelimClient
from .config_flow import generate_uuid_from_username
from .const import DOMAIN, MANUFACTURER, EventPushTypes, PushTypes
from .coordinator import DaelimEventCoordinator
from .fcm_client import DaelimFcmClient

if TYPE_CHECKING:
    from homeassistant.helpers.typing import ConfigType

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.LIGHT,
    Platform.SWITCH,
    Platform.CLIMATE,
    Platform.LOCK,
    Platform.FAN,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CAMERA,
]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up Daelim SmartHome component."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Daelim SmartHome from config entry."""
    hass.data.setdefault(DOMAIN, {})

    uuid = entry.data.get("uuid") or generate_uuid_from_username(
        entry.data["username"]
    )
    client = DaelimClient(
        server_ip=entry.data["server_ip"],
        username=entry.data["username"],
        password=entry.data["password"],
        uuid=uuid,
        complex_name=entry.data["complex"],
    )

    if not await client.login():
        _LOGGER.error("Failed to login to Daelim SmartHome")
        return False

    event_coordinator = DaelimEventCoordinator(hass, client, entry.entry_id)

    def _on_fcm_push(ptype: int, sub_type: int, data: dict) -> None:
        """Handle FCM push notification (may be called from background thread)."""

        async def _handle() -> None:
            if ptype == PushTypes.EVENTS:
                msg = str(data.get("message", ""))
                door_communal = door_front = vehicle = camera_motion = False
                if sub_type == EventPushTypes.FRONT_DOOR_CHANGES:
                    if "공동현관" in msg:
                        door_communal = True
                    else:
                        door_front = True
                elif sub_type == EventPushTypes.CAR_GETTING_IN:
                    vehicle = True
                elif sub_type == EventPushTypes.VISITOR_PICTURE_STORED:
                    camera_motion = True
                event_coordinator.trigger_from_fcm(
                    door_communal=door_communal,
                    door_front=door_front,
                    vehicle=vehicle,
                    camera_motion=camera_motion,
                )

        hass.async_add_job(_handle())

    fcm_client = DaelimFcmClient(hass, entry.entry_id, _on_fcm_push)
    fcm_token = await fcm_client.start()
    if fcm_token:
        await client.register_push_token(fcm_token)
    else:
        _LOGGER.warning(
            "FCM client failed to start - door/vehicle/visitor sensors will not "
            "receive real-time updates"
        )

    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "entry": entry,
        "event_coordinator": event_coordinator,
        "fcm_client": fcm_client,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Daelim SmartHome config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok and entry.entry_id in hass.data.get(DOMAIN, {}):
        data = hass.data[DOMAIN].pop(entry.entry_id)
        if "fcm_client" in data:
            await data["fcm_client"].stop()
        if "client" in data:
            data["client"].disconnect()
    return unload_ok
