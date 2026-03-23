"""Daelim SmartHome integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed

from .client import DaelimClient
from .config_flow import generate_uuid_from_username
from .const import DOMAIN, EventPushTypes, PushTypes
from .coordinator import DaelimEventCoordinator
from .fcm_client import DaelimFcmClient

if TYPE_CHECKING:
    from homeassistant.helpers.typing import ConfigType

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.LIGHT,
    Platform.SWITCH,
    Platform.CLIMATE,
    Platform.FAN,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.ALARM_CONTROL_PANEL,
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

    ok, extra = await client.try_login(entry.data.get("directory_name"))
    if not ok and extra and extra.get("require_wallpad"):
        client.disconnect()
        raise ConfigEntryAuthFailed("wallpad_required")
    if not ok:
        _LOGGER.error("Failed to login to Daelim SmartHome")
        return False

    event_coordinator = DaelimEventCoordinator(hass)

    def _on_fcm_push(ptype: int, sub_type: int, data: dict) -> None:
        """Handle FCM push notification."""

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

    fcm_client = DaelimFcmClient(hass, entry, _on_fcm_push)
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
        "listeners": [],
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Daelim SmartHome config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok and entry.entry_id in hass.data.get(DOMAIN, {}):
        data = hass.data[DOMAIN].pop(entry.entry_id)
        for unsub in data.get("listeners", []):
            try:
                unsub()
            except Exception:  # noqa: BLE001
                pass
        if "fcm_client" in data:
            await data["fcm_client"].stop()
        if "client" in data:
            data["client"].disconnect()
    return unload_ok
