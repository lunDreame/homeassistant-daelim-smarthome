"""Camera platform for Daelim SmartHome."""

from __future__ import annotations

import binascii
from typing import Any

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, MANUFACTURER

CAMERA_DEVICES = [
    ("FD-CAM0", "세대현관", "door_record_duringlist"),
    ("CE-CAM0", "공동현관", "lobby_record_duringlist"),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Daelim cameras from config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    client = data["client"]
    entry_id = entry.entry_id
    complex_name = entry.data["complex"]

    entities = []
    for device_id, name, location in CAMERA_DEVICES:
        entities.append(
            DaelimCameraEntity(
                client,
                entry_id,
                device_id,
                name,
                complex_name,
                location,
            )
        )
    async_add_entities(entities)


class DaelimCameraEntity(Camera):
    """Daelim intercom camera - shows visitor snapshot when available."""

    def __init__(
        self,
        client,
        entry_id: str,
        device_id: str,
        name: str,
        complex_name: str,
        location: str,
    ) -> None:
        """Initialize camera."""
        super().__init__()
        self._client = client
        self._entry_id = entry_id
        self._device_id = device_id
        self._attr_name = name
        self._attr_unique_id = f"{entry_id}_{device_id}_camera"
        self._complex_name = complex_name
        self._location = location
        self._snapshot: bytes | None = None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}_{self._device_id}")},
            manufacturer=MANUFACTURER,
            model=self._complex_name,
            name=self._attr_name,
        )

    async def async_camera_image(
        self,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes | None:
        """Return camera image."""
        visitor_list = await self._client.visitor_list(page=0, listcount=1)
        if not visitor_list or "list" not in visitor_list or not visitor_list["list"]:
            return self._snapshot

        history = visitor_list["list"][0]
        if history.get("location") != self._location:
            return self._snapshot

        index = int(history.get("index", 0))
        resp = await self._client.visitor_check(index, "Y")
        if not resp or "image" not in resp:
            return self._snapshot

        hex_str = resp["image"].replace("\r", "").replace("\n", "")
        hex_str = hex_str.replace(" ", "")
        try:
            hex_bytes = bytes.fromhex(hex_str)
            self._snapshot = hex_bytes
            return self._snapshot
        except (ValueError, binascii.Error):
            return self._snapshot
