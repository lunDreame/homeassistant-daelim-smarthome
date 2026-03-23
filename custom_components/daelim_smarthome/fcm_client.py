"""FCM Push client for Daelim SmartHome."""

from __future__ import annotations

import logging
from typing import Callable

from firebase_messaging import FcmPushClient, FcmRegisterConfig
from homeassistant.config_entries import ConfigEntry

from .const import (
    FCM_API_KEY,
    FCM_APP_ID,
    FCM_PROJECT_ID,
    FCM_SENDER_ID,
)

_LOGGER = logging.getLogger(__name__)
CONF_FCM_CREDENTIALS = "fcm_credentials"


class DaelimFcmClient:
    """FCM client wrapper for Daelim SmartHome push notifications."""

    def __init__(
        self,
        hass,
        entry: ConfigEntry,
        on_push: Callable[[int, int, dict], None],
    ) -> None:
        """Initialize FCM client."""
        self.hass = hass
        self.entry = entry
        self.entry_id = entry.entry_id
        self.on_push = on_push
        self._client: FcmPushClient | None = None
        self._credentials: dict | None = None
        self._fcm_token: str | None = None

    def _on_notification(self, data: dict, persistent_id: str, context: object) -> None:
        """Handle incoming FCM notification."""
        if not data or not isinstance(data, dict):
            return
        try:
            ptype = int(data.get("data1", data.get("type", 0)))
            sub_type = int(data.get("data2", data.get("subType", 0)))
        except (TypeError, ValueError):
            return
        _LOGGER.debug("FCM push: type=%s, subType=%s, data=%s", ptype, sub_type, data)
        self.on_push(ptype, sub_type, data)

    def _on_credentials_updated(self, credentials: dict) -> None:
        """Persist credentials when updated."""
        self._credentials = credentials
        self.hass.add_job(self._save_credentials_to_entry, credentials)

    def _load_credentials_from_entry(self) -> dict | None:
        """Load credentials from config entry data."""
        credentials = self.entry.data.get(CONF_FCM_CREDENTIALS)
        return credentials if isinstance(credentials, dict) else None

    def _save_credentials_to_entry(self, credentials: dict) -> None:
        """Save credentials into config entry data."""
        current = self.entry.data.get(CONF_FCM_CREDENTIALS)
        if current == credentials:
            return
        updated_data = dict(self.entry.data)
        updated_data[CONF_FCM_CREDENTIALS] = credentials
        self.hass.config_entries.async_update_entry(self.entry, data=updated_data)

    async def start(self) -> str | None:
        """Start FCM client and return FCM token for PUSH_REQUEST."""
        try:
            if self._credentials is None:
                self._credentials = self._load_credentials_from_entry()
            config = FcmRegisterConfig(
                project_id=FCM_PROJECT_ID,
                app_id=FCM_APP_ID,
                api_key=FCM_API_KEY,
                messaging_sender_id=FCM_SENDER_ID,
            )
            self._client = FcmPushClient(
                callback=self._on_notification,
                fcm_config=config,
                credentials=self._credentials,
                credentials_updated_callback=self._on_credentials_updated,
            )
            self._fcm_token = await self._client.checkin_or_register()
            if not self._fcm_token:
                _LOGGER.error("FCM token not received")
                return None
            await self._client.start()
            _LOGGER.info("FCM client started, token registered")
            return self._fcm_token
        except KeyError as err:
            _LOGGER.error("FCM credentials structure error: %s", err)
            return None
        except Exception as err:
            _LOGGER.error("FCM client start failed: %s", err)
            return None

    async def stop(self) -> None:
        """Stop FCM client."""
        if self._client:
            try:
                await self._client.stop()
            except Exception as err:
                _LOGGER.debug("FCM stop error: %s", err)
            self._client = None
        self._fcm_token = None
